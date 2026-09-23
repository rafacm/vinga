"""The bespoke conversation runtime: VAD, ASR, an LLM tool loop, and TTS.

One utterance at a time, run behind the device-facing boundary. It talks
as one agent at a time, the active agent, picked at connect from the
agents the device is bound to; prompt, providers, and endpointer all come
from that agent, so swapping it swaps all three.

While the device listens, decoded mic audio feeds the agent's
endpointer; when the utterance ends, ASR transcribes it, the LLM streams
a reply into sentences, and TTS speaks each sentence back through the
device. Conversation history lives here, one list of turns per
connection.

The reply is a tool loop, and the loop lives here rather than in a
provider because only the runtime can change agents between rounds. Per
reply it snapshots the tools the active agent may use, streams, executes
whatever the model asked for, feeds the results back, and streams again,
up to a small cap whose last round forbids calling so a reply always
ends in speech. Executing a round's calls is `ToolExecution`'s
([tool_execution.py](tool_execution.py)): classifying, reserving,
coercing, bounding, dispatching and reporting each one. The moves stay
here, because a move rebinds the conversation and ends the loop.
History stays text-only: the structured tool turns exist in a working
copy inside one reply, and what survives is what was actually said
aloud.

A sentence of that reply is spoken unless it is shaped like a call to
one of the tools the same snapshot offered, which is a model writing
its own calls into its speech rather than an answer (#385). Such a
sentence is dropped whole, reported as its own event, and enters
nothing: not the leg, not the history, not the record. A reply that
ends having spoken none of its sentences and withheld some says the
agent's fixed fallback phrase, because what the user is otherwise
handed is exactly the silence that phrase exists to end.

An utterance that ends while a reply is streaming cancels that reply and
is answered, which is what barge-in is. An endpointer-driven cancel is
gated: a reply is only cancelled on evidence of user speech (enough
classified speech, a transcript when in doubt), because acoustics alone
are as often noise or the reply's own bleed as the user (#28). A manual
`listen stop` mid-reply is a deliberate act and cancels unconditionally.

What happens in a conversation is logged twice over: as a human
sentence, and as the structured fields the JSON log format emits as
top-level keys. Both halves go out through the session's
`SessionEvents` ([events](../events/__init__.py)), so that every record carries
the same channel and the same identity whichever side of the boundary
emitted it, and so that every consumer of the events sees it.
"""

import asyncio
import contextlib
import functools
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Protocol

from vinga_server.audio.resample import Resampler
from vinga_server.config import Config
from vinga_server.config.store import LiveDevice
from vinga_server.conversations.records import (
    MilestoneRecord,
    SessionTurns,
    TurnRecorder,
    TurnStore,
)
from vinga_server.device.boundary import (
    PIPELINE_SAMPLE_RATE,
    DeviceGone,
    DeviceOutput,
    PlayableAudio,
    RuntimeFactory,
    SessionInput,
)
from vinga_server.events import SessionEvents, assembly, logger
from vinga_server.events.catalog import (
    AgentSaid,
    ConversationResumed,
    Handover,
    MilestoneRecorded,
    NothingHeard,
    PromptAssembled,
    Replied,
    ReplyFinished,
    TranscriptionAbandoned,
    TurnStarted,
)
from vinga_server.events.values import (
    ABSENT,
    ConversationId,
    Count,
    FallbackReason,
    Flag,
    Identifier,
    LlmPurpose,
    PromptSources,
    Real,
    ReplyOutcome,
    UtteranceId,
    Whole,
)
from vinga_server.filler import FallbackClip, FillerClips
from vinga_server.generation import Generation, Generations
from vinga_server.memory.store import NOTHING_REMEMBERED, MemoryStore
from vinga_server.providers import (
    AgentProviders,
    TextDelta,
    ToolCall,
    ToolChoice,
    ToolResult,
    TtsProvider,
    Turn,
    Usage,
)
from vinga_server.runtime import prompt, resumption
from vinga_server.runtime.filler_runner import FillerRunner
from vinga_server.runtime.provider_watch import ProviderWatch
from vinga_server.runtime.reply_in_flight import ReplyInFlight, SpeakingPass
from vinga_server.runtime.speech import _Synthesis, speak_after
from vinga_server.runtime.tool_execution import DEFAULT_TOOL_TIMEOUT_S, Offer, ToolExecution
from vinga_server.runtime.turns import TurnUnderway
from vinga_server.runtime.turntaking import Confirmation, TurnTaking, Utterance
from vinga_server.session_conversations import SessionConversations, mint
from vinga_server.text import SentenceSplitter
from vinga_server.tools import builtin, names
from vinga_server.tools.mcp import McpServers
from vinga_server.tools.source import (
    BuiltinTools,
    DeviceTools,
    McpTools,
    ToolSource,
)

if TYPE_CHECKING:
    # The post-close surface this runtime hands each assembled request
    # to, named rather than imported: `llm_input_export.py` imports
    # `telemetry.py`, which nothing here does, and a runtime import
    # would make the reply path pay for a module it only ever holds.
    # The device edge names its own collaborator the same way.
    from vinga_server.llm_input_export import LlmInputExport
    from vinga_server.transcript_export import TranscriptExport

# How many times one reply may stream, call tools, and stream again.
# The last permitted round forbids calling, so a reply always ends in
# speech rather than in a tool nobody hears the result of.
MAX_TOOL_ROUNDS = 4

# The synthetic user turn a conversation opens on when a reply moves to
# one, in the three shapes a move has. It exists because both APIs need
# a fresh completion to end on a user turn, and because a thread that
# began with an assistant greeting would read as an answer to nobody.
#
# Written into the target thread's history rather than kept for one
# round, which is what changed when histories became per thread (#190):
# it is that conversation's opening line, the model reads it on every
# later round of the same thread, and it says nobody said it out loud.
# The stored record is untouched by it: a turn is what a user said and
# what was replied, and none of these three was said by anyone.
SWITCH_GREETING = (
    "You have just taken over this conversation from another assistant. "
    "Greet the user briefly as yourself, in the language they have been "
    "speaking, and carry on from what was said above."
)

FRESH_GREETING = (
    "The user has asked to start a new conversation. Nothing that was "
    "said earlier is available to you here. Greet them briefly as "
    "yourself, in the language they have been speaking, and ask what "
    "they would like to talk about."
)

RESUMED_GREETING = (
    "You have just resumed an earlier conversation with this user, and "
    "what is above is what was said in it. Greet them briefly, say in "
    "one sentence what the two of you were talking about, and carry on "
    "from there, in the language they have been speaking."
)

# What a resumed conversation is additionally told about its own record,
# appended to the seed above where each applies. Fixed sentences from a
# closed set, chosen where the resume is decided: what they exist for is
# an agent that does not claim to remember what it cannot see.
RESUMED_FROM_RECENT = (
    " Only the most recent part of that conversation is above; what came "
    "before it is not available to you, so do not claim to remember the "
    "whole of it."
)
RESUMED_WITH_GAPS = (
    " Parts of that conversation were never stored, so there are gaps in "
    "what you can see; say so plainly if the user asks about something "
    "that is missing."
)
RECAP_UNAVAILABLE = (
    " The recap the user asked for could not be made just now, so what is "
    "above is only the recent part; tell them that rather than summarizing "
    "what you cannot see."
)

# What the round after a consented recap is told, in place of the
# ordinary resumed greeting. The recap has already been spoken, by this
# runtime and in the agent's own voice, so the one thing this seed has
# to prevent is the model saying it again.
RECAPPED_GREETING = (
    "You have just resumed an earlier conversation with this user and read "
    "them the recap above, which is your own summary of the whole of it. "
    "They have heard it: do not repeat it. Ask them briefly what they would "
    "like to pick up from it, in the language they have been speaking."
)

# The summarization round, which is one round against the active agent's
# own provider and produces the words the user then hears.
#
# The instruction is fixed and carries nothing a room said. What it asks
# for is a recap that can be spoken: a paragraph, in the language the
# conversation was held in, because the text that comes back is fed to
# synthesis verbatim and stored byte for byte as it was heard.
RECAP_INSTRUCTION = (
    "You are summarizing an earlier conversation between an assistant and a "
    "user so that the assistant can pick it up again. Write the summary as "
    "the assistant would say it out loud to the user: one short paragraph, "
    "plain sentences, no headings, no lists and no markup of any kind. Say "
    "what the two of you talked about and where it was left. Write it in the "
    "language the conversation was held in. Answer with the summary and "
    "nothing else."
)
RECAP_REQUEST = "Recap the conversation above for me, out loud, in a few sentences."

# How long that round may take before the recap is given up on and the
# thread is resumed from its recent tail instead.
#
# Its own bound rather than the reply's: the user has asked for a
# summary and is waiting through silence for it, and the whole of what
# a slow one costs is that they hear the fallback sentence instead.
RECAP_ROUND_TIMEOUT_S = 30.0

# How long the recap's own write is waited on before the runtime stops
# waiting, having already spoken it.
#
# The wait exists only to decide whether to say the checkpoint landed.
# It is bounded because the user is at the far end of a conversation
# that has to continue; a write that commits after this is late rather
# than lost, and it can never be a summary nobody heard, because nothing
# is enqueued until the playback finished.
MILESTONE_ACKNOWLEDGEMENT_S = 2.0

# The abort reasons a device may send that this side knows by name. The
# firmware's `AbortReason` enum has exactly two members
# (`main/protocols/protocol.h` in 78/xiaozhi-esp32): `kAbortReasonNone`,
# which sends no `reason` field at all, and
# `kAbortReasonWakeWordDetected`, which sends the string below.
#
# Closed rather than passed through because the field is a string a
# peer wrote, and the upstream protocol note says as much: "`reason`
# may be `wake_word_detected` or other implementation-defined values"
# (`docs/websocket.md`). Anything outside the set is logged as `other`
# and its value is not repeated anywhere, which is the same rule the
# tool-name events follow (#154, #185).
#
# Absence is not a member. A device that sends no reason is reported as
# `none`, and a device that sends the word "none" is a device sending a
# reason the firmware has no member for, which is `other` like any
# other unknown: the two facts stay distinguishable on the line.
DEVICE_ABORT_REASONS = frozenset({"wake_word_detected"})


class DeviceRecords(Protocol):
    """The device record, as a reply reads it.

    Named here rather than imported because this is the side that says
    what it needs: one question, asked once per round, about the record
    this conversation attached to at its connect rather than about a
    MAC. It answers None rather than raising, both for a record that is
    gone and for a database that could not be read. What answers it in a
    server is `device.bindings.DeviceBindings`, which is also where a
    failed read is logged and fallen back from; a runtime built without
    one is a runtime whose replies say nothing about the device, which
    is what every deployment sent before there was a record to read.
    """

    async def resolve_record(self, attached: LiveDevice) -> LiveDevice | None: ...


class AgentNotAllowed(ValueError):
    """Something asked a session to become an agent its device is not
    bound to. The switch_agent tool turns this into a spoken refusal,
    phrased by the agent that is already talking; anywhere else it can
    only mean a bug."""


def _not_allowed(name: str, agents: Sequence[str]) -> AgentNotAllowed:
    """The refusal, built in one place because the model is shown the
    same text the enforcement raises."""
    return AgentNotAllowed(
        f'this device is not bound to agent "{name}"'
        + (f" (bound to: {', '.join(agents)})" if agents else "")
    )


@dataclass(frozen=True)
class _Recapped:
    """A recap that has been made and not yet spoken.

    Carried on the transition rather than acted on where it was made,
    because the two things still owed to it happen at the boundary: the
    text is spoken on the thread the reply began on, and the checkpoint
    is stored only once it has been. Holding the summarizer's answer
    beside the range it was made from is what keeps the row and the
    speech one decision: `text` is fed to synthesis verbatim and written
    to the column verbatim, and `made_from` is the coverage it is
    allowed to claim.
    """

    text: str
    made_from: resumption.Recap


@dataclass(frozen=True)
class _Transition:
    """What a tool loop ended for, and what happens at the boundary.

    One type for the three moves, because they differ in what they
    rebind and agree on everything else: each ends the loop, lets the
    turn finish on the thread it started on, and opens a round on the
    other side seeded with a synthetic user turn. Handing the loop back
    a type rather than an agent name is what lets a resume travel with
    the history it brings.

    `agent` is set by a handover and by nothing else; `conversation` by
    the two moves that change which thread the agent is on. Exactly one
    of the two is ever set, which is the whole of the shape.
    """

    seed: str
    agent: str | None = None
    conversation: str | None = None
    history: tuple[Turn, ...] = ()
    # What the resume found, for the event emitted at the boundary. None
    # for a handover and for a fresh conversation, neither of which read
    # anything back.
    resumed: resumption.Resumed | None = None
    # The recap this move owes the user, for the one move that has one.
    # Spoken at the boundary and stored after it has been heard, both by
    # the reply path, which is the only place that can know playback
    # finished.
    recap: _Recapped | None = None


class PipelineRuntime:
    """One conversation, for one connection, behind the device edge.

    `output` is the device it speaks through, and it is the whole of
    what this runtime knows about the far end: no socket, no protocol,
    no codec. Built by `bespoke_runtime_factory` below, which is what
    the composition root hands the device edge.

    Four of the things it used to do are now modules of their own. Who
    holds the floor is `TurnTaking` ([turntaking.py](turntaking.py)),
    which reaches back into four of this class's methods and nothing
    else; this world's cached speech is `FillerRunner`
    ([filler_runner.py](filler_runner.py)), which reads the floor with
    two questions and never writes it; how a provider call is watched
    is `ProviderWatch` ([provider_watch.py](provider_watch.py)), which
    is handed the round and the turn it reports on rather than reading
    either off this class; and running a round's tool calls is
    `ToolExecution` ([tool_execution.py](tool_execution.py)), which is
    handed the turn it files on at every call and asks this class two
    questions through callables, the memory policy and who owns a tool
    name now, and writes nothing of this class's but that turn. What
    stays here is the orchestration: the reply in flight, the
    conversation history, the tool loop and its moves, and agent
    handover.

    Two of a reply's three lifetimes are values rather than fields
    ([reply_in_flight.py](reply_in_flight.py)), each made where its
    lifetime begins so that being fresh is what making one means: a
    `ReplyInFlight` per started reply, holding its task, how it ended
    and the utterance it answers, and a `SpeakingPass` per pass of the
    speaking loop, holding the round count and whether anything was
    spoken or withheld. The third, the memory permission per agent leg,
    is `_remembering` below.

    The runner owns two verbs and this class uses both: the reply path
    arms the latency mask at the transcription and settles it at the
    end, and two arms ask it to say the agent's fixed phrase, the one
    that catches a terminal failure and the check at the end of a reply
    that spoke nothing because every sentence of it was withheld.
    Saying the phrase adds nothing here: what it needs is a read of the
    world's cache and the output handle, both of which are the runner's
    already, so a failed turn speaks without this class learning
    anything new to remember (#384). Deciding whether the second arm
    fires does, and it is the speaking pass's pair of reply-wide facts,
    because the question is about the whole reply and nothing the
    runner holds can see one (#385).

    The mutable state that crosses those responsibilities, listed
    because it is what a reader has to hold in mind at once (#141).
    Three entries this list used to carry are the values' now and are
    no longer fields here: `_reply_task`, and the outcome latch and
    utterance id beside it, are `ReplyInFlight`'s; `_llm_round`,
    `_reply_spoke` and `_reply_withheld` are `SpeakingPass`'s.

    - `_in_flight`: the reply `start_reply` last started, replaced by
      the next one, read by `replying` and `drain`, and let go by
      `cancel_reply` only if it is still the reply that cancel ended.
      The turn-taking side and the device edge both ask about the reply
      in flight, and both ask through those methods, so the field
      itself keeps one owner. The reply body is handed its value rather
      than reading this, so which reply is current never decides what a
      body latches or reports.
    - `_providers` and `_know_how`: written by `_activate_agent` alone,
      at connect and at a handover, and read by every leg of the reply
      that follows, `confirm_transcript` included. That one reads it
      before an await a handover can land in, and answers with the ear
      it read, for the reason `Confirmation` gives.
    - `_asr_language`: written where the reply's own ASR answers, read
      by that call and by the confirmation the gate ladder asks for, so
      the session's language lock survives an interruption.
    - `_turn`: the record being assembled, replaced at the start of each
      reply and again at each move the reply makes, written from half a
      dozen places in the loop, and read by `_record_turn` at the end of
      whichever conversation it belongs to. The pair it is stamped with
      at replacement is the pair the turn is attributed to.
    - `conversations`: the device session's conversations
      ([session_conversations.py](../session_conversations.py)), which
      this runtime is handed and never makes: each agent's current
      thread, every thread's history, the store's handle for each
      thread's last write, and who is talking now. Written through its
      transitions alone (`_activate_agent` activates, `_move_to` starts
      a new thread or reactivates a stored one, the recording site
      acknowledges), and read through `_agent`, `_conversation`,
      `_device` and `_turns`, which are reads of it rather than fields.
      Public, because the edge holds the same object and reads the pair
      off it for what it stamps.
    - `_resumption`: this session's offered-candidate state and its way
      into the store, absent where the deployment did not ask for
      resumption, which is what makes both conversation tools answer a
      spoken refusal instead of moving anything.
    - `_pass`: the speaking pass `_speak_reply` made at its top,
      replaced whole by the next one. The tool loop counts its rounds
      on it and hands the watch the round for its retry line and for
      `llm_round`; the loop's two sentence sites mark it withheld
      through `_withheld`; `_speak_reply` marks it spoken at each
      leg and at the end, and reads the pair to decide the fallback. A
      field rather than a local of `_speak_reply` because the
      withholding is decided a call away, inside the tool loop.
    - `_remembering`: whether the agent speaking may reach memory,
      written by `_tool_loop` alone where it takes the tool offer and
      read through `_remembering_now` by the builtin source's offer and
      dispatch, by tool execution before it answers a call at all, and
      by `_system_prompt`. A field rather than an argument
      because those two readers are on two clocks, and one field is what
      makes them one answer.
    - `_agent`: a read of `conversations` rather than a field, because
      both sides of the boundary attribute events to whoever is talking,
      so the device session's conversations are the one place it can
      live.
    """

    def __init__(
        self,
        output: DeviceOutput,
        generations: Generations,
        generation: Generation,
        events: SessionEvents,
        conversations: SessionConversations,
        agent_providers: Mapping[str, AgentProviders],
        mcp_servers: McpServers,
        memory: MemoryStore,
        fillers: Mapping[str, FillerClips],
        agents: Sequence[str],
        fallbacks: Mapping[str, FallbackClip] = MappingProxyType({}),
        recorder: TurnRecorder | None = None,
        threads: resumption.ThreadReads | None = None,
        purge: Callable[[Sequence[str]], object] | None = None,
        devices: DeviceRecords | None = None,
        device_access: builtin.DeviceAccess | None = None,
        device: LiveDevice | None = None,
        llm_input: "LlmInputExport | None" = None,
        transcripts: "TranscriptExport | None" = None,
    ) -> None:
        self._output = output
        # The world this runtime reads its configuration out of, asked
        # rather than kept: a reload replaces it, and the two reads
        # below are at the two moments the answer is allowed to change
        # (#191). An activation assembles the prompt from the generation
        # current at that instant; the reply's own timeout is a
        # restart-only setting that every generation carries the same
        # value of.
        self._generations = generations
        # And the world this conversation was built from, kept because
        # an activation may have to fall back to it: an apply can delete
        # an agent this device is bound to, and a handover to it has to
        # read the prompt world it was last served with rather than
        # index a current world that has never heard of it. Everything
        # else this runtime speaks through came out of this object at
        # construction, so keeping it costs nothing that was not already
        # being held.
        self._generation = generation
        # The file half, taken once because a generation never replaces
        # it: a reload composes the stored domain half onto this
        # process's own server section, so every generation carries the
        # same one.
        self._server = generations.current().config.server
        self._events = events
        self.session_id = events.session_id
        # The device session's conversations: which thread each agent is
        # on, every thread's history, the store's handle for each
        # thread's last write, and who is talking now. Constructed by
        # the edge and handed in, never made here, because they belong
        # to the device session rather than to this runtime, and a
        # runtime that could make its own would be a second authority.
        # Public, because it is part of what this runtime is rather than
        # a detail of how it works: the edge reads the same object, and a
        # test holds the two to being one with `is`.
        self.conversations = conversations
        self._agent_providers = agent_providers
        self._mcp_servers = mcp_servers
        self._memory = memory
        # How a reply asks what device it is speaking through, and None
        # for a runtime composed without one, which sends the prompts it
        # sent before a device had a name. Asked per round beside the
        # memory read rather than captured at the activation: the name
        # is stable, the location is not, and the tool that moves a
        # device is reached from inside the conversation it moves.
        self._devices = devices
        # And the record this conversation attached to, resolved by the
        # edge in the same snapshot the binding came from and never
        # replaced. It is an ADDRESS and not a value: what a round
        # renders is what the read above answers, and this is only how
        # that read says which record it means. Keeping the connect's
        # copy as the address is the point, since a MAC can be deleted
        # and bound again, or moved to another record, under a
        # conversation that is still talking. None is a board with no
        # record, whose replies say nothing about their device.
        self._attached = device
        # And the seam that holds that record's address still while a
        # tool writes what the device remembers. The same object the
        # location tool writes through, asked one question earlier: it
        # owns the domain writer lock, which is what orders a `remember`
        # against a board swap (#449, M4). None is a server that keeps
        # no writable records, whose device memory is filed under the
        # board this session is talking to and cannot be moved by
        # anything.
        self._filing = device_access
        # The conversation's content channel, beside the event tap and
        # separate from it on purpose: tool arguments and results never
        # rode the events, and the events are losing their text (#120).
        # None means nobody is listening, which is every deployment until
        # the store is wired, and the reply path then behaves exactly as
        # it did before the channel existed.
        self._recorder = recorder
        # And where each round's assembled request goes, when a
        # deployment asked for that (#502). An optional collaborator
        # exactly like the recorder above, compared `is not None`, and
        # the reason the comparison is at the two call sites rather than
        # once: with this absent nothing is rendered at all, which is
        # what "the flag off stages nothing" means concretely.
        self._llm_input = llm_input
        self._transcripts = transcripts
        # How every provider call a reply makes is watched: a failure
        # reported and raised on, an LLM's first token bounded and
        # retried once, a finished round reported and filed
        # ([provider_watch.py](provider_watch.py)). The bound is the
        # server section's, taken once for the reason `_server` above
        # is; the round and the turn are the reply's, handed over per
        # call.
        self._watch = ProviderWatch(
            events, conversations, self._server.llm_first_token_timeout_s, llm_input
        )
        # How this session's threads lose their memory when it closes,
        # and absent wherever a thread outlives its connection. Present
        # only on a deployment that records nothing, where a closed
        # session's threads can never be resumed and no erasure or
        # retention will ever come for them, which makes the close the
        # thread's end. Compared `is not None` at the one call site.
        self._purge = purge
        # Whether this server can find a past conversation and pick it
        # up again, and the whole of what says so: absent unless the
        # deployment asked for it, and compared `is not None` by the two
        # tools and by the interception alike. The switch is read here
        # rather than by whoever built the read seam, so the answer to
        # "can this session resume" has one home.
        #
        # Per session, because what it holds is what this session's
        # agents were offered. The bound it reads the store under is the
        # tool bound, since every read it makes happens inside a tool
        # call the user is waiting through.
        section = self._server.conversations
        self._resumption = (
            resumption.Resumption(
                threads, section.resumption_budget_tokens, DEFAULT_TOOL_TIMEOUT_S
            )
            if threads is not None and section is not None and section.resumption
            else None
        )
        # The turn being assembled, replaced at the start of every reply
        # and read once at the end of it. Always present rather than
        # optional: the reply path writes into it from half a dozen
        # places, and a guard at each of them would be six chances to
        # forget one. Installed below, after the first activation, since
        # it carries the pair that activation decides.
        self._turn: TurnUnderway
        # The agents this device may talk to. The one it is talking to
        # now is the device session's conversations' to say, because
        # both sides of the boundary attribute events to it.
        self._agents: list[str] = []
        self._providers: AgentProviders | None = None
        # The half of the system prompt that belongs to the agent rather
        # than to the moment: its persona and the guidance of the MCP
        # entries it is granted, assembled once per activation and held
        # here for the life of it. Nothing about it is recomputed per
        # reply; what is, is the memory block appended to it.
        self._know_how: prompt.Assembled | None = None
        # The speaking pass now running, or the last one to have run:
        # its round count and whether any sentence of it went out or was
        # withheld ([reply_in_flight.py](reply_in_flight.py)). Replaced
        # whole at the top of every pass rather than reset field by
        # field, so a pass starts from nothing by construction. One made
        # here too, since no pass has run and it has counted nothing.
        self._pass = SpeakingPass()
        # Whether the agent speaking may reach memory, resolved once per
        # reply where the tool snapshot is taken and read from there by
        # the tools it offers and by every round's injected blocks. One
        # clock for both halves, so a reload landing mid-reply cannot
        # hand one reply the old policy's tools and the new policy's
        # prompt. None until the first reply resolves it, because there
        # is no honest value before then: an agent is what the policy is
        # about, and nothing asks this outside a reply.
        self._remembering: bool | None = None
        # The language the ASR provider asked this session to reuse
        # (`AsrResult.lock_language`). Session-scoped on purpose: the
        # provider is shared between sessions and holds no per-session
        # state, and the speaker does not change on an agent switch.
        self._asr_language: str | None = None
        # Who holds the floor: the mic feed, the utterance buffer and
        # the barge-in gates. It reaches back into four of this
        # runtime's methods and nothing else, so the reply task and the
        # conversation history stay on this side of the seam.
        self._turntaking = TurnTaking(events, output, self._server, self)
        # The reply `start_reply` last started: its task, how it ended
        # and the utterance it answers, in one value made per reply
        # ([reply_in_flight.py](reply_in_flight.py)). None until the
        # first utterance, and again once a cancel has seen its reply
        # through; a reply that finished on its own stays here, done,
        # until the next one replaces it.
        self._in_flight: ReplyInFlight | None = None
        # This world's cached speech, bound at construction: this turn's
        # latency mask if any agent this device is bound to has one, and
        # the phrase a failed reply says. It reads the floor with two
        # questions and answers it nothing, so the one field the two
        # clusters share (whether the outgoing frames are paused) has one
        # writer and one reader and crosses as a question.
        self._filler = FillerRunner(
            events,
            conversations,
            output,
            fillers,
            agents,
            self._turntaking,
            fallbacks,
        )
        self._agents = list(agents)
        # The three places a tool can come from, asked in the order the
        # namespace gives them: builtins are bare, the device's tools
        # carry its prefix, an MCP server's carry their entry's, and
        # configuration forbids an entry from taking either of the other
        # groups' names, so no two of these can own one name and the
        # order settles nothing that was in doubt. Each is handed the
        # default bound rather than reading it, so how long a builtin or
        # a device tool may take stays one answer, tool execution's.
        sources: tuple[ToolSource, ...] = (
            BuiltinTools(
                self._agents,
                memory,
                DEFAULT_TOOL_TIMEOUT_S,
                self._memory_context,
                self._remembering_now,
                self._resumption,
                # The other direction through the device rows, handed
                # straight over rather than kept: nothing else in a
                # reply writes a device. None is a server that cannot
                # write those records at all, and the tool then refuses
                # with a sentence saying so rather than not being
                # offered.
                device_access,
                # And the record this conversation attached to, as the
                # address every write to it uses, for the reason every
                # read of it uses one: a MAC is where a board is
                # standing and an id is which record it is. None is a
                # board with no record, whose conversation is told it
                # has nowhere to write a place to.
                None if device is None else device.id,
            ),
            DeviceTools(output, DEFAULT_TOOL_TIMEOUT_S),
            McpTools(mcp_servers, DEFAULT_TOOL_TIMEOUT_S),
        )
        # And what runs a round's calls over them. Built here because the
        # builtins above are handed this runtime's own state, and private
        # because nothing outside the reply asks it anything. The two
        # questions about the registries are asked when they are asked:
        # a board rediscovers its tools and an apply replaces the MCP
        # registry between two calls, and the registry is read off this
        # runtime's field for the same reason every other read of it is.
        self._tools = ToolExecution(
            sources,
            output.device_tools,
            lambda published: self._mcp_servers.owner_of(published),
            events,
            conversations,
            self._remembering_now,
        )
        # The activation the connect used to do by hand, and the MCP
        # revive that followed it, in that order. No task is spawned
        # here: the reply task is created on the first utterance, and
        # discovery belongs to the edge.
        self._activate_agent(self._agents[0])
        self._turn = self._fresh_turn(None)
        # A server that was down at boot, or that dropped since, gets a
        # background reconnect now, so it is picked up by the time this
        # conversation needs it rather than at the next server restart.
        # Which entries those are is asked of the registry rather than
        # resolved from this session's configuration: a reload replaces
        # the grants along with the managers they name, and the
        # configuration this session holds is the world it opened in.
        self._mcp_servers.revive_for_agents(self._agents)

    @property
    def _agent(self) -> str | None:
        """The agent talking now, read off the device session's
        conversations rather than kept: both sides of the boundary
        attribute their events to it, so it has one home and this is a
        read of it. None only before the constructor's first
        activation."""
        active = self.conversations.active
        return None if active is None else active.agent

    @property
    def _conversation(self) -> str | None:
        """The thread the active agent is on, read in the same place for
        the same reason: the edge's pacer stamps `speaking_started`
        about it without ever having activated anything."""
        active = self.conversations.active
        return None if active is None else active.conversation

    @property
    def _device(self) -> str:
        """The board this conversation is happening on, which is what
        the device scope of memory is addressed by where no record was
        resolved.

        Read off the device session's conversations, which the edge
        built from the MAC it normalized and which are that MAC's one
        authority: a second copy here would be a second answer to one
        question.
        """
        return self.conversations.device

    def _remembering_now(self) -> bool:
        """Whether the reply being spoken may reach memory at all.

        What the builtin source asks before it offers the memory family
        and again before it runs one of them, and what `_system_prompt`
        asks before it reads a scope. A callable rather than a value
        handed over at construction, because the answer belongs to the
        agent speaking and a session can hand over to a sibling with a
        different section; a read of what this reply resolved rather
        than of the world, because the world can move between two of
        this reply's rounds and the policy has one clock.

        Asserted rather than defaulted, the rule `_device_of` keeps: the
        resolution happens at the top of every tool loop, so a question
        asked before one is a defect here rather than a state to invent
        an answer for.
        """
        assert self._remembering is not None
        return self._remembering

    def _resolved_memory(self) -> bool:
        """This reply's answer, read out of the world at the moment the
        tool snapshot is taken."""
        assert self._agent is not None
        return self._world_of(self._agent).memory_for_agent(self._agent).enabled

    def _world_of(self, agent: str) -> Config:
        """Which configuration answers about this agent (#191).

        The current one, because that is what an activation converges at
        and the whole reason a reload reaches a conversation at all; the
        session's own when the current world has never heard of this
        agent, which is exactly the state an apply that deleted it
        leaves behind. This device is still bound to it and this
        conversation is still allowed to be talking as it, so it goes on
        being served the world it opened with rather than raising a
        KeyError inside a tool call.

        One home for that choice because two clocks make it: the prompt
        at an activation, and the memory policy at a reply.
        """
        current = self._generations.current().config
        return current if agent in current.agents else self._generation.config

    async def _memory_context(self) -> builtin.MemoryContext:
        """Which memory this session's tool calls belong to, asked at the
        moment a call runs.

        Not kept, because three of the four moves a reply can make change
        the answer: a note written after a session has moved to another
        thread belongs to the thread it is on now, and a note written
        after its board has been replaced belongs to the address that
        record stands at now (#449, M4).

        The device half is read here rather than taken from the session
        because a device's facts are filed under a MAC and the MAC this
        session dialled is not necessarily the one its record stands at
        any more. The record is resolved by the same lock-free read a
        round's prompt uses, which is enough for the two calls that only
        READ memory; the three that write ask `filing` for it again and
        hold it, because between an answer and a row is exactly where a
        swap fits.

        Falls back to the address this session is talking to, which is
        where a board with no record has always filed its facts and
        where a runtime composed without a store files all of them.
        """
        record = await self._device_record()
        return builtin.MemoryContext(
            device=self._device if record is None else record.mac,
            conversation=self._conversation,
            record=None if self._attached is None else self._attached.id,
            filing=self._filing,
        )

    @property
    def _turns(self) -> list[Turn]:
        """The history of the thread the active agent is on.

        A read of the device session's conversations, which own every
        thread's history: there is one right answer at any moment and
        every reader should be unable to reach a stale one. The append
        sites and the read site are unchanged by that; which list they
        reach is this line. Kept as a property rather than inlined at
        its sites because the suites reach it by this name.
        """
        return self.conversations.history()

    def _fresh_turn(self, utterance: str | None) -> TurnUnderway:
        """A turn beginning, stamped with the pair that owns it and the
        utterance it answers.

        The one place that pair is read off the runtime. Everything
        after it reads the snapshot, which is what keeps a handover turn
        on the thread it started on rather than the one it ended on.

        Both halves of the pair are asserted rather than defaulted: an
        agent is activated before this runtime can be asked for anything,
        and the thread is minted in that same activation, so a turn
        beginning without either is a defect here and not a row for the
        store to make sense of.

        The utterance is handed in rather than read, because it belongs
        to the reply rather than to the runtime, and it is not asserted:
        the turn installed at that first activation precedes every
        utterance, and a reply body driven without `start_reply` answers
        none. The first records nothing, since `record` answers None
        where nothing was heard, so the absence never reaches a row.
        """
        assert self._conversation is not None and self._agent is not None
        return TurnUnderway(self._conversation, self._agent, utterance)

    def _seeded_turn(self) -> TurnUnderway:
        """The first turn of the thread a reply has just moved onto.

        A turn with nothing heard on it, which is what the seeded round
        is: the user said what they said on the thread that was left,
        and this side's dialogue opens with an answer. So it carries a
        reading rather than an utterance, taken here because a turn
        needs an origin on the session's timeline and there is no
        `heard` event on this side to take one from.

        Stamped after the rebinding and never before it: the pair this
        reads is the one the move installed, which is the whole reason
        the record it produces lands on the other thread. The utterance
        is the departing turn's, which is what makes the two rows a
        moved reply records say they answer one thing the user said.
        """
        turn = self._fresh_turn(self._turn.utterance)
        turn.at = self._events.now()
        return turn


    # --- SessionInput: what the device edge asks of this runtime -------

    async def audio(self, pcm: bytes) -> None:
        """One decoded mic frame, at `PIPELINE_SAMPLE_RATE`, for whoever
        is deciding who holds the floor."""
        await self._turntaking.feed(pcm)

    async def listen_started(self) -> None:
        """The device asked to listen. Which mode it asked in is the
        edge's business; what this side does is start a fresh
        utterance."""
        self._turntaking.restart()

    async def listen_stopped(self) -> None:
        """A manual end of utterance."""
        await self._turntaking.manual_stop()

    async def device_aborted(self, reason: str | None) -> None:
        """The device gave up on the answer: the reply in flight dies
        and the utterance starts over.

        The reason is named only when it is one this side knows
        (`DEVICE_ABORT_REASONS`), because it arrives as a free string
        from the far side of the wire and this line is kept. An abort
        that carried no reason at all is `none`; anything else this
        side does not know is `other`."""
        # Absence is `none` and a value this side does not know is
        # `other`, which are different facts: `reason or "none"` would
        # report an abort carrying an empty string as though the field
        # had not been sent, and an empty string is something a device
        # chose to send.
        if reason is None:
            token = "none"
        else:
            token = reason if reason in DEVICE_ABORT_REASONS else "other"
        logger.info("session %s: device aborted (%s)", self.session_id, token)
        await self.cancel_reply(ReplyOutcome.ABORTED)
        self._turntaking.restart()

    def replying(self) -> bool:
        """Whether a reply is streaming right now, which is what both
        halves of the barge-in decision turn on, and what the edge's own
        jobs (the barge-in-off frame guard, the idle watchdog) ask."""
        return self._in_flight is not None and self._in_flight.running()

    async def drain(self, grace_s: float) -> bool:
        """Let a reply in flight finish, whether it is already speaking
        or still generating, and answer whether it did within
        `grace_s`. Never cancels it, and counts a failed reply as a
        finished one."""
        reply = self._in_flight
        return True if reply is None else await reply.drain(grace_s)

    async def close(self) -> None:
        """The conversation is over.

        Where nothing is recorded, this is also the end of every thread
        this session opened: none of them has a row, none of them can be
        resumed, and no retention pass will ever reach them. So their
        ledgers and the facts they were holding for an undo go here, off
        the loop like every other database call and contained by the
        store like every other lifecycle cleanup, which is what keeps a
        process that never restarts from accumulating them.
        """
        await self.cancel_reply(ReplyOutcome.ABORTED)
        if self._purge is not None:
            # Each agent's CURRENT thread, as it always was, and not
            # every thread a move left behind: the conversations' own
            # method says which in its name.
            await asyncio.to_thread(
                self._purge, list(self.conversations.current_threads())
            )

    # --- the device's outgoing audio, arbitrated against the filler ----

    async def _send_reply_audio(self, batch: PlayableAudio) -> None:
        """Send a batch of the reply's own audio.

        A batch with nothing in it is not audio and never reaches the
        arbitration: a chunk too short to fill a frame must not be read
        as "the reply is ready" and stand an unfired filler down. Once
        there is something to play, a clip already sounding is waited
        out so the first real sentence queues behind its tail. The
        filler's own frames go straight to the device, which is what
        keeps this from waiting on itself."""
        if not batch:
            return
        await self._filler.tail()
        await self._output.send_audio(batch)

    def _activate_agent(self, name: str) -> None:
        """Talk as this agent from now on: its prompt, its providers, and a
        fresh endpointer from its VAD, since the previous agent's endpointer
        carries the previous agent's tuning and mid-utterance state. Called
        once at connect, and again mid-reply when switch_agent hands the
        conversation over.

        The history does not carry across the switch, and that is the
        behavior #190 changed here: a conversation is a thread between a
        user and exactly one agent, so binding the incoming agent to its
        own thread is also binding it to its own history. What it starts
        with is the seed the transition writes; what it comes back to on
        a second handover is what it said the first time. Agents are
        scoped on purpose, and a switch that handed the whole session
        over would leak around that scoping and would move words spoken
        to a local agent to whatever provider the incoming one runs on.

        This is also where the know-how half of the system prompt is
        assembled, which is the whole of when it happens: at session
        open and again at an agent switch, and never per reply. Nothing
        is fetched here, because nothing needs to be: the persona is
        configuration this server is already holding and the guidance is
        what the registry's slice holds, so a reload that landed since
        is picked up by the next session or the next switch rather than
        by a conversation in flight.

        The device's bound list is enforced here rather than left to
        callers, because the next caller is a tool whose argument a model
        chose: an agent that merely exists is not one this device may
        talk to. Nothing is swapped when the name is refused, so the
        session keeps the agent it already had.

        Which world the prompt is read out of is the one decision here
        that is not obvious (#191), and it is `_world_of`'s: the current
        one, or the session's own where an apply has deleted this agent
        underneath a conversation still allowed to hand over to it.
        """
        if name not in self._agents:
            raise _not_allowed(name, self._agents)
        # The thread this agent is on in this device session: minted the
        # first time it is activated and continued on every later
        # activation, so switching away and back returns to the same
        # conversation. The conversations' rule, and one call, so no
        # reader can see this agent beside the previous one's thread.
        self.conversations.activate(name)
        self._providers = self._agent_providers[name]
        config = self._world_of(name)
        self._know_how = prompt.know_how(
            config.prompt_for_agent(name),
            config.fragments_for_agent(name),
            self._mcp_servers.guidance_for_agent(name),
        )
        self._prompt_assembled(name, self._know_how)
        self._turntaking.endpointer = self._providers.vad.new_endpointer()
        self._turntaking.restart()

    def _prompt_assembled(self, agent: str, half: prompt.Assembled) -> None:
        """One `prompt_assembled` event: what this agent's know-how half
        was made of, and how big each piece of it is.

        The decision-site rule applied to prompt size. Every injected
        block competes with the rest for the budget of a small local
        model, and when one degrades in the field the retained logs
        should say what its prompt held without anybody reproducing the
        session.

        Memory is deliberately outside it. This fires where the
        know-how half is actually assembled, once per activation, while
        memory is read per round; emitting per round would double a
        round's log volume for a number that moves slowly, and
        `llm_round` already carries that round's token counts. The
        inspection surface reads memory fresh and answers its size on
        demand.
        """
        self._events.emit(
            lambda: PromptAssembled(
                agent=Identifier(agent),
                conversation=ConversationId(self._conversation),
                characters=Count(half.characters),
                sources=PromptSources(half.sizes()),
            )
        )

    async def _reply(self, utterance: Utterance, reply: ReplyInFlight) -> None:
        """Run one utterance through ASR, the LLM, and TTS. Cancelled by
        `abort`; provider failures end the reply but not the session. The
        closing `tts stop` is sent even then, because the device (in auto
        mode) waits for it before listening again.

        `reply` is the value this body runs as, and it is what every
        outcome below is latched on and what the `finally` reads: handed
        in rather than read off the runtime, so the body never depends
        on which reply is current, and the utterance it answers comes
        with it.

        `utterance.transcript` is a transcription that already exists: a
        confirmed barge-in ran ASR to decide the cancel, and reusing its
        full result (language fields included) is what keeps ASR at one
        run and `heard` at one event per interruption. What that run
        cost travels with it, so the interrupting turn's `heard` reports
        a real latency rather than none."""
        assert self._providers is not None
        providers = self._providers
        pcm = utterance.pcm
        result = utterance.transcript
        asr_ms = utterance.asr_ms
        # The ear that produced the transcription this turn is
        # answering: the one carried over where a confirmed barge-in
        # already ran it, and this turn's own where the arm below does.
        # Never read at the emit, which is after every await a handover
        # could have landed in.
        asr_provider = utterance.asr_provider
        spoken: list[str] = []
        self._output.reply_started()
        heard_s = round(len(pcm) / 2 / PIPELINE_SAMPLE_RATE, 2)
        self._turn = self._fresh_turn(reply.utterance)
        # Whether this turn owes the user a spoken failure notice.
        # Recorded in the arm below and said outside it, which is the
        # whole of why the body is nested: inside the arm the
        # provider's exception is the active one, so a cancellation
        # arriving while the notice is going out would leave carrying
        # that exception as its `__context__`, message and causes and
        # all, straight past the line that took care to write down a
        # class name and nothing else (#384).
        unanswered = False
        try:
            try:
                if result is None:
                    # On the session's clock, which is the loop's: the
                    # record's one duration measured outside an event is
                    # read through the same thing that stamps the offsets it
                    # sits beside.
                    started = self._events.now()
                    try:
                        async with self._watch.watching("asr", providers.asr):
                            result = await providers.asr.transcribe(
                                pcm, PIPELINE_SAMPLE_RATE, language_hint=self._asr_language
                            )
                    except asyncio.CancelledError:
                        # The reply was cut short with the transcription
                        # still running, which is what a mid-ASR merge
                        # does by construction: the utterance is being
                        # reconstituted in front of the continuation and
                        # this call's answer is no longer wanted.
                        #
                        # Said here rather than left to the arm below,
                        # and said as its own event rather than as a
                        # provider failure. `watching` catches
                        # `Exception` and a cancellation is not one, so
                        # nothing else on this path ever reports the ASR
                        # stage at all, and a turn whose only records
                        # were `turn_started` and `reply_finished` is
                        # exactly the shape the pair exists to make
                        # impossible. Nothing failed, so nothing says a
                        # provider did.
                        self._events.emit(
                            lambda: TranscriptionAbandoned(
                                agent=Identifier(self._agent),
                                conversation=ConversationId(self._conversation),
                                duration_s=Real(heard_s),
                                asr_ms=Whole(
                                    round((self._events.now() - started) * 1000)
                                ),
                            )
                        )
                        raise
                    asr_ms = round((self._events.now() - started) * 1000)
                    asr_provider = providers.asr
                    # Only where this turn ran one. A reply handed a
                    # transcription reuses a confirmed barge-in's, measured
                    # at a different call site as part of a different
                    # decision, and a null here says "not measured this
                    # turn" rather than reporting somebody else's wait.
                    # The event beside it is less strict on purpose: what
                    # `heard.asr_ms` answers is what the transcription
                    # this turn is answering cost, whoever ran it.
                    self._turn.asr_ms = asr_ms
                # ASR is done, so the mid-ASR marker comes down: from here a
                # barge-in has nothing of the user's left to destroy.
                self._turntaking.clear_pending()
                # What the ear says it was SENT, which is what a vendor
                # bills on and is not how long the user spoke: a clip
                # under an endpoint's floor never left this process and
                # a clip an echo retry heard twice cost twice. It rides
                # the result rather than being measured here, because
                # the only thing that knows how many requests a call
                # made is the call. An engine that does not count leaves
                # it None and the record says nothing rather than none.
                submitted = result.submitted_ms
                if result.lock_language is not None:
                    self._asr_language = result.lock_language
                transcript = result.text.strip()
                if transcript:
                    # Only engines that detected carry these; a mock or a
                    # pinned language adds no noise to the record. Absent
                    # rather than null, which are different answers: an
                    # engine that detected nothing leaves no key rather than
                    # a key holding nothing.
                    confidence = (
                        None
                        if result.language_confidence is None
                        else round(result.language_confidence, 2)
                    )
                    # What was heard, never the words: the utterance is
                    # content and the conversation store is where content
                    # lives (#120, the content-and-telemetry ADR). What the
                    # event keeps is what an operator measures with, which
                    # is how long the user spoke and what language the
                    # engine heard it in; the sentence renders exactly that,
                    # so the two halves of this record say the same thing.
                    heard_at = self._events.emit(
                        lambda: assembly.heard(
                            self._agent,
                            self._conversation,
                            asr_provider,
                            heard_s,
                            asr_ms,
                            result.language,
                            confidence,
                            submitted,
                        )
                    )
                    # The emission's own reading rather than a second one
                    # taken beside it: the store measures both offsets from
                    # the same origin, so two readings a microsecond apart
                    # put the turn and its `heard` in different milliseconds
                    # whenever they straddle a boundary.
                    self._turn.heard_utterance(
                        heard_at,
                        transcript,
                        heard_s,
                        result.language,
                        confidence,
                    )
                    # And only now the device, which is a socket and can
                    # meet a peer that has gone away. The order used to
                    # be the other way round, so a transcription that
                    # succeeded and a disconnect a millisecond later
                    # ended the turn `device_gone` with nothing saying
                    # the ASR stage had answered at all. What the ear
                    # answered is a fact about this turn and does not
                    # depend on the device still being there to be shown
                    # it; showing it is the reply's first act, not part
                    # of hearing.
                    await self._output.show_transcript(transcript)
                else:
                    # The third ASR outcome, and until #66 the only one
                    # that was a log line rather than an event: an
                    # utterance the engine answered, with nothing in the
                    # answer. No text field on it at all, which the type
                    # is what guarantees; a transcription that FAILED is
                    # `provider_failed` and never this.
                    reply.latch(ReplyOutcome.NOTHING_HEARD)
                    self._events.emit(
                        lambda: NothingHeard(
                            agent=Identifier(self._agent),
                            conversation=ConversationId(self._conversation),
                            duration_s=Real(heard_s),
                            asr_ms=ABSENT if asr_ms is None else Whole(asr_ms),
                            submitted_ms=(
                                ABSENT if submitted is None else Whole(submitted)
                            ),
                        )
                    )
                if transcript:
                    self._turns.append(Turn("user", transcript))
                    self._filler.arm()
                    await self._speak_reply(transcript, spoken)
            except DeviceGone:
                # The device went away mid-reply. Only this type: the edge
                # translates both of the transport's disconnect shapes into
                # it, so a bare `RuntimeError` arriving here is a bug in
                # this process (#137) and belongs on the record below rather
                # than being read as a disconnect and returned on in
                # silence.
                #
                # Latched, because this arm RETURNS: an unlatched exit
                # means the reply finished, and a device that vanished
                # mid-sentence did not.
                reply.latch(ReplyOutcome.DEVICE_GONE)
                return
            except asyncio.CancelledError:
                # A barge-in or an abort is cancelling this reply, and the
                # filler is reply audio: it dies with the reply rather than
                # being waited out. The settle below still awaits the
                # cancellation through.
                self._filler.abandon()
                raise
            except Exception as exc:
                # The class name, and nothing else. No `exc_info`, and no
                # `str(exc)`: since the catch above narrowed, this arm
                # catches every provider failure too, and what a failure
                # from the wire carries is untrusted. `providers/kit.py`
                # sanitizes the taxonomy's own message, but a traceback
                # rendered here would print the whole chain behind it, and
                # an exception raised anywhere near a response body can
                # embed one in its message. The logs the observability ADR
                # makes the retained surface are not the place to find that
                # out. What stays diagnosable: `provider_failed` names the
                # stage, the provider and the host for anything that failed
                # on the wire, and this line names the class for the rest.
                # Where a reply's failure is already classified, so this
                # is where the outcome is written down: the arm that
                # catches it is the arm that knows the exception's kind,
                # and nothing downstream has to read a message to guess.
                reply.latch(ReplyOutcome.FAILED)
                logger.error(
                    "session %s: reply failed: %s", self.session_id, type(exc).__name__
                )
                # And the user is owed a notice, which they were not
                # before (#384): a terminally failed reply used to be
                # silence, and from the couch a broken pipeline was
                # indistinguishable from a slow one. Recorded after the
                # log, so the reason an operator reads is written down
                # first, and said below rather than here.
                unanswered = True
            # Said here rather than in the arm, for the reason above,
            # and with nothing active: the arm has finished, so a
            # cancellation landing in the notice leaves with an empty
            # chain behind it.
            #
            # Only the general arm gets here. `DeviceGone` above has
            # nobody to tell and returns, and a cancellation means the
            # user is talking, so speaking into either would be worse
            # than the silence it replaces.
            #
            # After the filler settles, so a clip still sounding is
            # not talked over and the shared encoder is not
            # interleaved. That wait re-raises a cancellation of this
            # reply rather than swallowing it, so a barge-in confirmed
            # while it runs takes the turn instead of the notice.
            #
            # `speak_fallback` raises nothing but `CancelledError` by
            # contract, and the `finally` below is outside this block,
            # so the closing `tts stop` goes out either way, which in
            # auto mode is what re-arms the device's listening.
            if unanswered:
                await self._filler.settle()
                await self._filler.speak_fallback(FallbackReason.REPLY_FAILED)
        finally:
            # The FIRST statement, ahead of every await below it, and
            # that placement is the whole of what makes this
            # unconditional. `emit` is synchronous, so a cancellation
            # delivered into this `finally` lands in one of the awaits
            # after it and this record is already made; the settle below
            # is an await, and a `reply_finished` behind it would be the
            # one a barge-in could skip.
            #
            # The outcome comes off the latch rather than off whatever
            # exception is in flight: a `CancelledError` cannot tell a
            # barge-in from a shutdown, and every canceller has already
            # said which it is. Nothing latched means nothing ended this
            # reply, which is what `completed` is.
            outcome = reply.outcome or ReplyOutcome.COMPLETED
            self._events.emit(
                lambda: ReplyFinished(
                    agent=Identifier(self._agent),
                    conversation=ConversationId(self._conversation),
                    outcome=outcome,
                    sentences_spoken=Count(len(spoken)),
                )
            )
            # Before the closing tts stop: an unfired timer is stood
            # down, and a clip already sounding finishes rather than
            # being cut mid-word by the stop.
            try:
                await self._filler.settle()
            except BaseException:
                # This is the only await between the reply-finished
                # event and the turn record. A cancellation delivered
                # here must still close the transcript collaborator's
                # utterance, including the no-row case that releases
                # its held root.
                self._record_turn(spoken, final=True)
                raise
            self._turntaking.clear_pending()
            # After the filler settles, because a clip still sounding is
            # more of this reply's audio, and before the awaits below,
            # because none of them puts a frame on the wire. Every frame
            # this reply will ever send has gone by here, so this is
            # where the endpointer stops carrying the assistant's own
            # playback into the answer the user is about to give (#456).
            #
            # The server's last frame rather than the room's: the device
            # trails by about 760 ms, but the measurements on the #70
            # capture show the trailing echo of one reply does not
            # re-poison a freshly cleared detector the way ten seconds of
            # it does, so there is nothing here worth waiting out.
            #
            # Contained, for the reason the two lines below it are:
            # everything after this point is the device's closing `tts
            # stop`, which in auto mode is what re-arms its listening,
            # and a detector that would not forget a reply must not be
            # able to cost a session its next turn. The failure would be
            # a stranger's, too: `forget_audio` reaches the VAD
            # library's own reset.
            forgetting: BaseException | None = None
            try:
                self._turntaking.forget_reply_audio()
            except Exception as exc:  # noqa: BLE001 - never costs the closing stop
                # Bound to an ordinary local before the suite ends, the
                # rule `conversations/store.py: _prune` states: `except
                # ... as` unbinds its own name at the end of its block.
                forgetting = exc
            # Said out here rather than in the arm, the discipline
            # `_gate_barge_in` follows: inside the arm that exception is
            # the active one, so a logging call that itself failed would
            # escape with the library's message and the chain behind it
            # attached as `__context__`, past the line that took care to
            # write down a class name and nothing else (#183).
            if forgetting is not None:
                logger.warning(
                    "session %s: the endpointer would not forget the reply: %s",
                    self.session_id,
                    type(forgetting).__name__,
                )
            # The other end the idle timeout counts from. In the finally,
            # so a reply that failed or was cancelled still resets the
            # clock: the user is owed the full silence before being hung
            # up on either way.
            if spoken:
                said = " ".join(spoken)
                self._turns.append(Turn("assistant", said))
                # What the reply was, not what it said (#120). The count
                # is the sentences whose audio actually went out, so a
                # reply cut short by a barge-in reports what the user
                # heard rather than what was generated, and it is the
                # one size on this event that is measured rather than
                # inferred.
                self._events.emit(
                    lambda: Replied(
                        agent=Identifier(self._agent),
                        conversation=ConversationId(self._conversation),
                        sentences=Count(len(spoken)),
                    )
                )
            # Beside `replied` and for the same reason: this is where a
            # reply ends however it ended, so a cancelled or a failed one
            # records what its finally sees rather than nothing at all.
            # What is recorded here is the LAST record of the reply: one
            # that moved to another conversation closed the record it
            # began with at that boundary, and what this line hands over
            # is the one the seeded round opened on the other side.
            self._record_turn(spoken, final=True)
            # Broad on purpose, and narrow in what it covers: the one
            # statement inside is a device send, so the `RuntimeError`
            # half can only be the transport's, and this closing pair
            # is not worth a report whichever way it fails.
            with contextlib.suppress(DeviceGone, RuntimeError):
                # A reply that never spoke still sends the pair. The
                # device leaves its speaking state on `tts stop`, and in
                # auto mode that is what re-arms its listening, so a
                # `stop` it was never told to expect is the one way this
                # could strand a device.
                await self._output.finish_speaking()

    def _record_turn(self, spoken: Sequence[str], *, final: bool = False) -> None:
        """Hand the finished turn to the content channel.

        Called at each end of a turn, which is the end of the reply and,
        for a reply that moved, the boundary it moved at. A deployment
        that asked for no store leaves here at the first line, so both
        call sites can say what they mean rather than guarding first.

        Under the same guard an event tap gets, and for the same reason:
        a consumer nobody has met yet must not be able to cost the device
        the closing `tts stop` that follows this line, which in auto mode
        is what re-arms its listening. The class name and nothing else,
        because a recorder may be holding whatever a far side answered
        it with."""
        if self._recorder is None:
            return
        record = self._turn.record(self._agent, spoken)
        if record is None:
            if final and self._transcripts is not None and self._turn.utterance is not None:
                self._transcripts.turn_missing(self.session_id, self._turn.utterance)
            return
        try:
            # The handle is kept and never waited on here: what it is
            # for is a resume that must not read past its own writes,
            # and the never-block contract is why this line reads it and
            # walks away. A recorder that answers nothing (every store
            # double, and any future consumer) leaves nothing to keep.
            landed = self._recorder.record_turn(record)
            if landed is not None:
                self.conversations.acknowledge(record.conversation, landed)
            if self._transcripts is not None:
                self._transcripts.turn_recorded(
                    self.session_id, record, landed, final=final
                )
        except Exception as exc:  # noqa: BLE001 - a consumer never breaks a reply
            if self._transcripts is not None:
                self._transcripts.turn_recorded(
                    self.session_id, record, None, final=final
                )
            logger.warning(
                "session %s: the turn recorder failed and was skipped: %s",
                self.session_id,
                type(exc).__name__,
            )

    async def _speak_reply(self, transcript: str, spoken: list[str]) -> None:
        """One reply, which may be spoken by more than one agent and may
        end on a different conversation than it began on.

        `spoken` collects sentences as their audio goes out, so an abort
        or a barge-in leaves the history holding exactly the part of the
        reply the user heard, sentence by sentence.

        A move ends the current loop, whichever of the three it is: what
        was said so far becomes an assistant turn on the thread it was
        said on, the leg is closed there, the record of the turn that
        asked is finished and handed over there, the rebinding happens
        here at that boundary, and a fresh loop runs on the other side
        of it against a record of its own. So no turn is ever split
        across two conversations, in the history or in the store: what
        the user said and what was answered before the move belong to
        the thread they happened on, and the seeded round that follows
        is the first turn of the thread it landed on.

        At most one move per reply, whichever kind, which is what the
        latch counts: two agents cannot ping-pong, and a model cannot
        resume its way through a user's history inside one answer.

        The pass begins here, and so does the value that holds what it
        counts: the rounds, and the two reply-wide facts the empty-reply
        check reads. Those two are kept rather than derived from
        `spoken` because `spoken` is cleared at every leg: a reply where
        an earlier agent spoke and the final leg was wholly withheld
        would read as empty from it, and the user would be told the
        reply said nothing when they had just heard most of it."""
        switches_left = 1
        self._pass = SpeakingPass()
        while True:
            transition = await self._tool_loop(spoken, switches_left)
            if transition is None:
                self._pass.spoke = self._pass.spoke or bool(spoken)
                await self._nothing_sayable()
                return
            if transition.recap is not None:
                # Before the leg closes and before anything moves: the
                # recap is spoken on the thread this reply began on, by
                # this runtime and not by another model round, and it
                # becomes part of the turn being recorded like any other
                # words the user heard. Anything that goes wrong here
                # raises out of this reply, which is the guarantee: a
                # barge-in, a synthesis failure and a disconnect all
                # leave the move unmade and the checkpoint unwritten,
                # and the next resume simply offers the choice again.
                await self._speak_text(transition.recap.text, spoken)
                await self._store_recap(transition.recap)
            said = " ".join(spoken) if spoken else None
            if said is not None:
                self._turns.append(Turn("assistant", said))
                # This leg's share of the reply, in the same terms
                # `replied` reports the whole of it: which agent, and how
                # many sentences of it the user heard. Never the words,
                # which are the store's (#120).
                self._events.emit(
                    lambda: AgentSaid(
                        agent=Identifier(self._agent),
                        conversation=ConversationId(self._conversation),
                        sentences=Count(len(spoken)),
                    )
                )
                # Before the clear, which is the whole reason the fact
                # is kept here at all.
                self._pass.spoke = True
                spoken.clear()
            # Closed whether or not this agent spoke: a leg that only
            # asked for the move still spent tokens, and the leg is the
            # only place they can be attributed to the agent that spent
            # them. A move to another thread closes one too, although
            # the agent has not changed: what a leg is for is the share
            # of a reply that belongs to one context.
            self._turn.leg_ended(self._agent, said)
            # The record ends where the conversation does. Everything
            # this turn heard, spoke, called and spent belongs to the
            # thread it began on, and the round after the move belongs
            # to the thread it lands on; one record held across the
            # boundary would file the second on the first, leaving the
            # thread that was left holding a reply it never heard and
            # the thread that was joined holding none of its own.
            self._record_turn(spoken)
            self._move_to(transition)
            switches_left -= 1
            # Every offer this session is holding goes with the move,
            # whichever kind it was. An id offered inside the
            # conversation that just ended is exactly the stale
            # selection the enforcement exists to refuse.
            if self._resumption is not None:
                self._resumption.forget()
            self._turns.append(Turn("user", transition.seed))
            # The other side's first turn, opened here and handed over
            # by the reply's own `finally`, so a move that is then cut
            # short by a barge-in still records what the user heard of
            # it on the thread it was said on.
            self._turn = self._seeded_turn()

    async def _nothing_sayable(self) -> None:
        """The reply is over. If it spoke nothing and withheld
        something, say the agent's fixed phrase instead of handing the
        user the silence #384 exists to end.

        Both halves of the condition matter. A reply that spoke nothing
        and withheld nothing is an empty answer from the model, which
        this has never had anything to say about; a reply that withheld
        a sentence and spoke the rest is the issue's own constraint,
        that one bad sentence does not discard a good answer.

        Here, at the end of the reply, rather than by raising from the
        loop. The failure arm's log line means a reply that broke, and a
        reply whose model wrote its calls into its speech did not break:
        it is a fact about the model this deployment configured, and the
        record the runner emits says exactly that.

        Reached with nothing active, which the failure arm has to nest a
        block to arrange and this gets for free: it is a statement in
        the ordinary flow of a reply, so a cancellation landing in the
        notice leaves with an empty chain behind it rather than carrying
        whatever was being handled.

        The settle is the failure arm's, for its two reasons and one
        more of this site's own. A clip still sounding must not be
        talked over and the shared encoder must not be interleaved; and
        a reply that spoke nothing never sent a batch, so the tail wait
        inside `_send_reply_audio` was never reached and this is the
        first thing in the turn that would have waited for the mask at
        all. The wait re-raises a cancellation of this reply rather than
        swallowing it, so a barge-in confirmed while it runs takes the
        turn instead of the notice; the `finally` in `_reply` settles
        again, idempotently, and still owns the closing `tts stop`.
        """
        if self._pass.spoke or not self._pass.withheld:
            return
        await self._filler.settle()
        await self._filler.speak_fallback(FallbackReason.NOTHING_SAYABLE)

    def _move_to(self, transition: _Transition) -> None:
        """Apply one transition at the boundary the loop ended on, and
        say on the record which one it was.

        The two arms are the two things a move can rebind. A handover
        changes the agent, and the agent's own thread comes with it,
        minted at its first activation and continued at every later one.
        The other two change which thread the agent is on, which is one
        line of state and one history: nothing about the agent, its
        providers or its prompt moves, because it is the same agent
        answering.
        """
        previous = self._agent
        # Held before the rebinding replaces it, so the event can say
        # which thread was left as well as which one was joined.
        leaving = self._conversation
        if transition.agent is not None:
            target = transition.agent
            self._activate_agent(target)
            # Read by a thunk the emitter calls before this method
            # returns, the way the watch's retry line is.
            self._events.emit(
                lambda: Handover(
                    from_agent=Identifier(previous),
                    to_agent=Identifier(target),
                    from_conversation=ConversationId(leaving),
                    to_conversation=ConversationId(self._conversation),
                )
            )
            return
        assert transition.conversation is not None
        # One call either way, which rebinds the agent's thread, installs
        # the thread's history and moves the active pair with no await
        # between them. A resume is the move that found something and
        # brings the thread's own history; a fresh conversation found
        # nothing and brings none.
        found = transition.resumed
        if found is None:
            self.conversations.start_new(transition.conversation)
        else:
            self.conversations.reactivate(transition.conversation, transition.history)
        if found is not None:
            self._events.emit(
                lambda: ConversationResumed(
                    conversation=ConversationId(found.conversation),
                    turns=Count(found.rendered),
                    skipped=Count(found.skipped),
                    over_budget=Flag(found.over_budget),
                )
            )

    async def _tool_loop(
        self, spoken: list[str], switches_left: int
    ) -> "_Transition | None":
        """Stream, run whatever tools the model asked for, and stream
        again, up to the round cap. Returns the move that ended it, or
        None when the reply is finished.

        The tool snapshot and the resampler are taken here rather than
        per round, because they belong to the agent speaking; the next
        agent gets its own. The history it works from is the active
        thread's, which after a move is the thread the move landed on,
        seed and all.

        The memory policy is resolved on the same line as the snapshot,
        and that is the whole of what makes it one clock. It decides two
        things on two clocks otherwise: which tools this reply offers,
        taken once here, and which blocks each round's prompt carries,
        assembled per round below. A reload landing between them would
        hand one reply the tools of one policy and the prompt of the
        other, which is a reply nobody configured."""
        assert self._providers is not None
        providers = self._providers
        self._remembering = self._resolved_memory()
        assert self._agent is not None
        # The tools, their declared shapes and where each came from, as
        # one value taken once: the shapes are what the coercion reads
        # and the origins are what a withheld sentence is named from, so
        # all three have to be this leg's offer (`Offer` says why).
        offer = self._tools.offer(self._agent)
        working = list(self._turns)
        resampler = Resampler(providers.tts.sample_rate, self._output.output_sample_rate)
        self._output.restart_pacing()

        switch_to: _Transition | None = None
        for round_index in range(MAX_TOOL_ROUNDS):
            choice: ToolChoice = "none" if round_index == MAX_TOOL_ROUNDS - 1 else "auto"
            splitter = SentenceSplitter()
            leg: list[str] = []
            calls: list[ToolCall] = []
            # Where each of those calls is on the turn's record, filled
            # in the moment the calls are known and read after the block
            # below has ended one way or another.
            slots: list[int] = []
            # The sentence currently being spoken, which runs alongside
            # the model still streaming. At most one sentence is ever
            # run ahead of it: every sentence plays for longer than the
            # next takes to start, so one closes the gap, and more would
            # only mean more concurrent requests to the provider and
            # more audio held for a reply a barge-in may throw away.
            speaking: asyncio.Task[None] | None = None
            loop = asyncio.get_running_loop()
            began = loop.time()
            first_token_at: float | None = None
            usage: Usage | None = None
            self._pass.round += 1
            invocation = uuid.uuid4().hex
            # Resolved before the request is built, and per round rather
            # than per reply, because that is the memory block's clock.
            system = await self._system_prompt()
            if self._llm_input is not None:
                # Staged HERE, where the round is assembled, and
                # deliberately not inside the partial below. The
                # first-token watchdog calls that partial a second time
                # over arguments fixed before the first attempt, so a
                # retry sends byte-identical content: staging there
                # would put the same bytes on the trace twice and claim
                # the model was given two things. What a reader wants
                # about a retry is already on the trace as `llm_retry`.
                self._llm_input.stage_reply(
                    self.session_id,
                    invocation=invocation,
                    agent=self._agent,
                    system=system,
                    turns=working,
                    tools=offer.tools,
                    choice=choice,
                )
            try:
                async for event in self._watch.reply_stream(
                    providers.llm,
                    functools.partial(providers.llm.stream, system, working, offer.tools, choice),
                    invocation=invocation,
                    round_=self._pass.round,
                ):
                    if self._llm_input is not None:
                        self._llm_input.observe(invocation, event)
                    match event:
                        case TextDelta(text=text):
                            # Speech only, and speech that is not just
                            # whitespace. Both providers assemble tool
                            # calls and usage after their stream has
                            # ended, so timing from those would report a
                            # whole generation as its own time to first
                            # token, and a round that only calls a tool
                            # has no first token to time.
                            if first_token_at is None and text.strip():
                                first_token_at = loop.time()
                            for sentence in splitter.push(text):
                                if self._withheld(sentence, offer):
                                    continue
                                speaking = await self._speak_after(
                                    speaking, sentence, providers.tts, resampler, leg, spoken
                                )
                        case Usage():
                            usage = event
                        case ToolCall():
                            calls.append(event)
                # The earliest point the model's calls exist: both
                # adapters assemble them after their stream has ended.
                # Reserved here rather than at the dispatch because
                # everything between the two can end the reply (the last
                # sentence's synthesis failing, a barge-in cancelling
                # mid-execution), and a call the model issued belongs on
                # the record whether or not it ever ran.
                slots = self._tools.reserve(self._turn, calls)
                self._watch.reply_round_done(
                    self._turn,
                    self._pass.round,
                    providers.llm,
                    working,
                    began,
                    first_token_at,
                    usage,
                    invocation=invocation,
                )
                tail = splitter.flush()
                if tail is not None and not self._withheld(tail, offer):
                    speaking = await self._speak_after(
                        speaking, tail, providers.tts, resampler, leg, spoken
                    )
                # The round ends here, so the lookahead stops here too:
                # there is no next sentence to overlap with, and the
                # tools below must not run over the top of speech.
                if speaking is not None:
                    await speaking
                    speaking = None
            finally:
                # A barge-in cancels this coroutine anywhere above, and
                # the sentence being spoken must not outlive the reply it
                # belonged to. `_speak` takes its own synthesis down with
                # it, so cancelling the task is enough.
                if speaking is not None:
                    speaking.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await speaking
            if not calls:
                break
            # Whatever preamble was spoken before the calls is part of
            # the assistant turn that asked for them.
            working.append(Turn("assistant", " ".join(leg), tool_calls=tuple(calls)))
            # Here and nowhere else: the reservation has filed the
            # originals and the line above has put them in the history
            # this reply is written against, and `_run_tools` has not yet
            # branched into the move tools, which never reach a dispatch.
            # So this is the one point every execution path shares, and
            # the one point where the record's values and the far side's
            # can part company.
            executing = [
                self._tools.for_execution(self._turn, call, slot, offer)
                for call, slot in zip(calls, slots, strict=True)
            ]
            results, switch_to = await self._run_tools(executing, slots, switches_left)
            if switch_to is not None:
                break
            working.append(Turn("tool", "", tool_results=tuple(results)))

        # Drain the resampler's interpolation tail and the encoder's
        # partial frame, which flushing pads with silence.
        batch = self._output.encode_audio(resampler.flush()) + self._output.flush_encoder()
        await self._send_reply_audio(batch)
        return switch_to

    async def _run_tools(
        self, calls: Sequence[ToolCall], slots: Sequence[int], switches_left: int
    ) -> tuple[list[ToolResult], "_Transition | None"]:
        """Execute one round of calls. Everything that is not a move is
        `ToolExecution.run`'s, which says in what order it runs them;
        the moves are resolved here instead, because a successful one
        ends the loop rather than producing a result the model reads.

        `slots` says where on the turn's record each of these calls was
        already reserved, index for index with `calls`, which is why
        both halves are split out of one enumeration rather than
        rebuilt: a move the model asked for third keeps the third call's
        place, whatever order this method runs things in.

        The moves are resolved in the order the model issued them, and
        that IS the precedence when it asks for more than one: the first
        wins and the rest are refused, whether they were the same kind
        of move or not. A rule about which kind outranks which would be
        a rule nobody could predict from the outside."""
        plain = [
            (slots[index], call)
            for index, call in enumerate(calls)
            if not self._moves(call)
        ]
        moves = [
            (slots[index], call) for index, call in enumerate(calls) if self._moves(call)
        ]
        results = await self._tools.run(self._turn, plain)

        transition: _Transition | None = None
        for order, (slot, call) in enumerate(moves):
            moving, refusal = await self._move(
                call, switches_left, order, transition is not None
            )
            if refusal is not None:
                results.append(refusal)
                # No duration: nothing ran, and the refusal is what the
                # turn's record shows in place of it.
                self._turn.executed(slot, refusal.content, refusal.is_error, None)
                continue
            transition = moving
            # A successful move answers the model nothing, so the
            # reservation is already the whole of its record: no result
            # and no duration. It stays on the record all the same,
            # because the move is otherwise only implied by the legs it
            # produced.
        return results, transition

    def _moves(self, call: ToolCall) -> bool:
        """Whether this call is one the loop resolves itself.

        Two of the three are decided by name alone. The third is
        `resume_conversation`, which is one tool doing two things: a
        call that names a conversation is a move and is this method's,
        and a call that describes one is a read that changes nothing and
        goes to the source that owns it like any other tool. A call that
        names neither is not a move either, so it reaches the dispatch
        and is answered by the sentence that asks for one of the two.
        """
        if call.name in (names.SWITCH_AGENT, names.NEW_CONVERSATION):
            return True
        if call.name != names.RESUME_CONVERSATION:
            return False
        chosen = call.arguments.get("conversation")
        return isinstance(chosen, str) and bool(chosen.strip())

    async def _move(
        self, call: ToolCall, switches_left: int, order: int, moved: bool
    ) -> tuple["_Transition | None", ToolResult | None]:
        """One move, as either the transition it is or the refusal it
        gets. Exactly one of the two comes back.

        The two vocabularies stay apart deliberately. A refused handover
        is an error result, which is what it has always been: the model
        asked for something about the agents this device is bound to and
        got it wrong. A refused selection is not an error, because the
        answer is a sentence a user is owed out loud (#190, decision
        11): a server that cannot resume anything, a conversation that
        is gone, an id nobody offered.

        So do the two things they are told about a round that already
        asked for something. A handover is refused for being the second
        one the loop resolved, which is the merged rule and stays; a
        selection is refused for arriving after a move that was actually
        made, because "this reply has already moved" has to be true when
        it is said.
        """
        if call.name == names.SWITCH_AGENT:
            refusal = self._refuse_handover(call, switches_left, order)
            if refusal is not None:
                return None, refusal
            return _Transition(SWITCH_GREETING, agent=str(call.arguments["agent"])), None
        answer = await self._select(call, switches_left, moved)
        if isinstance(answer, str):
            return None, ToolResult(call.id, answer, is_error=False)
        return answer, None

    async def _select(
        self, call: ToolCall, switches_left: int, moved: bool
    ) -> "_Transition | str":
        """Which thread this reply moves to, or the sentence saying why
        it does not.

        The latch is the one a handover shares, and the same one it has
        always been: the first move of a reply wins, whichever kind it
        was, and `moved` is that fact from earlier in this round.

        A resume has three shapes and they are three arms below, in the
        order the flow reaches them: pick a thread up, which offers a
        choice where the thread is too long to hand over whole; answer
        that choice with the recent part; or answer it with a recap.
        The last two are honoured only against the question this agent
        actually asked, which is what stops a model consenting on the
        user's behalf to a recap nobody was offered.
        """
        if switches_left <= 0 or moved:
            return builtin.ALREADY_MOVED
        if self._resumption is None:
            return builtin.RESUMPTION_UNAVAILABLE
        if call.name == names.NEW_CONVERSATION:
            # Minted here, by the same `mint` an agent's first thread of
            # a device session is minted by: the boundary is decided at
            # this seam, and the id has to exist before the first turn
            # it stamps, which is recorded before the move applies.
            return _Transition(FRESH_GREETING, conversation=mint())
        assert self._agent is not None
        agent = self._agent
        chosen = str(call.arguments["conversation"]).strip()
        # Before the read and not after it: a thread the agent was not
        # offered is refused without the store being asked about it, so
        # an id a model invented cannot even be a query.
        if not self._resumption.offers(agent, chosen):
            return builtin.NO_SUCH_CANDIDATE
        answer = call.arguments.get("start_from")
        flow = self._resumption
        if answer is None:
            return await self._picked_up(flow, agent, chosen)
        if not flow.awaits(agent, chosen):
            return builtin.NO_CHOICE_OFFERED
        if answer == builtin.RECENT:
            return await self._picked_up(flow, agent, chosen, offering=False)
        if answer != builtin.RECAP:
            return builtin.UNKNOWN_START
        return await self._recapped(flow, agent, chosen)

    async def _picked_up(
        self,
        flow: "resumption.Resumption",
        agent: str,
        conversation: str,
        offering: bool = True,
    ) -> "_Transition | str":
        """A thread resumed as it stands, or the choice offered about
        one that will not fit.

        `offering` is false for the half of that choice that answers
        "the recent part", which is the same resume with the question
        already asked and answered: the tail is installed and the seed
        says it is a tail.
        """
        await self.conversations.settled(conversation)
        found = await flow.resumed(agent, conversation)
        if isinstance(found, str):
            return found
        if offering and found.over_budget:
            # Nothing is swapped and nothing is stored: the thread is
            # longer than the budget, so the user is asked which of the
            # two ways they want it, and the answer arrives as a
            # `start_from` on the next utterance.
            flow.offer_choice(agent, conversation)
            return builtin.TOO_LONG_TO_RESUME_WHOLE
        return _Transition(
            self._resumed_seed(found),
            conversation=found.conversation,
            history=found.turns,
            resumed=found,
        )

    async def _recapped(
        self, flow: "resumption.Resumption", agent: str, conversation: str
    ) -> "_Transition | str":
        """The consented recap: read the thread, summarize it once, and
        carry the answer to the boundary where it will be spoken.

        Everything after the consent is this runtime's, which is what
        makes what the user hears and what the store keeps the same
        bytes: the summarizer's text is not handed back to another
        model round to rephrase, it is carried on the transition and
        fed to synthesis exactly as it arrived.

        A summarization that fails or times out is not a failed resume.
        The thread is picked up from its recent tail instead and the
        seeded round is told the recap could not be made, which is a
        fixed sentence like every other caveat; nothing is stored, so
        the next resume offers the choice again.
        """
        await self.conversations.settled(conversation)
        made = await flow.recap(agent, conversation)
        if isinstance(made, str):
            return made
        text = await self._summarized(made)
        if text is None:
            fallback = await flow.resumed(agent, conversation)
            if isinstance(fallback, str):
                return fallback
            return _Transition(
                self._resumed_seed(fallback) + RECAP_UNAVAILABLE,
                conversation=fallback.conversation,
                history=fallback.turns,
                resumed=fallback,
            )
        found = flow.after_recap(made, text)
        return _Transition(
            self._recapped_seed(found),
            conversation=found.conversation,
            history=found.turns,
            resumed=found,
            recap=_Recapped(text=text, made_from=made),
        )

    async def _summarized(self, made: "resumption.Recap") -> str | None:
        """One round against the active agent's own provider, or None
        where it could not be had.

        The agent's own provider rather than a summarizer of its own, so
        a recap adds no outbound surface a deployment did not already
        configure, and a fixed instruction with the thread as its turns,
        so nothing a room said decides what is asked. Bounded by its own
        timeout, because the user is waiting through silence for it.

        Every failure is one answer, which is None: a provider that
        refused, a stream that broke and a round that ran long all mean
        the same thing to the caller, which is that there is no recap to
        speak. A cancellation is not one of them and passes through,
        because a barge-in ends the reply rather than the recap.
        """
        assert self._providers is not None
        providers = self._providers
        said: list[str] = []
        turns = [*made.input, Turn("user", RECAP_REQUEST)]
        invocation = uuid.uuid4().hex
        loop = asyncio.get_running_loop()
        began = loop.time()
        first_token_at: float | None = None
        usage: Usage | None = None
        if self._llm_input is not None:
            # The second call shape, staged for the same reason the
            # reply's rounds are: this is a thing a model was given, and
            # a reader asking what it saw wants the summarization as
            # much as the answer. Before the call rather than after it,
            # so a recap that failed or timed out is still on the trace
            # as something the model was handed.
            self._llm_input.stage_recap(
                self.session_id,
                invocation=invocation,
                agent=self._agent,
                system=RECAP_INSTRUCTION,
                turns=turns,
                tools=[],
                choice="none",
            )
        try:
            async with asyncio.timeout(RECAP_ROUND_TIMEOUT_S) as deadline:
                async for event in self._watch.watched(
                    providers.llm,
                    providers.llm.stream(RECAP_INSTRUCTION, turns, (), "none"),
                    invocation=invocation,
                    purpose=LlmPurpose.RECAP,
                ):
                    if self._llm_input is not None:
                        self._llm_input.observe(invocation, event)
                    if isinstance(event, TextDelta):
                        if first_token_at is None and event.text.strip():
                            first_token_at = loop.time()
                        said.append(event.text)
                    elif isinstance(event, Usage):
                        usage = event
        except TimeoutError as exc:
            if deadline.expired():
                self._watch.failed(
                    "llm",
                    providers.llm,
                    exc,
                    loop.time() - began,
                    invocation=invocation,
                    purpose=LlmPurpose.RECAP,
                )
            logger.warning(
                "session %s: the recap could not be made: %s",
                self.session_id,
                type(exc).__name__,
            )
            return None
        except Exception as exc:  # noqa: BLE001 - a failed recap is a fallback
            # The class name and nothing else, the rule the reply path
            # applies to every provider failure: a message from the wire
            # is a stranger's words.
            logger.warning(
                "session %s: the recap could not be made: %s",
                self.session_id,
                type(exc).__name__,
            )
            return None
        self._watch.recap_round_done(
            providers.llm,
            turns,
            began,
            first_token_at,
            usage,
            invocation=invocation,
        )
        text = "".join(said).strip()
        return text or None

    async def _speak_text(self, text: str, spoken: list[str]) -> None:
        """Say something this runtime wrote, through the path a reply's
        own sentences go out on.

        One synthesis for the whole of it rather than a sentence split,
        and that is what makes the recap's promise keepable: what is fed
        to the provider is the summarizer's text byte for byte, so the
        text stored afterwards is the text that was spoken. A splitter
        normalizes whitespace, and a stored recap that differed from the
        heard one by a newline would be a promise kept only loosely.

        It returns when the audio has been paced out to the device,
        which is what "the user heard it" means on this side of the
        edge. A barge-in cancels here, a dead socket raises here, and a
        provider that failed raises here, which is why the caller can
        treat returning as the fact it stores on.
        """
        assert self._providers is not None
        providers = self._providers
        resampler = Resampler(providers.tts.sample_rate, self._output.output_sample_rate)
        speaking: asyncio.Task[None] | None = None
        try:
            speaking = await self._speak_after(
                None, text, providers.tts, resampler, [], spoken
            )
            await speaking
            speaking = None
        finally:
            # The same rule the tool loop keeps: a sentence being spoken
            # must not outlive the reply it belonged to.
            if speaking is not None:
                speaking.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await speaking
        batch = self._output.encode_audio(resampler.flush()) + self._output.flush_encoder()
        await self._send_reply_audio(batch)

    async def _store_recap(self, made: "_Recapped") -> None:
        """Record the checkpoint, now that the user has heard it.

        Called after playback and nowhere else, which is the ordering
        the whole flow rests on: before it, nothing is stored, so a
        barge-in, a synthesis failure, a disconnect or a crash leaves
        the thread exactly as it was and the next resume offers the
        choice again. After it, a write that is late is still a write of
        something that was heard.

        The wait is bounded and its only consumer is the event: a
        checkpoint that lands after this line is stored all the same,
        and this session simply does not say so. A store that refused
        stores nothing durable, which is the same answer the next resume
        reads, so the choice is offered again.

        A store that refuses because the thread moved under the recap is
        one case of exactly that, and the reason the provenance travels
        on the record: a session erasure committing while this paragraph
        was being spoken took the turns it summarized, and the store
        declines to write a checkpoint standing for words that are gone.
        The user heard the recap, which nothing here can unspeak; what
        does not happen is any of it being kept.
        """
        if self._recorder is None:
            return
        record = MilestoneRecord(
            conversation=made.made_from.conversation,
            covered=made.made_from.covered,
            parent=made.made_from.parent,
            text=made.text,
        )
        try:
            landed = self._recorder.record_milestone(record)
        except Exception as exc:  # noqa: BLE001 - a consumer never breaks a reply
            logger.warning(
                "session %s: the turn recorder failed and was skipped: %s",
                self.session_id,
                type(exc).__name__,
            )
            return
        if landed is None:
            return
        if await asyncio.to_thread(landed.wait, MILESTONE_ACKNOWLEDGEMENT_S):
            self._events.emit(
                lambda: MilestoneRecorded(
                    conversation=ConversationId(record.conversation)
                )
            )

    def _resumed_seed(self, found: "resumption.Resumed") -> str:
        """What the round on the other side of a resume is told.

        The base sentence, plus whichever of the two caveats are true.
        The tail caveat is said where the user chose the recent part, or
        where a recap was wanted and could not be made: either way the
        agent is told it is holding a tail rather than a conversation.
        """
        return "".join(
            [
                RESUMED_GREETING,
                RESUMED_FROM_RECENT if found.over_budget else "",
                RESUMED_WITH_GAPS if found.skipped or found.incomplete else "",
            ]
        )

    def _recapped_seed(self, found: "resumption.Resumed") -> str:
        """What the round after a consented recap is told.

        Its own base sentence, because the situation is its own: the
        recap has already been spoken in this agent's voice, and the one
        thing the round must not do is say it twice. No tail caveat: the
        checkpoint is what stands for everything the context does not
        hold, which is the whole point of having made one.
        """
        return RECAPPED_GREETING + (
            RESUMED_WITH_GAPS if found.skipped or found.incomplete else ""
        )

    def _refuse_handover(
        self, call: ToolCall, switches_left: int, order: int
    ) -> ToolResult | None:
        """Why this switch_agent cannot happen, as an error result the
        current agent phrases in its own voice and language, or None
        when it can.

        `order` is which switch_agent of this round it is, not its place
        in the model's call list: what a second one is refused for is
        being the second the loop resolves."""
        if switches_left <= 0 or order > 0:
            return ToolResult(
                call.id,
                "this conversation has already been handed over once in this reply; "
                "answer as yourself instead",
                is_error=True,
            )
        target = call.arguments.get("agent")
        if not isinstance(target, str) or not target.strip():
            return ToolResult(
                call.id,
                'switch_agent needs an "agent" argument naming one of the available '
                f"assistants: {', '.join(self._agents)}",
                is_error=True,
            )
        if target not in self._agents:
            return ToolResult(call.id, str(_not_allowed(target, self._agents)), is_error=True)
        # Handing over to the agent already speaking is a pure cost: the
        # leg ends, the same agent is re-activated, and a second round
        # runs only to greet a user who is already mid-conversation.
        if target == self._agent:
            return ToolResult(
                call.id,
                "you are already speaking as this assistant; answer as yourself instead",
                is_error=True,
            )
        return None

    async def _system_prompt(self) -> str:
        """The prompt this round is sent: the half cached at activation,
        plus everything memory holds for it and everything the device
        record says, both as they stand right now.

        The half is not rebuilt here. What this adds is the scope blocks,
        which keep the clock the memory block has always had: read on
        every round, so a fact remembered in one session is known to a
        concurrent one on its next reply and a note written in one round
        is read in the next, which is a contract that predates this
        split.

        One read for all three scopes rather than three, which is what
        keeps the cost of this line where it was: it is a database round
        trip and runs in a worker thread rather than on the loop every
        live conversation shares, exactly as the file read before it did.
        It takes no advisory lock, so it never waits on a `remember` in
        flight. It is resolved before the request is built, which is what
        lets the assembler stay a pure function of the text it is handed.

        An agent whose memory section is off is read nothing of memory,
        and that read does not happen: there is no block to assemble
        from it, and a round trip whose answer is thrown away is a cost
        every round of every reply would pay for nothing. The answer is
        this reply's rather than the world's, so the blocks and the
        offered tools cannot disagree inside one reply.

        The device record is not on that switch. What a device is
        called is not a remembered thing, and an agent that may not
        remember anything still has to know what it is speaking
        through, so the record is read whether or not memory is. It is
        read here rather than at the activation for the reason the
        scopes are: a device relocated between two replies has moved for
        the second of them, and the activation may be an hour of
        conversation behind.

        The two reads used to be started together, and are not any more,
        because one of them is now the other's address. A device's facts
        are filed under a MAC, a board swap moves the record and its
        facts to another one in one transaction (#449, M4), and a memory
        read addressed by the MAC this session dialled would answer with
        an empty device scope for the rest of the conversation. So the
        record is read first and its address is what the scopes are read
        under. What that costs is one round trip inside the turnaround a
        person is listening to, on a primary key, against the same
        database; what it buys is that a conversation does not lose what
        the room told it because somebody changed the hardware.

        The fallback is the session's own address, which is where a
        board with no record has always filed its facts and where a
        runtime with no view files all of them.
        """
        assert self._know_how is not None and self._agent is not None
        assert self._conversation is not None
        record = await self._device_record()
        if not self._remembering_now():
            return prompt.with_scopes(self._know_how, NOTHING_REMEMBERED, record).text
        scopes = await asyncio.to_thread(
            self._memory.read_for_prompt,
            self._agent,
            self._device if record is None else record.mac,
            self._conversation,
        )
        return prompt.with_scopes(self._know_how, scopes, record).text

    async def _device_record(self) -> LiveDevice | None:
        """What this conversation is speaking through, as the record it
        attached to stands right now.

        Asked about that record rather than about the MAC this session
        is on, which is the difference between "what is my device
        called" and "what is the device at this address called". The two
        answers part company the moment an operator deletes a device and
        binds the same board again, and #449's M4 parts them on purpose
        by moving a MAC to another record.

        None wherever there is nothing to ask or nobody to ask: a
        runtime composed without the view, a board that had no record at
        its connect, and a record that has since been deleted. Off the
        event loop, because the view reads a database and every live
        conversation in this process shares that loop.
        """
        if self._devices is None or self._attached is None:
            return None
        return await self._devices.resolve_record(self._attached)

    def _withheld(self, sentence: str, offer: Offer) -> bool:
        """Whether this sentence is a leaked tool call, in which case it
        has already been reported and nothing else happens to it, and
        remember for this reply that one was.

        Both of the loop's sentence sites come through here, so neither
        can drop a sentence without the reply knowing. The question is
        the leg's, asked of the offer this leg was made; the answer is
        the reply's, which is why the flag is set here and not by the
        module that answers: it outlives the leg the offer belongs to.
        """
        if not self._tools.withheld(sentence, offer):
            return False
        self._pass.withheld = True
        return True

    async def _speak_after(
        self,
        speaking: asyncio.Task[None] | None,
        sentence: str,
        tts: TtsProvider,
        resampler: Resampler,
        leg: list[str],
        spoken: list[str],
    ) -> asyncio.Task[None]:
        """The lookahead, with this session's failure reporting, its
        first-audio measurement, and its way of actually speaking a
        synthesis bound in.

        The measurement is bound to the synthesis's place in the reply
        rather than to the moment it answers: only the first request
        waited against silence, and a later one that happened to answer
        first spent its wait against playback already happening."""
        index = self._turn.synthesis_started()
        return await speak_after(
            speaking,
            sentence,
            tts,
            lambda exc, elapsed: self._watch.failed("tts", tts, exc, elapsed),
            lambda elapsed_ms: self._turn.first_audio(index, elapsed_ms),
            lambda first_chunk_ms, stream_ms: self._sentence_synthesized(
                index, len(sentence), tts, first_chunk_ms, stream_ms
            ),
            lambda synthesis: self._speak_and_record(synthesis, resampler, leg, spoken),
        )

    def _sentence_synthesized(
        self,
        index: int,
        characters: int,
        tts: TtsProvider,
        first_chunk_ms: int | None,
        stream_ms: int,
    ) -> None:
        """One `sentence_synthesized` event, for a stream that has just
        ended.

        Both numbers as the producer measured them, and the record says
        what each one is: the first is the voice's own latency to its
        first audio, and the second is how long the whole stream lived,
        which for a paced consumer includes the playback it was feeding.
        Anything that averaged the two, or called the second synthesis
        time, would be reporting the speaker's clock as the provider's.

        The voice is the one the caller synthesized through, which is
        also the one it reports a failure against, so both halves of the
        TTS stage name the same entry.

        `characters` is the size of the sentence this stream spoke,
        measured by the caller that holds it: a voice is billed on the
        text it is given, and the length is the one thing about that
        text a record here may carry. The measurement crosses as a
        number, so the sentence itself stops at this method's caller.
        """
        self._events.emit(
            lambda: assembly.sentence_synthesized(
                self._agent,
                self._conversation,
                tts,
                index,
                characters,
                first_chunk_ms,
                stream_ms,
            )
        )

    async def _speak(
        self, synthesis: _Synthesis, resampler: Resampler, spoken: list[str]
    ) -> None:
        """Say one sentence, and count it as said only once its audio has
        gone out.

        The order is the point. Frames are paced, so sending a sentence
        takes about as long as hearing it, and a barge-in cancels this
        coroutine somewhere in the middle of that. Counted first, a
        sentence the user heard two frames of would go into the turn the
        round hands the model as its own preamble. A sentence synthesized
        ahead and never spoken is counted nowhere at all, which is the
        same rule seen from the other end.

        The audio arrives from `synthesis`, which may already have some
        or all of it buffered. Resampling and encoding stay here, in
        order, because the resampler and the encoder are stateful and
        belong to the stream rather than to a sentence.

        `sentence_start` goes out now rather than when synthesis began:
        it tells the device what is being said, and what is being said is
        what is about to be heard.

        This is also where the device is told speech is starting, which
        leaves one window open: a TTS provider slow to its first byte
        holds the device in its speaking state for that wait, and for a
        host that drops traffic that is the synthesis `timeout_s`.
        Closing it means holding `sentence_start` back until the first
        chunk, which reverses a decision #37 made deliberately (the
        announcement belongs to the sentence about to be spoken, and
        whether its audio will arrive is not known then), and changes
        the order of messages the firmware sees. Worth deciding on the
        board rather than here."""
        await self._output.begin_speaking()
        await self._output.sentence_started(synthesis.sentence)
        try:
            async for chunk in synthesis.chunks():
                await self._send_reply_audio(
                    self._output.encode_audio(resampler.process(chunk))
                )
        finally:
            # A barge-in cancels this coroutine mid-sentence, and the
            # synthesis behind it is a separate task that would otherwise
            # keep pulling from the provider for a sentence nobody will
            # hear. After a sentence finishes normally this is a task
            # that is already done, so cancelling costs nothing.
            synthesis.cancel()
            await synthesis.wait_cancelled()
        spoken.append(synthesis.sentence)

    async def _speak_and_record(
        self, synthesis: _Synthesis, resampler: Resampler, leg: list[str], spoken: list[str]
    ) -> None:
        """Say a sentence and count it in both places at once: the
        round's own list, which becomes the turn the model is shown, and
        the reply's, which becomes the history.

        One call rather than two lists merged at the end of the round,
        because a barge-in cancels mid-round: merging later loses every
        sentence of that round, including the ones the user sat through
        and answered. Whoever speaks next then has no idea what was
        already said."""
        await self._speak(synthesis, resampler, leg)
        spoken.append(synthesis.sentence)

    def start_reply(self, utterance: Utterance) -> None:
        """Answer this utterance, from now on.

        The reply is made here rather than on the turn-taking side so
        that `_in_flight`, `replying` and `drain` stay one object's
        business: the reply in flight is what the edge's own jobs ask
        about, and a second owner of the field would be a second answer
        to the same question.

        This is also where a turn begins as far as the record is
        concerned, and the definition is deliberately this call rather
        than a list of the ways into it: the ordinary endpointed
        utterance, a manual stop, a confirmed barge-in and the mid-ASR
        merge all arrive here, and a candidate the gate turned away
        never does. Stamped with the instant the user stopped speaking,
        which the utterance carries across the gate, so an interruption
        is timed from the speech rather than from the confirmation that
        took it seriously.
        """
        # Minted here because here is where the turn begins, and nowhere
        # else: a reply this method did not start answers no utterance.
        # It travels on the value, which the body is handed, so the turn
        # it opens is stamped with it; and it outlives a handover on
        # purpose, which is what makes the two rows a moved reply records
        # say they answer one utterance. The value's latch is fresh
        # because the value is.
        reply = ReplyInFlight(uuid.uuid4().hex)
        self._events.emit(
            lambda: TurnStarted(
                agent=Identifier(self._agent),
                conversation=ConversationId(self._conversation),
                utterance=UtteranceId(reply.utterance),
                speech_ms=Whole(utterance.speech_ms),
                barge_in=Flag(utterance.barge_in),
            ),
            at=utterance.ended_at,
        )
        self._in_flight = reply
        reply.start(self._reply(utterance, reply))

    async def cancel_reply(self, outcome: ReplyOutcome) -> None:
        """Cancel a reply in flight and see the cancellation through.
        Waiting matters: a fire-and-forget cancel leaves the task not yet
        done, and an utterance finishing in that window would be dropped.

        `outcome` is what this canceller is: a barge-in, a device that
        gave up, a session closing. It is taken as an argument rather
        than inferred because `CancelledError` cannot tell those apart;
        how it is latched and the cancellation seen through is the
        value's (`ReplyInFlight.cancel`).

        The handle is let go only if it is still the reply this call
        cancelled. A reply started while the cancel was awaited is the
        reply in flight now, and clearing the field after the await
        would drop the one handle anything has on it.
        """
        reply = self._in_flight
        if reply is None:
            return
        await reply.cancel(outcome)
        if self._in_flight is reply:
            self._in_flight = None

    async def confirm_transcript(self, pcm: bytes) -> Confirmation:
        """Transcribe an interruption, so that the gates in front of a
        barge-in can ask what was actually said.

        Injected into the gate ladder whole rather than assembled there,
        which is what lets the provider watch and the session's language
        lock stay on this side: the ladder needs an answer, not the
        machinery that produces one. Failures propagate, and the
        ladder's own catch decides what an unanswerable confirmation
        means.

        The answer names the ear that gave it, because this is the last
        place that knows. `_providers` is rebound by `_activate_agent`,
        and the reply this confirmation is deciding about can hand the
        conversation over while the call is awaited, so a reply reusing
        the result and reading the binding then would label somebody
        else's transcription. The ear is held before the await for that
        reason, and it crosses as `object`, which is what the assembly
        that turns it into four names takes."""
        assert self._providers is not None
        ears = self._providers.asr
        async with self._watch.watching("asr", ears):
            return Confirmation(
                result=await ears.transcribe(
                    pcm, PIPELINE_SAMPLE_RATE, language_hint=self._asr_language
                ),
                provider=ears,
            )


def bespoke_runtime_factory(
    generations: Generations,
    mcp_servers: McpServers,
    memory: MemoryStore,
    conversations: TurnStore | None = None,
    threads: resumption.ThreadReads | None = None,
    devices: DeviceRecords | None = None,
    device_access: builtin.DeviceAccess | None = None,
    llm_input: "LlmInputExport | None" = None,
    transcripts: "TranscriptExport | None" = None,
) -> RuntimeFactory:
    """The composition root's half of the seam: everything this runtime
    needs that outlives one connection, closed over once at startup.

    The device edge calls what comes back with a device to speak
    through, the session's observability, the agents the device is bound
    to and the world to build all of that from, and never learns what an
    LLM is.

    Neither the engines nor the clips are closed over, and that is the
    one thing here worth reading twice. Both belong to a world rather
    than to a process, so both are read off the generation the edge
    hands in, which is the generation the edge is telling the registry
    this conversation holds (#191). What that decides is where a change
    converges: a conversation goes on speaking through the engines and
    masking with the clips it opened on, and the next session gets what
    the reload built.

    `mcp_servers` is closed over rather than read off the world, and
    that difference is the tool half's own convergence point: the
    registry is one object whose contents an apply replaces, so an
    utterance is answered with the tools that are running rather than
    with the ones that were running when the conversation began.

    `conversations` is closed over, and is the reason the recorder
    reaches a runtime without the `RuntimeFactory` type moving: the
    store outlives every connection, and the per-session channel is
    derived here from the identity the edge already hands over. None
    means no store, which is every deployment that has not asked for one.

    `threads` is the other direction through the same database, and it
    is closed over for the same reason and holds nothing per session:
    reading a stored thread is a connection opened for the read and
    disposed after it. Whether a conversation may actually be resumed is
    not decided here but in the runtime, off the section it already
    holds, so the switch and the keys it reads live in one place.

    The session-close purge is passed only where `conversations` is
    None, and that condition is the whole of the decision. Where threads
    are recorded, a session's close is not a thread's end: the thread can
    be resumed, so its ledger and the undo it is holding outlive the
    connection, and what takes them is the erasure or the retention pass
    that takes the thread. Where nothing is recorded, no thread row ever
    lands, no retention runs and no closed session's thread can ever be
    resumed, so the session's close IS the thread's end and the runtime
    takes its own threads' memory as it tears down. That is what keeps a
    long-running recording-off process bounded without waiting for a
    reboot.

    `devices` is the live view of the device rows, closed over for the
    reason `memory` is: it is one object per server, it outlives every
    connection, and what a reply asks it is about the record the edge
    hands each conversation at its connect. None is a composition with
    no view, which is an embedded caller and a test lane, and its
    replies say nothing about the device.

    `device_access` is the other side of those same rows, closed over
    for the same reason and separate from the read for two: it goes
    through the repository rather than through a read-only connection,
    and what it is handed is the engine this process writes its
    configuration with. Two things reach it, which is why it is not
    called the relocation: a room saying where the device is, and a room
    writing what the device remembers, which has to resolve the record's
    address under the same lock a board swap takes (#449, M4). None is
    the same composition `devices` calls None, and its conversations are
    told they cannot move their device rather than offered no way to say
    so; their device memory is filed under the board they are talking
    to, which is where it has always been.

    That record is the one argument here that is neither closed over nor
    read off the world: it belongs to one connection, and it comes in
    beside the agents because it was resolved with them, in one snapshot
    (#449). Everything the conversation later reads about its device is
    addressed by the identity in it.

    `llm_input` is closed over for the reason `memory` is: it is one
    object per server, it outlives every connection, and what a
    conversation does with it is tell it about each round it is about to
    send. None is a deployment that did not ask for the export, and it
    is the default, which is what makes the flag off cost a reply
    nothing at all rather than a render nobody reads.

    Deliberately one function rather than a config-selectable registry:
    one runtime exists, and a selection mechanism with one option is
    surface without a reader. This is the seam a second runtime plugs
    into."""

    def build(
        output: DeviceOutput,
        events: SessionEvents,
        session_conversations: SessionConversations,
        agents: Sequence[str],
        generation: Generation,
        device: LiveDevice | None = None,
    ) -> SessionInput:
        return PipelineRuntime(
            output,
            generations,
            generation,
            events,
            session_conversations,
            generation.providers.agents,
            mcp_servers,
            memory,
            generation.fillers,
            agents,
            generation.fallbacks,
            None if conversations is None else SessionTurns(conversations, events.session_id),
            threads,
            memory.purge_threads if conversations is None else None,
            devices,
            device_access,
            device,
            llm_input,
            transcripts,
        )

    return build
