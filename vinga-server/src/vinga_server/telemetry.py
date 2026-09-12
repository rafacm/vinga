"""The optional OpenTelemetry exporter, and the whole of the OTel
surface (#66).

Its callers stop having to know that OpenTelemetry exists. The
composition asks `build_telemetry` for one object or for nothing, the
device session asks that object for a tap and attaches it beside
`LiveEvents`, and the lifespan release closes it. The SDK bootstrap, the
owned tracer provider, the clock conversion, the trace lifecycle and the
span map are implementation, and none of it is reachable from anywhere
else.

**It is a tap, not a second vocabulary.** Every span and every span
event is derived from the typed events the pipeline already emits, at
the one seam the events package documents for this issue: "the #66/#67
exporters attach as more, without touching a single emit site". No emit
site moves for this module, and nothing here can say a fact
`catalog.py` does not declare.

**It never blocks a reply.** A tap's `emit` runs on the reply path, so
what happens there is object assembly and nothing else: no lock the
export holds, no syscall, no wait. The SDK's `BatchSpanProcessor` owns
the bounded queue and the background thread, and a full queue drops
spans with a counter, which is the posture this issue chose out loud:
dropped spans are acceptable, a stalled reply is not.

**It owns its tracer provider.** The process-global provider is never
read and never set, so two sequential lifespans in one process each get
a fresh working exporter, and nothing installed here can be observed by
code that did not ask this module for it.

**The dangerous bytes enter below the catalog**, which is what the
no-leak rules here are about. The collector's credentials arrive in
`OTEL_EXPORTER_OTLP_HEADERS`, its address may carry userinfo, and the
SDK's own failure logging embeds the endpoint. So:

- endpoint, headers and timeouts are transport configuration only. This
  module never reads them: the exporter's constructor reads its own
  environment, and no value of theirs becomes a span attribute, a
  resource attribute, an event field or a line of log text;
- the resource is fixed and server-owned, the service name a constant
  and the build revision its version. `Resource.create()` is
  deliberately not used, because it merges `OTEL_RESOURCE_ATTRIBUTES`
  and `OTEL_SERVICE_NAME` into what every span carries, which is
  environment-derived content on the retained surface;
- the SDK's loggers are quieted before the exporter is constructed and
  restored when it shuts down.

The one environment variable this module does read is the protocol, and
it reads it to refuse: the supported transport is OTLP over
HTTP/protobuf exactly, because that is the one exporter the `[otel]`
extra declares. What is refused is named by the supported value rather
than by the rejected one, which is the same rule every refusal in this
repository follows.
"""

import asyncio
import contextlib
import json
import logging
import os
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from vinga_server.boundary import BoundaryRefusal, Reach, check_feature
from vinga_server.build_info import revision
from vinga_server.config import ConfigError
from vinga_server.config.models import TelemetryConfig
from vinga_server.events import Emission, EventTap, session_clock
from vinga_server.events.catalog import carried_values, catalog, kind_of
from vinga_server.events.values import (
    PROVIDER_ENTRY_OPTIONAL,
    PROVIDER_ENTRY_REQUIRED,
    Kind,
    PromptSources,
    ProviderEntries,
)
from vinga_server.quieting import Lease, Quieting

logger = logging.getLogger(__name__)

# Where the switch is written, which is what both refusals below name.
# One spelling, because a sentence an operator is told to edit by has to
# be the path they will find.
TELEMETRY_KEY = "server.telemetry.enabled"

# The extra that carries the packages, and the command that installs it.
# The registry's sentence shape (`providers/registry.py`): the entry,
# the extra, and what to type.
OTEL_EXTRA = "otel"

NEEDS_THE_OTEL_EXTRA = (
    f"{TELEMETRY_KEY} is on, which needs the {OTEL_EXTRA} extra; "
    f"install it with: uv sync --extra {OTEL_EXTRA}"
)

# The environment family the SDK reads its transport out of, as a
# prefix, because what a refusal may name is the family and never a
# member's value.
OTLP_ENV_PREFIX = "OTEL_EXPORTER_OTLP_"

# The transport the extra declares, spelled as the SDK spells it.
OTLP_PROTOCOL_ENV = "OTEL_EXPORTER_OTLP_PROTOCOL"
OTLP_TRACES_PROTOCOL_ENV = "OTEL_EXPORTER_OTLP_TRACES_PROTOCOL"
SUPPORTED_PROTOCOL = "http/protobuf"

# Both variables, and which of them wins, because an operator can only
# act on a sentence that names the one they have to edit. The SDK reads
# the traces-specific variable in front of the general one, so a
# deployment with a bad value in the specific one and a good value in
# the general one is refused by a sentence that named only the general
# one, and following that sentence changes nothing. Value-free, like
# every refusal here: what is quoted is this repository's own words.
UNSUPPORTED_PROTOCOL = (
    f"{TELEMETRY_KEY} is on, and this server exports over {SUPPORTED_PROTOCOL} "
    f"only; set {OTLP_TRACES_PROTOCOL_ENV} to {SUPPORTED_PROTOCOL} or leave it "
    f"unset, and the same for {OTLP_PROTOCOL_ENV}. The traces-specific "
    f"variable is the one that decides where both are set"
)

# And what an exporter that would not build at all is refused with.
#
# The whole `OTEL_EXPORTER_OTLP_*` family is operator-written text this
# module deliberately never reads, and the SDK parses several members of
# it eagerly: a timeout that is not a number and a compression that is
# not one of three words both raise, and each library exception quotes
# what it was handed. A `ValueError` out of a constructor is also
# outside `BOOT_FAILURES`, so it reached an operator as uvicorn's
# traceback rather than as a sentence.
#
# So every failure of that construction is contained and answered with
# this, which names the family and the file to look in and repeats
# nothing: those variables are where the collector's credentials live,
# and a refusal that echoed one would put it in the retained log of the
# deployment it belongs to.
CANNOT_BUILD_EXPORTER = (
    f"{TELEMETRY_KEY} is on, and no exporter could be built from the "
    f"{OTLP_ENV_PREFIX}* environment. Nothing of what those variables hold is "
    f"repeated here, because they carry the collector's credentials: check "
    f"that {OTLP_ENV_PREFIX}TIMEOUT is a number of seconds, that "
    f"{OTLP_ENV_PREFIX}COMPRESSION is one of gzip, deflate or none, and that "
    f"{OTLP_ENV_PREFIX}ENDPOINT is a URL"
)

# The SDK's own namespace, quieted for as long as an exporter exists.
#
# Its records are the one surface below the catalog that carries an
# operator's endpoint: an export that fails logs what it could not
# reach, and a URL with userinfo in it is a credential in a retained
# log. `tools/mcp/transport.py` takes the MCP SDK's namespace off this
# server's handlers for the same reason and by the same mechanism; the
# difference is that this one is put back, because it is switched on by
# a configuration key rather than by importing a module.
OTEL_NAMESPACE = "opentelemetry"

# What the batch processor is given, written out rather than left to the
# SDK's defaults, because the bound on the queue is the whole reason a
# slow collector cannot reach a reply. A full queue drops.
QUEUE_SIZE = 2048
BATCH_SIZE = 512
SCHEDULE_DELAY_MS = 5000
EXPORT_TIMEOUT_MS = 30000

# How long the lifespan waits for the exporter to finish on the way out.
# Bounded because a collector that has stopped answering must not hold a
# redeploy open; what is lost when it expires is spans, which is the
# same trade the queue makes.
SHUTDOWN_TIMEOUT_S = 5.0

# The fixed service name. Not `OTEL_SERVICE_NAME`, deliberately: what
# this process is, is this repository's word.
SERVICE = "vinga-server"

# --- the span map -----------------------------------------------------
#
# Fourteen event names have a shape of their own and everything else folds
# onto whichever span is open. That default is the design rather than a
# shortcut: an exporter that enumerated the events it knew would drop
# every variant the catalog grew after it was written, in silence, and
# the catalog grows. A name appears below only because a SPAN has to be
# constructed for it, never because the event is interesting.

SESSION_OPEN = "session_open"
SESSION_CLOSED = "session_closed"
TURN_STARTED = "turn_started"
REPLY_FINISHED = "reply_finished"
CAPTURE_STARTED = "capture_started"

# And the four that arrive after it closed: a recording's trip to the
# backend happens on a worker of its own, off the session's loop and
# after the span map has let the session go (#67), and a transcript
# export reads the store on a worker of its own for the same reason
# (#495). Both pairs reach the trace through one mechanism, which is
# what "the machinery generalizes and the sentences do not" means here.
CAPTURE_UPLOADED = "capture_uploaded"
CAPTURE_UPLOAD_FAILED = "capture_upload_failed"
TRANSCRIPTS_EXPORTED = "transcripts_exported"
TRANSCRIPT_EXPORT_FAILED = "transcript_export_failed"
AFTER_THE_CLOSE = frozenset(
    {
        CAPTURE_UPLOADED,
        CAPTURE_UPLOAD_FAILED,
        TRANSCRIPTS_EXPORTED,
        TRANSCRIPT_EXPORT_FAILED,
    }
)

# Not a lifecycle event, and the only span event that changes what the
# spans after it carry: it moves which agent a turn is stamped from.
HANDOVER = "handover"

# The four ways an utterance's ASR stage ends, which is the closed set
# the catalog declared in M1 and its PR round: it answered, it answered
# nothing, the engine failed, or the answer stopped being wanted. Each
# ends one ASR span, and the one that is a failure is the only one whose
# span says so.
HEARD = "heard"
NOTHING_HEARD = "nothing_heard"
PROVIDER_FAILED = "provider_failed"
TRANSCRIPTION_ABANDONED = "transcription_abandoned"

# The stage a `provider_failed` has to name to be an ASR outcome. Every
# other stage's failure folds as an ordinary span event onto the turn,
# which is where a failed generation or a failed voice belongs: the LLM
# and TTS spans are built from the events that SUCCEEDED, and a span
# built from a failure would claim an interval nobody measured.
ASR_STAGE = "asr"

# And the three stages a stage span can answer for ITSELF, which is why
# the retained context leaves one of them out of what it stamps there.
# The ASR one is above, because a `provider_failed` has to name it to be
# an ASR outcome at all; these two are only ever spoken here.
LLM_STAGE = "llm"
TTS_STAGE = "tts"

LLM_ROUND = "llm_round"
# Not a lifecycle event either, and the second one whose fold changes
# what the spans after it carry: it retains a prompt's provenance for
# the agent it was assembled for.
PROMPT_ASSEMBLED = "prompt_assembled"
# One declared event name with three variants, and one fold for all
# three: the naming policy the variants make structural is carried by
# `source` and by which of the two name fields the payload holds, and
# `_attributes` already skips a table key a payload does not carry.
TOOL_CALL = "tool_call"
SENTENCE_SYNTHESIZED = "sentence_synthesized"
SPEAKING_STARTED = "speaking_started"
SPEAKING_FINISHED = "speaking_finished"

# What a span is called in a backend's list. Deliberately short: the
# service name is beside them, and a backend groups by these.
#
# `tts_stream` rather than `tts` or anything with "synthesis" in it,
# which is the one name here that had to be argued for. The span's
# extent is the synthesis stream's whole lifetime, and a paced consumer
# holds that stream open: the interval INCLUDES playback backpressure,
# so calling it synthesis would be false in exactly the way the catalog
# refused to be false when it named `stream_ms`. The provider's own
# latency, the number that is backpressure-free, is the attribute.
SESSION_SPAN = "session"
# The two spans this module makes that are not a stage of a
# conversation: the reference that makes an uploaded recording playable
# (#67), and one turn's transcript (#495), both put on the trace after
# the session closed.
CAPTURE_SPAN = "capture"
TRANSCRIPT_SPAN = "transcript"
TURN_SPAN = "turn"
# What the model asked a tool for, inside the turn it asked in. Short
# like the rest and deliberately not the tool's own name: a span name
# is what a backend groups a list by, and one per configured tool would
# make that list as long as the deployment's tool table. Which tool it
# was is an attribute.
TOOL_SPAN = "tool"
ASR_SPAN = "asr"
LLM_SPAN = "llm"
TTS_SPAN = "tts_stream"
PLAYBACK_SPAN = "playback"

# The two span events a stage span carries in its middle, named for the
# instant rather than for the field the instant was derived from.
FIRST_TOKEN = "first_token"

# The payload keys the emitter itself contributes, which are the two
# identities every session event carries.
SESSION_FIELD = "session"
DEVICE_FIELD = "device"
EVENT_FIELD = "event"

# The three a span event never repeats: two are on the span it is being
# added to, and the third is its own name.
_IDENTITIES = frozenset({EVENT_FIELD, SESSION_FIELD, DEVICE_FIELD})

# The session id's second spelling, carried by every span beside
# `vinga.session.id` (#67 M1, verified against a live Langfuse 4.35.0).
#
# A backend that groups traces into sessions has to be told which
# attribute holds the session, and it cannot be told in vinga's
# vocabulary: pointed at a Langfuse with the #66 export exactly as
# merged, all twenty observations of a three-turn conversation arrived
# with an empty `sessionId`, so the three turn traces and the session
# trace were four unrelated traces in the UI. The generic
# `session.id` is what that backend reads, and it is the conventions'
# own name rather than a vendor's: the same attribute on a span is
# inert metadata under a backend that does not group, which is why this
# is an unconditional second spelling rather than a Langfuse-shaped
# mode.
#
# `vinga.session.id` stays what it is and stays first. This is the same
# fact under a second name for one reader, not a rename, and the
# walkthrough record in
# `docs/plans/2026-09-12-langfuse-backend-implementation.md` carries the
# API answers that made it necessary.
SESSION_ID_ALIAS = "session.id"

VINGA_SESSION_ID = "vinga.session.id"

# What a session id is spelled as everywhere: the vinga name first,
# because that is the one this repository's own documentation, tests and
# operators read, and the generic alias behind it.
SESSION_ID_NAMES = (VINGA_SESSION_ID, SESSION_ID_ALIAS)

# The three fields the backend renders an observation's own input,
# output and metadata from, and the two things this module writes into
# them whose value is not derived from an event.
#
# Those are real exceptions to this file's own rule (nothing it writes
# may say a fact `catalog.py` does not declare), and they are worth
# being exact about, because they are the whole of the exception list.
#
# The FIRST is a backend-minted media reference (#67). It is not a fact
# about the conversation: it is a token the BACKEND minted for bytes an
# operator already authorized to leave, and its only content is an
# opaque identifier in that backend's own namespace. It is written on
# no session unless `server.telemetry.export_audio` is on, so a
# deployment that exports traces and no audio never sees one. Two
# spellings for one token, because Langfuse resolves a reference
# wherever it finds one and the two render differently: the metadata key
# is what a reader filters and reads, and the output field is what the
# trace view puts a player in. Both were confirmed live to arrive with
# the token intact.
#
# The SECOND is a turn's own text (#495), and it is the one place in
# this module where conversation CONTENT is written onto a span. It is
# lawful for exactly the reason the media token is: it is written on no
# session unless `server.telemetry.export_transcripts` is on, it is read
# from the conversation store rather than from an emission, and the
# emit-to-span fold it does not go through stays content-free. The
# fields are the backend's own rendered input and output, confirmed
# live before the exporter was built around them (#495 M2's gate).
OBSERVATION_METADATA_PREFIX = "langfuse.observation.metadata."
OBSERVATION_INPUT = "langfuse.observation.input"
OBSERVATION_OUTPUT = "langfuse.observation.output"

# What one turn's span carries besides its text.
#
# `vinga.turn.index` is a session-local ordinal, 1-based, counting the
# turns this export actually wrote in `id`-ascending order, so any
# session's first exported turn is index 1 however many turns the
# THREAD holds. `vinga.turn.id` is beside it and is the store's own
# database-wide identity, which is what correlates an observation back
# to the row it came from and to the API's cursor; the two are
# deliberately separate facts rather than one spelled twice.
TURN_INDEX = "vinga.turn.index"
TURN_ID = "vinga.turn.id"
TURN_T_MS = "vinga.turn.t_ms"
TURN_AGENT = "vinga.agent"

# And where a split reply's per-leg attribution goes, under the exact
# wire encoding the plan fixed: ONE string attribute holding canonical
# JSON (sorted keys, no extra whitespace) of the legs in order.
#
# A string because OTel span attributes take primitives or homogeneous
# primitive arrays and never mappings, and because every post-close
# write this module makes is string-valued. The live gate recorded what
# the backend does with it: the string is parsed back into a structured
# `metadata.legs` on the observation, so a reader meets the legs as
# objects rather than as a quoted blob.
TRANSCRIPT_LEGS = f"{OBSERVATION_METADATA_PREFIX}legs"

# What a leg may say, allowlisted rather than copied. The token halves
# the column also holds are metadata the generation spans already
# carry, and content plus its attribution is the whole of what this
# observation adds.
LEG_FIELDS = ("agent", "text")

# Which payload fields become attributes on which span, and under what
# name. Written out rather than derived from the payload, so an event
# that gains a field does not silently gain an attribute: what a span
# carries is a decision, and the events reference is where the field it
# came from is documented.
#
# A value may be a tuple, which exports the one field under each of
# those names. One fact under two spellings is not two facts: the
# session id is the only one, for the grouping reason stated above it.
#
# The prefix is vinga's own. The settled `gen_ai.*` correspondence sits
# on the LLM round span below, where those attributes have a meaning;
# nothing on these two spans is a GenAI fact.
# What an operator calls the board, beside the MAC that identifies it.
#
# On EVERY span, which is an enumeration rather than a table entry: the
# session span reads it here, the turn and the stage spans read it off
# the retained identity below, and the three spans written after the
# close read it off the retained `_Exported` record. A dashboard
# grouped by a household's rooms is what this is for, and a stage span
# that carried only a MAC is a span nobody groups.
#
# The bounded copy `session_open` carries and never a configuration
# read: the value is sanitized at the decision site, and a board
# renamed after a session ran must not change what that session's spans
# say. A board nobody has named contributes NO attribute rather than a
# null one, which is what `_attributes` already does for an absent
# value.
DEVICE_NAME = "vinga.device.name"

SESSION_ATTRIBUTES = {
    SESSION_FIELD: SESSION_ID_NAMES,
    DEVICE_FIELD: "vinga.device.id",
    "device_name": DEVICE_NAME,
    "agent": "vinga.agent",
    "conversation": "vinga.conversation.id",
    "protocol": "vinga.device.protocol",
}

SESSION_CLOSE_ATTRIBUTES = {
    "reason": "vinga.session.close_reason",
    "duration_s": "vinga.session.duration_s",
}

TURN_ATTRIBUTES = {
    SESSION_FIELD: SESSION_ID_NAMES,
    DEVICE_FIELD: "vinga.device.id",
    "agent": "vinga.agent",
    "conversation": "vinga.conversation.id",
    "speech_ms": "vinga.turn.speech_ms",
    "barge_in": "vinga.turn.barge_in",
}

TURN_FINISHED_ATTRIBUTES = {
    "outcome": "vinga.turn.outcome",
    "sentences_spoken": "vinga.turn.sentences_spoken",
}

# The session's own identity, retained at the open and put on every span
# this exporter makes afterwards.
#
# Because OTel does not inherit: a child span carries its parent's id
# and nothing of its parent's attributes, so a backend filtering on a
# device or a session sees only the spans that spell it themselves. The
# issue asks for session-level context on EVERY span, and a stage span
# with only its own stage's fields is a span nobody can find.
#
# Three facts, all fixed for the life of a session, all read off the
# validated `session_open` payload. The agent and the conversation are
# NOT here: they move (a handover changes both) and every stage event
# carries its own, which is the more precise answer and comes through
# the same declared-value gate as the rest of its payload.
#
# The build revision is not here either, and is not missing: it rides
# the resource as `service.version`, which every span this provider
# makes carries by construction. A per-span copy would be the same fact
# twice, and the resource is where a backend looks for it.
CONTEXT_ATTRIBUTES = {
    SESSION_FIELD: SESSION_ID_NAMES,
    DEVICE_FIELD: "vinga.device.id",
    "device_name": DEVICE_NAME,
}

# What a session opened against, as span attributes.
#
# `session_open.providers` is a mapping of agent to stage to the four
# sanitized names off the built provider, and the issue asks for the
# resolved provider entries as session-level context on the spans. It
# arrives as one nested mapping and lands as one flat attribute per
# stage and per fact, because that is what a backend can filter on: a
# JSON blob would be present and unqueryable, which is the same as
# absent for the question this exists to answer.
#
# The applicable agent's entries, not every agent's. A session opens
# talking to one agent and a handover changes which, so the session span
# carries the agent it opened with and each turn span carries the agent
# that turn was spoken by. The entries themselves are retained whole, so
# a handover switches which of them is read rather than needing entries
# the exporter was never given.
PROVIDER_PREFIX = "vinga.provider"

# The four names an entry may carry, which is the whole of what
# `ProviderEntries` admits: nothing off a provider configuration can
# reach a span through here, which is what makes this sanitized by
# construction.
PROVIDER_FACTS = (*PROVIDER_ENTRY_REQUIRED, *PROVIDER_ENTRY_OPTIONAL)

# Where a prompt's provenance lands, and it lands FLATTENED for the
# reason the provider context gives in its own comment: a JSON blob is
# present and unqueryable, which is the same as absent for the question
# the attribute exists to answer. That question is "how much of this
# prompt came from where", which is a number per block a reader charts.
#
# One attribute per block, with the provenance token's `:` separators
# written as `.`, so `instructions:house` becomes
# `vinga.prompt.sources.instructions.house`: an attribute name is a
# dotted path and a token is not. The key space is bounded by the
# operator's own configuration rather than by anything a far side
# sends, which is the five declared provenance forms with configured
# names inside three of them, so the cardinality is bounded by exactly
# what bounds the provider keys.
#
# `characters` goes on beside them as the total the blocks sum to:
# without a denominator the parts answer nothing.
PROMPT_PREFIX = "vinga.prompt.sources"

PROMPT_ATTRIBUTES = {"characters": "vinga.prompt.characters"}


def _provider_context(held: Any) -> dict[str, dict[str, dict[str, str]]]:
    """What a `session_open` payload said this conversation opened
    against, validated, or nothing.

    Through the catalog's own value type rather than by inspection here.
    That is the difference between a claim and a check: `ProviderEntries`
    is what makes these entries sanitized by construction, because it is
    the type that refuses an agent name that is not an identifier, a
    stage outside the pipeline's own set, an entry missing its name or
    type or carrying a fifth key, and a value that is not an identifier.
    A fold that walked the mapping itself would accept
    `{"": {"../../etc": {"name": "<a credential>", "type": "x"}}}`
    and put it on a span under an attribute name of the sender's
    choosing, which is exactly the bounded-cardinality promise this
    context is supposed to keep.

    Nothing where the value does not validate, and nothing said about
    why: a payload this module did not build is a caller's, and the
    events package's own rule for one is that what is never looked at
    cannot leak later. The ordinary path cannot reach this branch at
    all, because the emitter builds payloads from the same type.
    """
    try:
        entries = ProviderEntries(held)
    except Exception:  # noqa: BLE001 - a payload nobody declared says nothing
        return {}
    return entries.carried()


def _provider_attributes(
    providers: dict[str, dict[str, dict[str, str]]], agent: str | None
) -> dict[str, Any]:
    """One agent's resolved providers, flattened into span attributes.

    Empty for a session whose `session_open` carried none and for an
    agent the entries do not describe. What arrives here has already
    been through `ProviderEntries`, so the stage is one of the
    pipeline's own and every value is an identifier; the four facts are
    read by name rather than by iterating the entry, so an entry that
    somehow held a fifth key would still contribute nothing.
    """
    entries = providers.get(agent or "")
    if entries is None:
        return {}
    attributes: dict[str, Any] = {}
    for stage, entry in entries.items():
        for fact in PROVIDER_FACTS:
            held = entry.get(fact)
            if isinstance(held, str):
                attributes[_provider_attribute(stage, fact)] = held
    return attributes


def _provider_attribute(stage: str, fact: str) -> str:
    """The attribute one of a stage's provider facts is spelled under.

    The only place this shape is written. Both readers go through it:
    the retained context above, which says what the session OPENED
    against, and `_entry_name` below, which a stage span's own table
    uses to say what the call that actually ran used. An earlier draft
    had the context build the name itself and `_entry_name` spell it a
    second time, which made the single-source claim false where it
    mattered, since changing one would have left the other emitting the
    old spelling.
    """
    return f"{PROVIDER_PREFIX}.{stage}.{fact}"


def _prompt_attributes(payload: dict[str, Any]) -> dict[str, Any]:
    """One `prompt_assembled` payload as the attributes a turn span
    carries, or nothing at all.

    Through the catalog's own value type rather than by inspection
    here, exactly as `_provider_context` is and for the same reason:
    `PromptSources` is what makes a provenance token safe to write into
    an attribute NAME, because it is the type that refuses a key
    outside the declared grammar and a value that is not a character
    count. A fold that walked the mapping itself would let a payload
    this module did not build choose its own attribute names, which is
    the bounded-cardinality promise broken in the one place it costs
    most.

    The sizes only, never a byte of the prompt: that is a property of
    the event rather than of this fold, and it is what makes the whole
    of this lawful on a metadata surface.
    """
    attributes = _attributes(payload, PROMPT_ATTRIBUTES)
    try:
        sources = PromptSources(payload.get("sources")).carried()
    except Exception:  # noqa: BLE001 - a payload nobody declared says nothing
        return attributes
    for token, characters in sources.items():
        attributes[f"{PROMPT_PREFIX}.{token.replace(':', '.')}"] = characters
    return attributes


def _entry_name(stage: str) -> str:
    """The attribute one stage's configured entry name is spelled under.

    Read from two sources: the retained context says what the session
    OPENED against, and a stage span's own table says what the call that
    ran actually used. One fact keeps one attribute name across both, so
    a backend filtering on it never has to know which it is looking at.
    """
    return _provider_attribute(stage, "name")


def _speaks_for(stage: str, spoken: dict[str, Any]) -> str | None:
    """The stage this span answers for ITSELF, or nothing.

    Which is what decides whether the retained context still speaks for
    that stage on this span, and it is decided by what the event
    actually said rather than by which fold is running. An event that
    named an entry states the whole of its stage, so the open-time
    entries for it are left out and one attribute name keeps one source;
    an event whose quartet is four absences, which is what a provider
    the registry never built produces, states nothing, and suppressing
    the context there would delete what the session opened against
    rather than correct it.

    The name is what is asked for, because it is the fact a stage's
    identity is atomic around: the catalog gives four values or four
    absences, so a span carrying the entry name carries the type, the
    host and the model that belong with it.
    """
    return stage if _entry_name(stage) in spoken else None

# --- what a payload field may become on a span ------------------------
#
# The fold used to copy a payload wholesale, taking every key but the
# three identities. That is a permissive rule in the one place this
# module cannot afford one: what reaches a backend would be whatever a
# payload happened to hold, so a field nothing here approved would be
# exported by default, and the OTel API accepts only scalars and
# sequences, so a field of any other shape was dropped by the SDK
# without a word (`prompt_assembled.sources` and `frames_dropped.reasons`
# are both mappings, and both went missing exactly that way).
#
# So the rule is explicit and it is closed at both ends. Every payload
# field the catalog declares has a KIND, `SHAPES` says what each kind
# becomes on a span, and the fold iterates the APPROVED table rather
# than the payload: a key the catalog does not declare for that event
# cannot be exported, whatever put it there.


class Shape(Enum):
    """What one declared payload field becomes on a span.

    A closed set with a row per `Kind`, checked as such by a test, so a
    kind added to the catalog fails this module rather than silently
    picking a default.
    """

    # A string, number or flag, exported under its own name as it is.
    SCALAR = "scalar"
    # A list of names, exported as a sequence of strings.
    SEQUENCE = "sequence"
    # A mapping, exported as one JSON string under its own name: the
    # OTel attribute types have no mapping, and the alternative to a
    # deterministic string is the SDK dropping the field.
    JSON = "json"
    # Not an attribute, and not discarded either: retained as context
    # this module carries onto the spans it applies to. One field is
    # this today, `session_open.providers`, which becomes the per-stage
    # provider attributes on the session span and on every turn span the
    # agent it describes is talking through.
    CONTEXT = "context"
    # Not an attribute at all.
    DROPPED = "dropped"


SHAPES: dict[Kind, Shape] = {
    Kind.IDENTIFIER: Shape.SCALAR,
    Kind.TOKEN: Shape.SCALAR,
    Kind.CLASS_NAME: Shape.SCALAR,
    Kind.ID: Shape.SCALAR,
    Kind.DESCRIPTOR: Shape.SCALAR,
    Kind.INT: Shape.SCALAR,
    Kind.FLOAT: Shape.SCALAR,
    Kind.BOOL: Shape.SCALAR,
    Kind.COUNT: Shape.SCALAR,
    Kind.IDENTIFIER_LIST: Shape.SEQUENCE,
    Kind.ID_LIST: Shape.SEQUENCE,
    # The two mappings a span event carries, as deterministic JSON.
    # OTel's attribute types are scalars and sequences of scalars, so a
    # mapping handed to `add_event` is discarded by the SDK with a
    # warning this module has already silenced: `prompt_assembled` lost
    # which fragments built the prompt and how long each was, and
    # `frames_dropped` lost the whole of what it says. Both are
    # bounded, server-owned mappings of names to numbers, which is why
    # one string is an honest representation of them rather than a
    # place for prose to hide.
    Kind.SOURCES: Shape.JSON,
    Kind.DROP_COUNTS: Shape.JSON,
    # And the one that is context rather than an attribute: what a
    # session opened against is attached per agent to the spans it
    # applies to rather than dumped onto one of them as a blob.
    Kind.PROVIDER_ENTRIES: Shape.CONTEXT,
}


@dataclass(frozen=True)
class _Rule:
    """What one declared field may become on a span, and what it must BE
    to become it.

    Two halves, because the shape alone was not a gate. `shape` is the
    OTel form the value takes; `admits` is the catalog's own value type
    or types, and a value is exported only if one of them accepts it.
    That second half is the whole of the difference from a check on
    Python builtins: `session_idle.idle_s` is declared `Real`, and a
    payload carrying a credential-shaped STRING there is a `str`, which
    every builtin check passes and `Real` refuses. The same for a
    mapping whose keys are not the server's own drop reasons.

    A field several variants of one event declare can have several
    declared types, and any of them accepting is enough: a payload of
    that event is a payload of one of its variants.
    """

    shape: Shape
    admits: tuple[type, ...]
    nullable: bool

    def accepts(self, held: Any) -> bool:
        """Whether the catalog's own declaration would have built this
        value.

        Asked by CONSTRUCTING it, which is the only honest way: the
        constraint lives in the value type's `__post_init__` and in an
        enumeration's membership, and a copy of either here would be the
        second home the events package exists to refuse. Anything the
        construction raises is a refusal, since a type that will not
        take the value is a type that does not admit it.

        Two accommodations, both about the difference between a value
        and the form it RIDES a payload in, and neither about what the
        type admits:

        - a nullable field's null is the payload saying the fact is not
          known, which is a shape the declaration allows and which
          exports as nothing anyway;
        - a sequence rides as a list and its type takes a tuple, so the
          list is offered as the tuple it is the carried form of. The
          element checks still run, which is the half that matters.
        """
        if held is None:
            return self.nullable
        for declared in self.admits:
            for form in (held, tuple(held)) if isinstance(held, list) else (held,):
                try:
                    declared(form)  # type: ignore[call-arg]
                except Exception:  # noqa: BLE001 - anything raised is a refusal
                    continue
                return True
        return False


def _approved() -> dict[str, dict[str, _Rule]]:
    """Which fields each event may put on a span, what each becomes, and
    what each has to be, read off the catalog's own declarations.

    Derived rather than written out beside the catalog, because a second
    list of a hundred events' fields is the pending bug the design guide
    names. What is written out is the rule (`SHAPES` above), which is
    fourteen rows and closed.

    An event's variants are merged: several variants of one event
    declare overlapping fields, and what a payload of that event may
    carry is the union, both of the shapes and of the types.
    """
    approved: dict[str, dict[str, _Rule]] = {}
    for name, declaration in catalog().items():
        fields: dict[str, _Rule] = {}
        for variant in declaration.variants:
            for declared in carried_values(variant):
                kind = kind_of(declared)
                if kind is None:
                    continue
                held = fields.get(declared.name)
                admits = (*(held.admits if held else ()), declared.type)
                fields[declared.name] = _Rule(
                    shape=SHAPES[kind],
                    admits=admits,
                    # Nullable where ANY variant declares it so: what a
                    # payload of this event may carry is the union of
                    # what its variants may.
                    nullable=declared.nullable or bool(held and held.nullable),
                )
        approved[name] = fields
    return approved


APPROVED = _approved()


def _as_attribute(held: Any, rule: _Rule) -> Any | None:
    """One payload value as the attribute its rule says it is, or
    nothing.

    Nothing rather than a coerced guess wherever the value is not what
    its declaration promised, and the declaration is asked rather than
    guessed at: a payload built by the catalog cannot disagree with it,
    and a payload that DOES disagree is one this module did not build.
    That is the case worth spending a construction on, because the field
    a hostile emitter would choose is a declared one: a string where a
    duration belongs passes every check on Python builtins and exports
    whatever it holds.
    """
    if not rule.accepts(held):
        return None
    shape = rule.shape
    if shape is Shape.SCALAR:
        return held if isinstance(held, str | int | float | bool) else None
    if shape is Shape.SEQUENCE:
        if not isinstance(held, list | tuple):
            return None
        return tuple(one for one in held if isinstance(one, str))
    if shape is Shape.JSON:
        if not isinstance(held, dict):
            return None
        # Sorted and separator-fixed, so the same mapping is the same
        # string in every process and a backend can group by it.
        return json.dumps(held, sort_keys=True, separators=(",", ":"))
    return None


# --- what each stage span carries -------------------------------------
#
# Every one of these tables is read by `_attributes`, which is the same
# declared-shape gate the span events go through: a name here is a
# REQUEST to export a declared field under a vinga name, and a field the
# catalog does not declare for that event contributes nothing however
# this table spells it. So there is one answer in this module to what a
# payload field may become on a span, and the stage spans are inside it
# rather than beside it.

# The ASR span, whose four ends carry four overlapping field sets. One
# table for all of them, because a field a given outcome does not carry
# contributes nothing: `language` is only on `heard`, `error` only on the
# failure, and `duration_s` (how long the user spoke) on three of the
# four.
#
# `error` is the exception's CLASS NAME and the catalog is what makes
# that structural: `ClassName` is built from the exception itself and
# there is no value in that vocabulary a message could be constructed
# as. Nothing else of a provider's failure reaches a span.
#
# The provider quartet is the settled correspondence, spelled exactly as
# the round span below spells it: an ear is a `gen_ai` provider like a
# generator is, so "ASR latency by provider" is the same question with
# the same keys at all three stages. Two of the four ASR outcomes carry
# it (`heard` and a failure at this stage); the two that do not
# contribute nothing here, and the span keeps what the session opened
# against instead.
ASR_ATTRIBUTES = {
    "agent": "vinga.agent",
    "conversation": "vinga.conversation.id",
    "duration_s": "vinga.asr.duration_s",
    "language": "vinga.asr.language",
    "language_confidence": "vinga.asr.language_confidence",
    "error": "vinga.asr.error",
    "type": "gen_ai.provider.name",
    "model": "gen_ai.request.model",
    "host": "server.address",
    "provider": _entry_name(ASR_STAGE),
}

# Which of the four ended, as the event's own name. The set is closed by
# the catalog rather than by a second vocabulary here: these are the
# four variants, spelled the way the events reference spells them.
ASR_OUTCOME = "vinga.asr.outcome"

# How long each outcome says its transcription ran, which is what the
# span's start is measured back from. Two different fields for the same
# question, because the catalog asks it twice: three of the outcomes
# carry `asr_ms`, and a provider failure carries the call's own
# `duration_ms` like every other provider failure does.
ASR_LENGTH = {
    HEARD: "asr_ms",
    NOTHING_HEARD: "asr_ms",
    TRANSCRIPTION_ABANDONED: "asr_ms",
    PROVIDER_FAILED: "duration_ms",
}

# The LLM round span, and the settled correspondence table shipped
# exactly (the conversation-store plan's, adopted by this issue's plan
# review): four GenAI keys, one `server.address`, and `provider`, the
# CONFIGURED ENTRY NAME, which is the one fact in the row that is
# vinga's own word rather than the conventions'. A backend that knows
# nothing about this project reads the five; an operator who has to find
# the entry in a configuration file reads the sixth.
#
# `round` and `turns` are beside them and vinga's, because neither is a
# GenAI fact: a round counts this reply's generations, including the one
# after a handover, and `turns` is the cheap proxy for payload size.
#
# The entry name is spelled the way the retained provider context spells
# it (`vinga.provider.llm.name`) rather than under a name of this
# table's own. One fact, one attribute name, wherever it is read from:
# the session and turn spans carry what the session OPENED against, and
# this carries what the round that answered actually ran on, which is
# the same question asked of a narrower thing. A second spelling would
# have been a second home for the same fact, and a backend filtering on
# it would have had to know which span it was looking at. `llm_round` is
# emitted only for the LLM stage, so the stage segment is a constant
# here rather than a field read.
LLM_ATTRIBUTES = {
    "type": "gen_ai.provider.name",
    "model": "gen_ai.request.model",
    "host": "server.address",
    "input_tokens": "gen_ai.usage.input_tokens",
    "output_tokens": "gen_ai.usage.output_tokens",
    "provider": _entry_name(LLM_STAGE),
    "agent": "vinga.agent",
    "conversation": "vinga.conversation.id",
    "round": "vinga.llm.round",
    "turns": "vinga.llm.turns",
}

# The tool span, which is what a `tool_call` becomes instead of the
# span event it used to be.
#
# `gen_ai.operation.name` is the conventions' own word for what this
# span IS, and it is the one attribute here that no payload field
# produces: the value is a constant this module names, the way the ASR
# outcome is. The conventions have a name for a tool's name too, and a
# builtin's `tool` is exactly that, this server's own word for a tool
# it authors.
#
# `entry` is NOT that name and is deliberately not spelled as it. What
# an MCP call may say is the entry an operator configured, never the
# far side's own tool name, so it lands under vinga's own word for the
# same reason the configured provider entry does on the round span:
# a reader filtering `gen_ai.tool.name` is asking which tool ran, and
# an entry name is the answer to a different question.
#
# `source` is the catalog's own closed set (`ToolSource`), not a second
# vocabulary invented here, and `is_error` is the flag the call
# returned rather than a span status: the call answered, and what it
# answered with is the tool's business rather than this server's
# failure.
GEN_AI_OPERATION = "gen_ai.operation.name"
EXECUTE_TOOL = "execute_tool"

TOOL_ATTRIBUTES = {
    "agent": "vinga.agent",
    "conversation": "vinga.conversation.id",
    "source": "vinga.tool.source",
    "is_error": "vinga.tool.is_error",
    "tool": "gen_ai.tool.name",
    "entry": "vinga.tool.entry",
}

# The per-sentence TTS span. The stream's lifetime is the span's own
# extent and is deliberately not repeated as an attribute; what IS an
# attribute is the number the extent cannot state, the provider's
# latency to its first audio chunk, measured producer-side before
# backpressure can bite.
#
# And the quartet, off the same correspondence the other two stages use:
# what makes a voice comparable across a fleet is the pair of its
# latency and its identity, and a span that carried only the first is
# the "TTS latency by provider" question left unanswerable.
TTS_ATTRIBUTES = {
    "index": "vinga.tts.index",
    "first_chunk_ms": "vinga.tts.first_chunk_ms",
    "agent": "vinga.agent",
    "conversation": "vinga.conversation.id",
    "type": "gen_ai.provider.name",
    "model": "gen_ai.request.model",
    "host": "server.address",
    "provider": _entry_name(TTS_STAGE),
}

# The paced-playback span, bounded by two real deliveries: the first
# frame out and the last frame out. Its count comes from the event that
# closes it.
PLAYBACK_ATTRIBUTES = {
    "frames": "vinga.playback.frames",
    "agent": "vinga.agent",
    "conversation": "vinga.conversation.id",
}

# How many sessions may have a `capture_started` waiting for their
# `session_open`. The capture's event is a server-channel one and beats
# the session's open by a handshake, so it is held and folded when the
# span exists; a session id that never opens would otherwise be a slow
# leak, so the hold is bounded and the oldest entry goes first.
PENDING_CAPTURES = 64

# And how many sessions may have a `prompt_assembled` waiting for their
# `session_open`, which is not an edge case but the ordinary one:
# `PipelineRuntime.__init__` activates the first agent and emits the
# event, and `DeviceSession.run` builds that runtime before the hello
# exchange and well before `session_open`. So the INITIAL agent's
# provenance has always arrived before there was a trace to put it on,
# and used to reach none at all.
#
# A sibling of the hold above rather than a reuse of it. The two are
# cleared by different events and a shared bound would let one starve
# the other: a deployment recording many sessions it never opens would
# evict the prompts of the sessions that did.
PENDING_PROMPTS = 64

# How many sessions' trace ids are kept for a reader to ask about after
# the fact, ON TOP of the deployment's own session capacity, oldest
# evicted first. The same posture as the hold above, for the same
# reason: a map that grew with every session a process ever ran would be
# a slow leak in the one object a server holds for its whole life, and
# what a late reader wants is the session that just closed rather than
# one from last week.
#
# Slack rather than the whole bound since #495, and the difference is a
# correctness one rather than a tuning one. This map is written at a
# session's OPEN, `server.limits.max_sessions` has no upper bound, and a
# fixed sixty-four would therefore evict a LIVE session's context as
# soon as sixty-five sessions were talking at once: a healthy deployment
# would answer `no_trace` for a session that had not even closed. So the
# bound is the configured capacity plus this, computed in
# `build_telemetry` from what the composition was given, which by
# construction means no live session's context is evicted by concurrent
# opens and the after-close window keeps the depth it always had.
#
# It narrows the capture uploader's own exposure incidentally and is
# claimed to do no more: a capture job does not pin a context and
# resolves `trace_of` later on its own worker, so a blocked capture
# worker under `max_sessions > 64` can still find older contexts gone.
# Closing that is the capture uploader's follow-up.
RETAINED_TRACES = 64


def build_telemetry(
    config: TelemetryConfig | None,
    *,
    boundary: Reach | None = None,
    exporter: Any | None = None,
    transcripts: Any | None = None,
    max_sessions: int = 0,
    queue_size: int = QUEUE_SIZE,
    batch_size: int = BATCH_SIZE,
    schedule_delay_ms: int = SCHEDULE_DELAY_MS,
    shutdown_timeout_s: float = SHUTDOWN_TIMEOUT_S,
) -> "Telemetry | None":
    """One server's exporter, or nothing at all.

    Nothing is the default and nothing is what an absent section, or a
    section with the flag off, answers: no import happens, no object is
    built, no thread starts, and no tap is ever attached, so a server
    with telemetry off is byte for byte the server it was.

    The three refusals are this function's, and they run in this order,
    which is the order that makes each of them honest:

    1. **The data boundary.** Asked of `boundary.py` before any
       OpenTelemetry import, any construction and any thread, so under a
       boundary narrower than the internet the exporter's constructor is
       provably never reached. The sentence is the boundary module's,
       value-free, and it arrives here as `BoundaryRefusal`; what leaves
       is `ConfigError`, raised after the handler has closed so nothing
       is chained to it.
    2. **The extra.** The packages are imported HERE rather than at
       module scope (the provider registry's `_resolved` pattern), which
       is what lets this module be imported by a server that has none of
       them. An install without the extra refuses with the sentence that
       names the section, the extra and the command.
    3. **The protocol.** Read before construction and compared against
       the one value the extra can serve.
    4. **The rest of that environment.** The SDK parses several members
       of `OTEL_EXPORTER_OTLP_*` inside its constructor and quotes what
       it was handed when one will not parse, so every failure of the
       construction is contained and answered with one fixed sentence
       naming the family. Without it a mistyped timeout reached the
       operator as a library traceback with the value in it, and as an
       exception type outside `BOOT_FAILURES`.

    `max_sessions` is the deployment's configured session capacity, and
    it is the one argument here that is neither a refusal nor a seam:
    the trace retention has to be at least that deep or a live session's
    context is evicted by the sessions talking beside it (#495). The
    formula is here rather than at the call site because it is this
    module's fact; what the composition knows is its own capacity.

    `exporter`, `transcripts`, `queue_size`, `batch_size`,
    `schedule_delay_ms` and `shutdown_timeout_s` are the test seam and
    nothing else: a lane drives the fold through the SDK's in-memory
    exporter, or fills a deliberately tiny queue behind a blocking one
    to prove a saturated exporter costs a reply nothing, or shortens the
    wait so a case about what happens AFTER the timeout does not take
    five seconds to reach it. `transcripts` is the second of those and
    stands in for the DEDICATED exporter instance a transcript export
    delivers through, which is a different object from `exporter` on
    purpose: one is a batch queue that drops, and the other is a bounded
    call that answers. A caller that passes none of them gets the real
    transport reading its own environment and the real bound.
    """
    if config is None or not config.enabled:
        return None

    refusal = _boundary_refusal(boundary)
    if refusal is not None:
        # Raised here rather than inside the handler that read it, so
        # nothing is chained to it: `app.lifespan` follows the same
        # discipline, and an exception chain from this depth is what
        # carries somebody else's message into an operator's terminal.
        raise ConfigError(refusal)

    sdk = _import_sdk()
    if sdk is None:
        # Outside the handler for the same reason: an ImportError
        # carries its module search path and a traceback through
        # somebody else's package, and this sentence is printed as it is.
        raise ConfigError(NEEDS_THE_OTEL_EXTRA)

    _check_protocol()

    quieted = _QUIETING.take()
    provider = _construct(
        sdk,
        exporter=exporter,
        queue_size=queue_size,
        batch_size=batch_size,
        schedule_delay_ms=schedule_delay_ms,
    )
    if provider is None:
        # Outside the handler that caught it, like the two refusals
        # above, and after the logging this build changed has been put
        # back: what leaves here is one sentence with no chain, and
        # `ConfigError` is inside `BOOT_FAILURES`, which the library's
        # own `ValueError` was not.
        quieted.release()
        raise ConfigError(CANNOT_BUILD_EXPORTER)
    return Telemetry(
        provider=provider,
        quieted=quieted,
        sdk=sdk,
        transcripts=transcripts,
        retained=RETAINED_TRACES + max(0, max_sessions),
        shutdown_timeout_s=shutdown_timeout_s,
    )


def _construct(
    sdk: "_Sdk",
    *,
    exporter: Any | None,
    queue_size: int,
    batch_size: int,
    schedule_delay_ms: int,
) -> Any | None:
    """The tracer provider this exporter owns, or nothing where the
    environment it was built from would not parse.

    Nothing rather than a raise, so the caller's sentence is raised
    outside this function's `except` and chains no library exception.
    Nothing about what was raised leaves here either, its class name
    included: the values these constructors parse are the collector's
    credentials, and `ValueError: could not convert string to float:
    'sk-live-...'` is exactly the shape of message this is containing.

    What got as far as existing is closed on the way out. A provider
    with a batch processor already added owns a thread, so a half-built
    one abandoned to the garbage collector would be a boot that refused
    and left an exporter running.
    """
    provider = None
    try:
        built = exporter if exporter is not None else _otlp_exporter()
        provider = sdk.provider(
            resource=sdk.resource(
                attributes={sdk.name_key: SERVICE, sdk.version_key: revision()}
            )
        )
        provider.add_span_processor(
            sdk.processor(
                built,
                max_queue_size=queue_size,
                max_export_batch_size=batch_size,
                schedule_delay_millis=schedule_delay_ms,
                export_timeout_millis=EXPORT_TIMEOUT_MS,
            )
        )
    except Exception:  # noqa: BLE001 - a refusal never carries a library's words
        # Deliberately unbound, for the reason the events package gives
        # where it does the same: what is never looked at cannot leak by
        # accident later.
        _discard(provider)
        return None
    return provider


def _discard(provider: Any | None) -> None:
    """Let go of a provider a failed build got part way through.

    Under its own guard, because this runs on a path that is already
    handling a failure and a second one here would replace a sentence
    with a traceback.
    """
    if provider is None:
        return
    try:
        provider.shutdown()
    except Exception:  # noqa: BLE001 - the refusal is what matters here
        pass


def _boundary_refusal(boundary: Reach | None) -> str | None:
    """What the data boundary says about an exporter, or nothing.

    Asked before any OpenTelemetry import, any construction and any
    thread, which is what lets the refusal claim the exporter's
    constructor was never reached. The sentence is the boundary module's
    own, and only the sentence crosses back: the exception type belongs
    to whichever surface asked, which here is `ConfigError`.

    The reach is `internet`, fixed and honest: where the collector is
    lives in `OTEL_EXPORTER_OTLP_ENDPOINT`, which this server never
    parses and could not vouch for if it did, and there is no telemetry
    entry for an operator to assert a LAN collector on. The consequence
    is stated rather than hidden: a `network`-bounded server refuses
    tracing even toward a collector on its own network.
    """
    try:
        check_feature(TELEMETRY_KEY, Reach.INTERNET, boundary)
    except BoundaryRefusal as refusal:
        return str(refusal)
    return None


@dataclass(frozen=True)
class _Sdk:
    """The names this module needs out of the SDK, resolved once.

    The registry's `_resolved` pattern: the import happens when an
    exporter is built and not before, so this module imports clean in an
    install that has none of it, and nothing outside this function ever
    sees an OpenTelemetry symbol.

    `result` is the enumeration a bounded export answers with, and it is
    here rather than imported where it is read for the same reason every
    other name is: a module that imports it at the top stops importing
    in an install without the extra.
    """

    provider: Any
    processor: Any
    resource: Any
    result: Any
    name_key: str
    version_key: str


def _import_sdk() -> _Sdk | None:
    """The SDK, or nothing where it is not installed.

    Nothing rather than a raise, so the sentence the caller prints is
    raised outside this function's `except` and chains no ImportError.
    """
    try:
        from opentelemetry.sdk.resources import (
            SERVICE_NAME,
            SERVICE_VERSION,
            Resource,
        )
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            BatchSpanProcessor,
            SpanExportResult,
        )
    except ImportError:
        return None
    return _Sdk(
        provider=TracerProvider,
        processor=BatchSpanProcessor,
        resource=Resource,
        result=SpanExportResult,
        name_key=SERVICE_NAME,
        version_key=SERVICE_VERSION,
    )


def _otlp_exporter() -> Any:
    """The real transport, which reads its own environment.

    Constructed with no arguments on purpose. Every fact it needs (the
    endpoint, the headers, the certificate, the timeout) is one this
    module must not touch, and the way not to touch a value is not to
    read it: what is never bound here cannot become an attribute, a
    field or a sentence by accident later.
    """
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    return OTLPSpanExporter()


def _check_protocol() -> None:
    """Refuse a protocol this distribution cannot serve.

    The traces-specific variable wins over the general one, which is the
    SDK's own precedence, and an unset variable is the supported value:
    an operator who wrote nothing gets what the extra installs.

    The rejected spelling is never quoted. It is an operator-supplied
    string like any other, and a refusal that echoed it would put
    whatever was in that variable into the retained log; naming the
    supported value says everything the operator has to do.
    """
    chosen = os.environ.get(OTLP_TRACES_PROTOCOL_ENV) or os.environ.get(
        OTLP_PROTOCOL_ENV
    )
    if chosen is None or chosen.strip() == SUPPORTED_PROTOCOL:
        return
    raise ConfigError(UNSUPPORTED_PROTOCOL)


_QUIETING = Quieting(OTEL_NAMESPACE)


def quiet_the_sdk() -> Lease:
    """Take a claim on the SDK's silence, and answer the claim to give
    back.

    Public because a second holder needs one, and it must be the SAME
    claim rather than a second `Quieting` over the same namespace: the
    logging configuration is process-wide, and two instances each
    reference-counting their own snapshot of one global is precisely the
    failure `quieting.py` spells out, where one holder's release
    un-silences the library while the other is still working and the
    other's release then silences it for the life of the process.

    The holder this exists for is the transcript exporter's worker
    (#495), which outlives this exporter's bounded shutdown by design: a
    late export failure logs the endpoint it could not reach, and that
    must not arrive through a namespace this exporter has already put
    back.
    """
    return _QUIETING.take()


def _epoch_ns(at: float, offset: float) -> int:
    """One monotonic reading as the epoch nanoseconds a span wants.

    The only conversion in this module, which is what keeps every span
    and every span event in one process on one mapping: two readings of
    the pair would put two spans of the same trace a clock drift apart,
    and the arithmetic between them is exactly what a trace is read for.
    """
    return int((at + offset) * 1_000_000_000)


def _rules(payload: dict[str, Any]) -> dict[str, _Rule]:
    """What this payload's event is allowed to export, by field.

    Empty for an event the catalog does not declare, which is what makes
    the fold below closed: nothing is exported for a payload whose event
    name is not one of the catalog's own.
    """
    name = payload.get(EVENT_FIELD)
    if not isinstance(name, str):
        return {}
    return APPROVED.get(name, {})


def _attributes(
    payload: dict[str, Any], table: dict[str, str | tuple[str, ...]]
) -> dict[str, Any]:
    """The span attributes one payload contributes, under the names the
    table gives them.

    Through the same shape rule the span events go through, so there is
    one answer in this module to "what may a payload field become on a
    span" rather than one per surface. A field the payload does not
    carry, or one whose value is not what its declared kind promised,
    contributes nothing rather than a null: an `Absent` value is left
    out of a payload by the catalog, and an attribute saying `None`
    would be a claim the event did not make.

    A table entry naming several attributes exports the one value under
    each of them, which is what `SESSION_ID_NAMES` is: the same fact
    read by two vocabularies, decided once in the table rather than by
    a second fold here.
    """
    rules = _rules(payload)
    attributes: dict[str, Any] = {}
    for key, names in table.items():
        rule = rules.get(key)
        if rule is None:
            continue
        held = _as_attribute(payload.get(key), rule)
        if held is None:
            continue
        for name in (names,) if isinstance(names, str) else names:
            attributes[name] = held
    return attributes


def _named(exported: "_Exported") -> dict[str, Any]:
    """The board's name for a span written after its session closed, or
    nothing at all.

    One home for it because all three post-close writers need it and
    each builds its attributes by hand: `reference_media`,
    `_after_the_close` and `_transcript_spans` would otherwise be three
    copies of one absence rule, and the rule is exactly the one
    `_attributes` keeps for a live span, that an unnamed board
    contributes no attribute rather than a null.
    """
    return {} if exported.name is None else {DEVICE_NAME: exported.name}


def _before(end: int, ms: Any) -> int:
    """The instant `ms` milliseconds before `end`, or `end` itself where
    the event carried no number.

    Which is the whole of the retrospective construction: a stage is
    never watched while it runs, and a span is assembled at the instant
    it ENDED out of the duration the pipeline already measured. An event
    that measured nothing gets a span with no extent rather than an
    invented one: a point in the trace, saying the stage ended here and
    declining to say when it began.
    """
    if isinstance(ms, bool) or not isinstance(ms, int | float):
        return end
    return end - int(ms * 1_000_000)


def _after(start: int, ms: Any) -> int | None:
    """The instant `ms` milliseconds after `start`, or nothing.

    Nothing where the event carried no number, which is a real answer
    rather than a missing one: a round that only asked for a tool timed
    no spoken token, and a span event at the round's own start would say
    the first token arrived instantly.
    """
    if isinstance(ms, bool) or not isinstance(ms, int | float):
        return None
    return start + int(ms * 1_000_000)


@dataclass
class _SessionTrace:
    """One device session's place in the trace, the spans open inside
    it, and the context they are stamped from.

    `identity` is the session's own two fixed facts, kept because OTel
    inherits nothing: a stage span carries its parent's id and none of
    its parent's attributes, so what a backend filters on has to be on
    every span that wants finding.

    `providers` is what `session_open` said this conversation opened
    against, for every agent the device is bound to, and `agent` is the
    one talking right now, which `handover` moves. Between them they are
    what lets a turn span carry the providers that turn actually ran on
    without the exporter needing a fact no event gave it.

    `prompts` is the same shape of retained fact for a different
    question: what each agent's know-how half was assembled out of, by
    provenance. Retained rather than stamped where it arrives because
    `prompt_assembled` is emitted once per AGENT and not once per turn,
    so an attribute written onto whichever turn was open would describe
    one turn per agent and leave every later one silent.

    `transcribed` is whether the open turn's ASR stage has already
    ended. A turn has exactly one, and the events that end one can
    arrive twice: a barge-in the gate REJECTS emits its own
    `provider_failed` at the ASR stage while the turn being spoken over
    is still the open one, and that failure is the gate's vocabulary
    about a candidate rather than a second transcription of this turn.

    `playback` is the one stage span held here rather than constructed
    whole, because it is the one interval the pipeline does not measure:
    the two deliveries that bound it are two events, and what is kept
    between them is the span they bound. Every other stage span is
    assembled at the instant it ended and never held.
    """

    span: Any
    turn: Any | None = None
    playback: Any | None = None
    transcribed: bool = False
    identity: dict[str, Any] = field(default_factory=dict)
    providers: dict[str, dict[str, dict[str, str]]] = field(default_factory=dict)
    prompts: dict[str, dict[str, Any]] = field(default_factory=dict)
    agent: str | None = None


@dataclass(frozen=True)
class TranscriptTurn:
    """One stored turn on its way onto a trace (#495).

    The seam between the transcript exporter and this module, stated as
    a type rather than implied by a mapping both sides index: what
    crosses is exactly these seven facts, so a projection that grew a
    column cannot reach a span by accident and this module never learns
    that a database is behind it.

    `index` is the exporter's session-local ordinal and `id` is the
    store's own row identity; `legs` is the column as the store holds
    it, allowlisted and encoded HERE, because what a span may carry is
    this module's question.
    """

    index: int
    id: int
    t_ms: int
    agent: str | None
    heard: str | None
    reply: str | None
    legs: Any = None


class Delivery(Enum):
    """What became of one bounded transcript export.

    Three answers, and the caller turns each into a word of its own
    closed set. They are this module's own vocabulary rather than the
    event's, because what this knows is whether a batch of spans
    reached the far side; which reason an operator reads is the
    exporter's to decide.
    """

    # The far side took the batch.
    DELIVERED = auto()
    # It did not, and trying again inside this call already happened:
    # the exporter's own bounded retry is the whole retry policy.
    UNDELIVERED = auto()
    # Nothing was even attempted, because this exporter has stopped
    # accepting or the spans could not be built. Shutdown territory,
    # which is why it is not a delivery answer at all.
    STOPPED = auto()


@dataclass(frozen=True)
class _Exported:
    """Which trace a session's spans went out under, and which span was
    its root.

    The spelled id is what `trace_of` answers and what a backend's API
    takes back. The two numbers are what a LATER span in that same trace
    has to be given, which is the whole reason this is a record rather
    than the string it used to be: a reference written after the session
    closed is a child of the session span, and a child needs its parent's
    identity rather than a rendering of half of it.

    And the board's name as `session_open` carried it, or nothing,
    because the three writers that run after the close build their
    attributes by hand and have no live session to read an identity
    from. Here rather than looked up when one of them writes, for the
    same reason the trace id is here: what a post-close span says is a
    fact about the session that ran, and a board renamed since would
    otherwise rename a conversation that is already over.
    """

    trace: str
    trace_id: int
    span_id: int
    name: str | None = None


class Telemetry:
    """One server's exporter, as the thing its callers hold.

    Built by `build_telemetry` and released by the lifespan. What a
    caller may do with it is ask for a tap, ask which trace a session
    was exported under, and close it; everything else it knows is what
    its callers stop having to.
    """

    def __init__(
        self,
        provider: Any,
        quieted: Lease,
        sdk: "_Sdk",
        transcripts: Any | None = None,
        retained: int = RETAINED_TRACES,
        shutdown_timeout_s: float = SHUTDOWN_TIMEOUT_S,
    ) -> None:
        # The two API names a span needs, bound once here rather than
        # imported per turn: an empty context, which is what makes a
        # span the root of a trace of its own, and the link that puts
        # such a root beside the session it belongs to.
        from opentelemetry.context import Context
        from opentelemetry.trace import (
            Link,
            NonRecordingSpan,
            SpanContext,
            Status,
            StatusCode,
            TraceFlags,
            format_trace_id,
            set_span_in_context,
        )

        self._root = Context
        self._link = Link
        # How a trace id is written for anything outside this process,
        # taken from the SDK rather than spelled here: the thirty-two
        # lowercase hex characters an OTLP request carries are the same
        # characters a backend's API takes back, and two spellings of
        # one identifier is the drift `trace_of` exists to avoid.
        self._spelled = format_trace_id
        # What makes a stage span a CHILD of the turn it happened in,
        # where the turn is itself the root of a trace of its own. A
        # stage span is not linked the way a turn is: an ASR call is
        # part of its turn, where a turn is only part of its session.
        self._within = set_span_in_context
        # And what makes a span written AFTER a session closed part of
        # that session's trace: a parent that is not a span this process
        # still holds, only its identity. The SDK has no other way to
        # continue a trace whose spans have all ended.
        # NOT `self._context`, which is a method of this class: an
        # attribute of that name shadows it, and what it builds is every
        # stage span's parentage, so the fold silently stopped making
        # them.
        self._orphan = NonRecordingSpan
        self._identity = SpanContext
        self._sampled = TraceFlags(TraceFlags.SAMPLED)
        # The one status a span here ever sets, and it sets no
        # description with it: a description is prose, and the only
        # prose a failure has is the far side's message.
        self._failed = Status(StatusCode.ERROR)
        self._provider = provider
        self._tracer = provider.get_tracer(SERVICE)
        self._sdk = sdk
        self._quieted = quieted
        # The transcript export's own half, all of it lazy, because a
        # deployment that exports no transcripts must pay for none of
        # it: no second provider, no second exporter, no second socket.
        # Built on the WORKER's thread at its first job, which is where
        # the only user of it runs and where a construction failure is a
        # contained delivery failure rather than a boot event.
        self._transcripts = transcripts
        self._private: Any | None = None
        self._transcript_lock = threading.Lock()
        self._shutdown_timeout_s = shutdown_timeout_s
        # The release runs once, on a thread of its own, and this is
        # what says whether it has been started and whether it is over.
        # Guarded because `shutdown` may be called twice (a lifespan
        # that unwound twice, a test): a second worker would shut a
        # provider down that is already shutting down and restore the
        # logging under the first one.
        self._closing = threading.Lock()
        self._finished: threading.Event | None = None
        # One offset per CLOCK, because the events package has two and
        # says so: a session event is stamped with the session loop's
        # clock, since the capture's audio tracks are aligned by it, and
        # a server event with `time.monotonic`, since server events fire
        # where no loop is running. Under uvloop, which is what uvicorn
        # runs when it is installed, the loop's clock is libuv's and
        # shares no origin at all with `time.monotonic`: the two read
        # tens of hours apart on the same machine, so one offset for
        # both would put every session span that far from when it
        # happened. A collector accepts those spans and no search window
        # ever contains them, which is what this cost before the Jaeger
        # walkthrough found it.
        #
        # The server clock's offset is read here, because `time.monotonic`
        # reads the same on any thread and at any time.
        wall = time.time()
        self._server_offset = wall - time.monotonic()
        # The session clock's is read at the FIRST session emission
        # instead, which is a reading taken on the session loop, by the
        # loop, whatever loop that turns out to be. Reading it here
        # would be reading it wherever this object happened to be built,
        # and an exporter built outside the loop would then be wrong in
        # exactly the way above and just as quietly. Still one number
        # for the process once it exists, which is what keeps the
        # arithmetic between two spans of one trace exact.
        self._offset: float | None = None
        self._sessions: dict[str, _SessionTrace] = {}
        # `capture_started` that arrived before its session opened, by
        # session id, oldest first and bounded.
        # Held as (epoch, emission) pairs rather than as emissions: a
        # server event is stamped on the server clock, so the conversion
        # belongs where the clock is known, which is the fold that
        # received it and not the session span that eventually claims
        # it.
        self._pending: dict[str, list[tuple[int, Emission]]] = {}
        # `prompt_assembled` that arrived before its session opened, by
        # session id, oldest first and bounded.
        #
        # Emissions rather than the (epoch, emission) pairs above,
        # because this one is a SESSION event and the session clock's
        # offset is one number for the process once it exists: the
        # stamp resolves to the same instant whenever it is read, so
        # holding the conversion would be holding an answer that never
        # differs from the one the claim can compute.
        self._prompts: dict[str, list[Emission]] = {}
        # The trace each session got, by session id, oldest first and
        # bounded, and NOT popped when the span is: what wants it asks
        # after the session closed, because the artifacts it is about
        # are only final by then.
        #
        # The one piece of this object's state with a lock of its own.
        # Everything else here is written and read on the session loop,
        # which is why the span map needs none; this is written there
        # and READ from another thread entirely, so the two operations
        # a write is (record, then evict) are held together rather than
        # left to the interpreter's own atomicity to imply.
        self._retained: dict[str, _Exported] = {}
        self._retained_lock = threading.Lock()
        # How many of them, which is the configured session capacity
        # plus this module's own slack: see `RETAINED_TRACES`.
        self._retention = max(1, retained)
        # Whether emissions are still accepted. Flipped by the lifespan
        # before it detaches anything, so a session still talking while
        # the server tears down cannot open a span nothing will close.
        self._accepting = True
        # The whole span map, as one table read once per emission. A
        # name is here because a span has to be CONSTRUCTED for it;
        # everything the catalog declares and everything it will declare
        # next falls through to the default, which is a span event on
        # whichever span is open.
        self._folds: dict[str, Callable[[str, Emission], None]] = {
            SESSION_OPEN: self._open_session,
            SESSION_CLOSED: self._close_session,
            TURN_STARTED: self._open_turn,
            REPLY_FINISHED: self._close_turn,
            HEARD: self._asr_span,
            NOTHING_HEARD: self._asr_span,
            TRANSCRIPTION_ABANDONED: self._asr_span,
            PROVIDER_FAILED: self._provider_failed,
            PROMPT_ASSEMBLED: self._prompt_assembled,
            LLM_ROUND: self._llm_span,
            TOOL_CALL: self._tool_span,
            SENTENCE_SYNTHESIZED: self._tts_span,
            SPEAKING_STARTED: self._open_playback,
            SPEAKING_FINISHED: self._close_playback,
        }

    # --- what the composition and the device edge ask for -------------

    def session_tap(self) -> EventTap:
        """A consumer for one conversation's events, attached beside
        `LiveEvents` at the same point and detached with it."""
        return _Tap(self._session_event)

    def server_tap(self) -> EventTap:
        """A consumer for the session-independent events, attached once
        for the process by the composition.

        One event reaches the trace this way today: `capture_started`,
        which is emitted on the capture's own channel and carries the
        session id it is about.
        """
        return _Tap(self._server_event)

    def trace_of(self, session: str) -> str | None:
        """The trace one session's spans were exported under, or None
        where this exporter never saw that session.

        The whole of the correlation surface, and deliberately one
        method: what a reader outside this module may know about the
        trace is the identifier a backend takes back, spelled the way
        the wire spells it, and nothing about spans, contexts or the
        SDK's own types.

        Answerable AFTER the session closed, which is the point. The
        span map is popped at `session_closed` and the artifacts a
        reader wants to name the trace beside (the capture's WAV and its
        manifest) are only final after that close, so an id that lived
        as long as the span would never be readable at the moment it is
        wanted. The retention is bounded (`RETAINED_TRACES`) and oldest
        first, so the answer for a session long gone is None, which is a
        reader's cue that the correlation cannot be established rather
        than an invitation to invent one.

        Safe to call from any thread.
        """
        with self._retained_lock:
            exported = self._retained.get(session)
        return None if exported is None else exported.trace

    def reference_media(self, session: str, references: dict[str, str]) -> bool:
        """Put backend-minted media references on the trace this session
        was exported under, and answer whether it was done.

        The second half of an attachment, and the half that makes it
        playable. Uploading a recording associates it with a trace; what
        makes a backend RENDER it is a reference token placed in a
        trace's or an observation's own field, which #67's M1 walkthrough
        established and M3's confirmed. So this writes one span in that
        trace carrying the tokens, as a child of the session span.

        A span rather than a request, and that is forced rather than
        chosen: the backend's ingestion route refuses a trace upsert
        outright on a current self-hosted deployment and names the OTLP
        path as the supported one instead. Which is the better answer
        anyway, because it costs no second transport, no second
        credential and no second timeout: this goes into the bounded
        queue every other span goes into, and a saturated exporter drops
        it rather than delaying anything.

        False where nothing could be written: a session this exporter
        never saw, one whose id has aged out of the retention, or an
        exporter that has stopped accepting because the server is
        shutting down. What a caller does with a False is say so, because
        a recording that is stored and cannot be found is the gap the
        attachment exists to close.

        Safe to call from any thread, which is why it exists in this
        shape at all: it runs on the uploader's worker. It touches the
        span map not at all and the retention under its lock, and the
        SDK's tracer and batch processor are themselves thread-safe.
        """
        if not self._accepting:
            return False
        with self._retained_lock:
            exported = self._retained.get(session)
        if exported is None:
            return False
        span = self._tracer.start_span(
            CAPTURE_SPAN,
            context=self._continuing(exported),
            attributes={
                **dict.fromkeys(SESSION_ID_NAMES, session),
                **_named(exported),
                **{
                    f"{OBSERVATION_METADATA_PREFIX}{name}": token
                    for name, token in references.items()
                },
                OBSERVATION_OUTPUT: "\n".join(references.values()),
            },
        )
        span.end()
        return True

    def retained_context(self, session: str) -> Any | None:
        """The opaque context a span written after this session closed
        belongs in, or None where this exporter has nothing for it
        (#495).

        The narrow read the transcript exporter admits a job on, and it
        is deliberately opaque: what crosses is a handle, never a trace
        id, a span id or an SDK type, so a caller that holds one can put
        a span in the right trace and can learn nothing else from it.

        Asked at ADMISSION and not at export, which is the whole reason
        it exists rather than being folded into the write below. The
        retention is bounded and oldest-evicted, so a job queued behind
        a slow worker could otherwise watch its own context age out
        between the close that made it and the worker that reached it,
        and a healthy export would report that the session had no trace.
        Captured into the job, `no_trace` is an answer about the moment
        the session closed, which is the moment it is about.

        Safe to call from any thread: it touches the span map not at all
        and the retention under its lock.
        """
        with self._retained_lock:
            return self._retained.get(session)

    def export_transcript(
        self, session: str, context: Any, turns: "Sequence[TranscriptTurn]"
    ) -> Delivery:
        """One page of a closed session's turns, as spans in the trace
        that session was exported under, delivered and answered for
        (#495).

        One span per turn, named `transcript`, a child of the session
        span by the passed context. It carries the session under both
        spellings so the query a reader already makes returns it beside
        the turns, the turn's ordinal and the store's own row id, the
        turn's offset and the agent it opened with, and the text in the
        two fields the backend renders as an observation's input and
        output. Where a handover split the reply, the per-leg
        attribution rides one canonical-JSON string attribute.

        The spans do NOT ride the shared batch queue, and that is the
        design rather than an optimization: that queue drops on
        saturation and swallows a collector failure, so a transcript
        that never arrived would be indistinguishable from one that did,
        and the whole point of this surface is that a reader can tell.
        They are built on a private tracer bound to the same resource,
        collected in memory, and handed to a dedicated exporter instance
        of the same class the batch queue uses, reading the same
        `OTEL_EXPORTER_OTLP_*` environment: one transport vocabulary and
        one credential family, and an answer.

        The call's bound is that exporter's own deadline, which covers
        its internal retries and is the whole retry policy here: a
        backend that is down stays down for longer than a worker should
        wait, and the failure event is the honest report.

        Timestamped at export time, and ordered by the ordinal rather
        than by a synthetic conversation clock: a span claiming to have
        happened at the turn's `t_ms` would be the one dishonest fact on
        a surface whose value is being checkable against the store.

        Answers `STOPPED` where nothing was attempted (this exporter has
        stopped accepting, or the spans would not build), and otherwise
        whether the far side took the batch. It never raises, because
        its caller is a worker whose failures are events.

        Safe to call from any thread, which is why it exists in this
        shape: it runs on the transcript exporter's own worker.
        """
        if not self._accepting:
            return Delivery.STOPPED
        try:
            spans = self._transcript_spans(session, context, turns)
        except Exception:  # noqa: BLE001 - a worker never dies of a page
            # Deliberately unbound and deliberately silent, the rule
            # this module applies to every containment: what is never
            # looked at cannot leak by accident later.
            return Delivery.STOPPED
        if not spans:
            return Delivery.DELIVERED
        return self._deliver(spans)

    def _transcript_spans(
        self, session: str, context: Any, turns: "Sequence[TranscriptTurn]"
    ) -> list[Any]:
        """This page's turns as finished spans, held here rather than
        queued anywhere.

        The private provider is built once and lazily, on the thread
        that first needs it, and has NO span processor at all, which is
        the whole trick: a provider with nothing attached still builds
        and ends real spans, and an ended span is exactly what an
        exporter takes. So the page exists as a list this function
        returns, and there is no second queue anywhere to drop it,
        flush it or export it behind this caller's back.

        Bound to the same resource as the shared provider, spelled the
        same way from the same two facts, because a transcript is the
        same service's span and a second service name would put it in a
        row of its own in every backend.
        """
        with self._transcript_lock:
            if self._private is None:
                self._private = self._sdk.provider(
                    resource=self._sdk.resource(
                        attributes={
                            self._sdk.name_key: SERVICE,
                            self._sdk.version_key: revision(),
                        }
                    )
                )
            tracer = self._private.get_tracer(SERVICE)
        spans = []
        for turn in turns:
            span = tracer.start_span(
                TRANSCRIPT_SPAN,
                context=self._continuing(context),
                attributes={
                    **_named(context),
                    **_transcript_attributes(session, turn),
                },
            )
            span.end()
            spans.append(span)
        return spans

    def _deliver(self, spans: list[Any]) -> Delivery:
        """The bounded call itself, and the one place this module asks a
        transport for an answer.

        The instance is constructed here, at the first page that needs
        it, on the caller's thread: a construction that fails is a
        delivery that failed, never a boot that refused, which is the
        same posture the uploader's client takes. Every exception is
        contained, and none of it is looked at: what a failing export
        holds is the endpoint and its credentials.
        """
        try:
            if self._transcripts is None:
                self._transcripts = _otlp_exporter()
            answer = self._transcripts.export(spans)
        except Exception:  # noqa: BLE001 - a failure here is an event, not a raise
            return Delivery.UNDELIVERED
        if answer is self._sdk.result.SUCCESS:
            return Delivery.DELIVERED
        return Delivery.UNDELIVERED

    def _continuing(self, exported: _Exported) -> Any:
        """The context a span written after a session closed belongs in.

        Every span of that trace has ended, so what continues it is the
        session span's identity rather than a span this process still
        holds. One home for it because two writers need it now, the
        media reference and the upload outcomes, and a second spelling
        of a parentage is a second trace waiting to happen.
        """
        return self._within(
            self._orphan(
                self._identity(
                    trace_id=exported.trace_id,
                    span_id=exported.span_id,
                    is_remote=True,
                    trace_flags=self._sampled,
                )
            )
        )

    def stop_accepting(self) -> None:
        """Take no more emissions.

        The first step of the teardown, ahead of the detach: a tap comes
        off one attachment point at a time, and a session mid-reply goes
        on emitting until it does.
        """
        self._accepting = False

    def flush(self) -> bool:
        """Hand whatever is queued to the exporter now, and answer
        whether it got there before the export timeout.

        Part of the interface rather than a hook a test reached in for:
        "has what I emitted actually left" is the one question about an
        exporter that cannot be answered from outside it, and the
        shutdown below asks it implicitly. It BLOCKS, which is why no
        path that serves a device calls it.
        """
        flushed: bool = self._provider.force_flush()
        return flushed

    async def shutdown(self) -> None:
        """Flush what is queued and let the SDK's thread go, bounded.

        Off the loop, because the SDK's shutdown joins a thread, and
        bounded, because a collector that has stopped answering must not
        hold a redeploy open. What a timeout costs is spans, which is
        the trade the bounded queue already makes.

        The wait is bounded and the QUIETING IS NOT. That asymmetry is
        the whole of this method's design. A shutdown that expired left
        an export still in flight against the endpoint it could not
        reach, and that export is going to fail and log the URL it
        failed against; restoring the SDK's logging when the WAIT ended
        would put the operator's endpoint, userinfo and all, into the
        retained log a second or two later, on a path nothing was
        watching any more. So the worker restores it from its own
        `finally`, when the work is genuinely over, and the timeout here
        only stops the lifespan waiting.

        The worker is a daemon thread of this method's own rather than
        `asyncio.to_thread`. The default executor's threads are joined
        by an `atexit` hook, so an abandoned export on one of them would
        hold the process open exactly as long as the collector felt like
        holding it, which is the thing a bounded shutdown exists to
        prevent. A daemon thread is dropped at exit instead, which is
        the honest ending for work whose result is spans nobody is going
        to read.
        """
        self._accepting = False
        finished, mine = self._claim()
        if mine:
            try:
                threading.Thread(
                    target=self._complete,
                    name="vinga-telemetry-shutdown",
                    daemon=True,
                ).start()
            except Exception:  # noqa: BLE001 - a teardown never raises at the operator
                # A process that cannot start a thread has larger
                # problems than its spans, and this method's job is to
                # leave none of them here. What must not survive is an
                # exporter nothing owns: the claim was taken before the
                # start, so a later caller would wait on a completion
                # nobody was ever going to reach, and the SDK's silence
                # would be held for the life of the process.
                #
                # So this is a completion too, and the same one every
                # other caller is waiting on: the claim goes back and
                # the event is set. The provider is deliberately NOT
                # shut down here, because that call blocks for as long
                # as the collector takes and doing it inline would put a
                # stalled collector on the event loop, which is the one
                # thing this whole design refuses. What is lost is the
                # SDK's own thread, which is a daemon and dies with the
                # process.
                self._quieted.release()
                finished.set()
                logger.warning(
                    "the telemetry exporter could not be released on a thread "
                    "of its own and was left to the process's exit"
                )
        # Off the loop for the wait itself, and with the bound passed to
        # `wait` rather than wrapped in `wait_for`, so the pool thread is
        # released at the deadline instead of being pinned to an export
        # that may never end.
        if not await asyncio.to_thread(finished.wait, self._shutdown_timeout_s):
            # A plain sentence and nothing about the far side: what
            # could not be reached is the endpoint, which is the one
            # string this module never writes down.
            logger.warning(
                "the telemetry exporter did not finish within %.0f s and was left behind",
                self._shutdown_timeout_s,
            )

    def release(self) -> None:
        """Shut the provider down and give the SDK's logging back, in
        that order, however it ended.

        BLOCKS for as long as the collector takes, which is why no path
        that serves a device calls it: `shutdown` above is this same
        work off the loop and under a bound, which is what a lifespan
        wants. A caller that is holding an exporter it no longer wants
        and has nothing to wait for calls this.

        Exactly once per exporter, whoever asks and however many ask.
        This and `shutdown`'s worker are the same operation with two
        doors, and running it twice was a leak rather than a waste: the
        SDK's own processor early-returns from a second shutdown, so the
        second caller finished instantly and gave the logging lease back
        while the first was still inside the export, which un-silences
        the endpoint-bearing failures the first one is about to log. So
        the first caller through claims it and the rest wait on the
        completion, and a caller that arrives after it is over returns
        at once.

        The wait is unbounded, which is this method's whole contract:
        a caller that cannot afford to wait wants `shutdown` above.
        """
        finished, mine = self._claim()
        if mine:
            self._complete()
            return
        finished.wait()

    def _claim(self) -> tuple[threading.Event, bool]:
        """The one completion this exporter has, and whether the caller
        just became the one that owes it.

        Under the lock, so exactly one of any number of concurrent
        callers is told it owns the release and every other is handed
        the same event to wait on.
        """
        with self._closing:
            if self._finished is None:
                self._finished = threading.Event()
                return self._finished, True
            return self._finished, False

    def _complete(self) -> None:
        """Shut the provider down and give the SDK's logging back, in
        that order, and then let everyone waiting go.

        Run by the caller that claimed it and by nobody else. The
        restore is here rather than in whoever asked, and that is the
        whole of the delta round's finding 2: this runs on the abandoned
        side of a timeout as often as not, and everything the SDK is
        going to say about a collector it cannot reach, it says between
        these two lines.
        """
        try:
            self._provider.shutdown()
        except Exception:  # noqa: BLE001 - a teardown never raises at the operator
            # Unbound, for the reason the build's own containment gives:
            # what a failing export was holding is the endpoint.
            pass
        finally:
            self._close_transcripts()
            self._quieted.release()
            if self._finished is not None:
                self._finished.set()

    def _close_transcripts(self) -> None:
        """Let the transcript export's own half go, if it was ever built.

        Both halves under one guard, on a path that is already finishing
        however it ended. Nothing waits on it: the transcript exporter's
        own shutdown is pushed LAST onto the composition's exit stack
        and therefore unwinds FIRST, so by the time this runs its worker
        has finished or has been left behind with a lease of its own.
        """
        provider, self._private = self._private, None
        transports, self._transcripts = self._transcripts, None
        for closing in (provider, transports):
            if closing is None:
                continue
            with contextlib.suppress(Exception):
                closing.shutdown()

    # --- the fold -----------------------------------------------------

    def _session_event(self, emission: Emission) -> None:
        """One conversation event, folded onto the trace."""
        if not self._accepting:
            return
        payload = emission.payload
        name = payload.get(EVENT_FIELD)
        session = payload.get(SESSION_FIELD)
        if not isinstance(session, str):
            return
        if not isinstance(name, str) or name not in APPROVED:
            # A name the catalog does not declare is not folded at all,
            # and the check is HERE rather than at the export: a span
            # event is named after the event, so an undeclared name is
            # itself exported content, and whatever put it in the
            # payload is not this repository's catalog. The default
            # fold below is a default over the DECLARED events, not
            # over any string that arrives.
            return
        # The table where a span has to be built, and a span event on
        # whichever span is open everywhere else. The default is what
        # keeps this from having to be revisited every time the catalog
        # grows a variant.
        self._folds.get(name, self._span_event)(session, emission)

    def _server_event(self, emission: Emission) -> None:
        """One server-scoped event, folded where it belongs.

        Only the events that name a session have a destination in a
        trace, and three do. `capture_started` arrives BEFORE its
        session's span exists, because a capture opens during the
        handshake and the handshake is ahead of `session_open`, so one
        that finds no span is held rather than dropped: the ordering is
        the ordinary case rather than a race. The two upload outcomes
        arrive AFTER the span has ended, because a recording's trip to
        the backend runs on a worker of its own once the session is
        over, so those find the retention instead.
        """
        if not self._accepting:
            return
        payload = emission.payload
        name = payload.get(EVENT_FIELD)
        if name != CAPTURE_STARTED and name not in AFTER_THE_CLOSE:
            return
        session = payload.get(SESSION_FIELD)
        if not isinstance(session, str):
            return
        at = _epoch_ns(emission.at, self._server_offset)
        if session in self._sessions:
            self._span_event(session, emission, at)
            return
        if name in AFTER_THE_CLOSE:
            self._after_the_close(session, emission, at)
            return
        held = self._pending.setdefault(session, [])
        held.append((at, emission))
        while len(self._pending) > PENDING_CAPTURES:
            # Oldest first: a held event whose session never opened is a
            # session that was refused after its capture started, and
            # the hold is a buffer rather than a record.
            self._pending.pop(next(iter(self._pending)))

    def _after_the_close(self, session: str, emission: Emission, at: int) -> None:
        """One outcome of a recording's trip to the backend, on the
        trace that session was exported under.

        A SPAN rather than a span event, and that is a finding rather
        than a preference: #67's first walkthrough established that the
        backend this surface exists for ingests no span events at all,
        so an outcome recorded as one would be invisible in the one
        place a reader goes looking for it. As a span it is an
        observation beside the session's own, which is what the
        milestone promised: a trace whose reader can see that a
        recording is there, or that it is not and why.

        Parented into the retained context the way a media reference is,
        for the same reason and by the same mechanism: every span of
        this trace has ended, so what continues it is the parent's
        identity rather than a span this process still holds.

        Nothing at all for a session this exporter never saw, or one
        that has aged out: the boot sweep's `abandoned` is about a
        session a PREVIOUS process ran, so there is no trace of this
        process's to put it on, and inventing one would be worse than
        the JSON log it is already in.
        """
        name = emission.payload.get(EVENT_FIELD)
        if not isinstance(name, str) or name not in APPROVED:
            return
        with self._retained_lock:
            exported = self._retained.get(session)
        if exported is None:
            return
        span = self._tracer.start_span(
            name,
            context=self._continuing(exported),
            attributes={
                **dict.fromkeys(SESSION_ID_NAMES, session),
                **_named(exported),
                **_event_attributes(emission.payload),
            },
            start_time=at,
        )
        span.end(end_time=at)

    def _open_session(self, session: str, emission: Emission) -> None:
        if session in self._sessions:
            return
        payload = emission.payload
        # What this conversation opened against, kept whole: every agent
        # the device is bound to, so a handover switches which of them a
        # span is stamped from rather than needing entries this exporter
        # was never given.
        held = _provider_context(payload.get("providers"))
        agent = payload.get("agent")
        talking = agent if isinstance(agent, str) else None
        # Through the same gate once, and read from there twice: the
        # live session's spans take the whole identity and the retained
        # record takes the board's name out of it. A second read of the
        # payload would be a second place for the name to be spelled.
        identity = _attributes(payload, CONTEXT_ATTRIBUTES)
        span = self._tracer.start_span(
            SESSION_SPAN,
            context=self._root(),
            attributes={
                **_attributes(payload, SESSION_ATTRIBUTES),
                **_provider_attributes(held, talking),
            },
            start_time=self._at(emission),
        )
        self._sessions[session] = _SessionTrace(
            span=span,
            identity=identity,
            providers=held,
            agent=talking,
        )
        self._retain(session, span, identity.get(DEVICE_NAME))
        # Through the fold that holds them rather than beside it, so
        # the retention rule and the span event are written once: what
        # the claim changes is only that there is now a trace to place
        # them on.
        for prompt in self._prompts.pop(session, []):
            self._prompt_assembled(session, prompt)
        for at, waiting in self._pending.pop(session, []):
            self._span_event(session, waiting, at)

    def _prompt_assembled(self, session: str, emission: Emission) -> None:
        """One agent's assembled know-how half, retained and then said.

        Retained because the event is emitted once per AGENT and the
        attribute belongs on every turn that agent speaks, which is the
        mechanism the provider context already uses; and still a span
        event, because when the prompt was assembled is a fact about
        this session's timeline and the span it lands on is where a
        reader meets it.

        Held where the session has no span yet, which is the ordinary
        case rather than a race: the first agent is activated while the
        runtime is being constructed, and the runtime is constructed
        before the hello exchange. `_open_session` claims what is
        waiting for it.
        """
        trace = self._sessions.get(session)
        if trace is None:
            held = self._prompts.setdefault(session, [])
            held.append(emission)
            while len(self._prompts) > PENDING_PROMPTS:
                # Oldest first, the capture hold's own rule and for the
                # same reason: a held event whose session never opened
                # is a session that was refused, and the hold is a
                # buffer rather than a record.
                self._prompts.pop(next(iter(self._prompts)))
            return
        payload = emission.payload
        agent = payload.get("agent")
        talking = agent if isinstance(agent, str) else trace.agent
        attributes = _prompt_attributes(payload)
        if talking is not None and attributes:
            trace.prompts[talking] = attributes
        self._span_event(session, emission)

    def _retain(self, session: str, span: Any, name: Any = None) -> None:
        """Remember which trace this session's spans went out under, for
        whoever asks after it is over.

        Written at the open rather than at the close, because that is
        where the id exists and because a session that never closes
        (a process that lost it) is one a reader may still ask about.

        And what the board was called then, so that the three writers
        that run after the close say what the session said rather than
        what the configuration holds by the time they run.
        """
        context = span.get_span_context()
        with self._retained_lock:
            self._retained[session] = _Exported(
                trace=self._spelled(context.trace_id),
                trace_id=context.trace_id,
                span_id=context.span_id,
                name=name if isinstance(name, str) else None,
            )
            while len(self._retained) > self._retention:
                # Oldest first, the hold's own rule: what a late reader
                # wants is a session that has just ended.
                self._retained.pop(next(iter(self._retained)))

    def _close_session(self, session: str, emission: Emission) -> None:
        trace = self._sessions.pop(session, None)
        if trace is None:
            return
        if trace.turn is not None:
            # A session that ended with a reply still in flight. The
            # turn's own `reply_finished` is emitted from the reply's
            # `finally` and lands before this, so reaching here means the
            # process is losing the turn rather than closing it: it is
            # left unended and never exported, which is the same posture
            # a lost batch queue takes.
            trace.turn = None
        # And a playback span with no closing event, for the same reason
        # a lost turn is dropped: what it is missing is its own end, and
        # the session's is not a substitute for it.
        trace.playback = None
        trace.span.set_attributes(
            _attributes(emission.payload, SESSION_CLOSE_ATTRIBUTES)
        )
        trace.span.end(end_time=self._at(emission))

    def _open_turn(self, session: str, emission: Emission) -> None:
        trace = self._sessions.get(session)
        if trace is None or trace.turn is not None:
            return
        # A playback span the previous turn left open is dropped here.
        # It is held past `reply_finished` on purpose (see there), but a
        # NEXT turn starting means its own event will never arrive: the
        # only way that happens is a cancellation delivered into the
        # reply's very last statement, and an interval with no last
        # frame is one this exporter declines to invent an end for.
        trace.playback = None
        # A new turn has not been transcribed yet, whatever the last one
        # did.
        trace.transcribed = False
        trace.turn = self._tracer.start_span(
            TURN_SPAN,
            # An empty context, which is what gives the turn a trace id
            # of its own rather than making it a child. Linked instead,
            # so a backend can list a session's turns without every turn
            # hiding inside one enormous trace.
            context=self._root(),
            links=[self._link(trace.span.get_span_context())],
            attributes={
                # The session's own identity, off the retained context
                # rather than off this payload, because `turn_started`
                # names the session and the device and knows nothing
                # about what the board is CALLED. The two facts it does
                # carry arrive under the same names with the same
                # values from its own table below, which is what makes
                # this a widening rather than a second source.
                **trace.identity,
                **_attributes(emission.payload, TURN_ATTRIBUTES),
                # The agent this turn is actually being spoken by, which
                # a handover may have changed since the session opened.
                **_provider_attributes(trace.providers, trace.agent),
                # And what that agent's prompt was assembled out of,
                # from the same retained state and read by the same
                # agent: the event said it once, and every turn the
                # agent speaks is a turn the prompt was behind.
                **trace.prompts.get(trace.agent or "", {}),
            },
            # The stamp the emission carries, which for `turn_started`
            # is the instant the user stopped speaking rather than the
            # instant the event was said.
            start_time=self._at(emission),
        )

    def _close_turn(self, session: str, emission: Emission) -> None:
        trace = self._sessions.get(session)
        if trace is None or trace.turn is None:
            return
        turn, trace.turn = trace.turn, None
        # A playback span still open here is deliberately NOT closed and
        # not dropped. `reply_finished` is the reply `finally`'s first
        # statement and `finish_speaking` is its last, so the event that
        # closes the paced interval is emitted AFTER the event that
        # closes the turn, while being STAMPED at the last delivery,
        # which is before both. The span is left open for its own event
        # to end it, and what it ends up bounding is the interval the
        # pacer paced rather than the order the two records were made
        # in. `_open_turn` and `_close_session` drop one that never got
        # its event, so nothing accumulates.
        turn.set_attributes(_attributes(emission.payload, TURN_FINISHED_ATTRIBUTES))
        turn.end(end_time=self._at(emission))

    # --- the stage spans ----------------------------------------------
    #
    # Each is constructed retrospectively out of the event that ENDED
    # it, which is what lets a trace be assembled from a tap that
    # watches nothing: the pipeline already measured every interval
    # below, and the exporter's arithmetic is one subtraction against
    # the session clock's one offset. A stage whose turn is not open
    # falls through to the span-event fold, so nothing is ever
    # silently dropped.

    def _context(
        self,
        trace: _SessionTrace,
        payload: dict[str, Any],
        states: str | None = None,
    ) -> dict[str, Any]:
        """The session-level context every stage span carries.

        One derivation for all four, because they all want the same
        thing and a per-stage copy would be four places to forget: the
        session's own identity as `session_open` stated it, and the
        resolved providers of whichever agent this event belongs to.

        The event's own agent decides, and the session's current one
        stands in where the event named none: a stage span belongs to
        the agent that ran it, and after a handover that is not the
        agent the session opened with.

        `states` names a stage this span answers for ITSELF, whose
        context entries are therefore left out. All three provider
        stages can: `llm_round`, `heard` and `sentence_synthesized` each
        carry the entry that actually ran, which after a mid-session
        change is not the entry the session opened against, and one
        attribute name may have one source. So the span speaks for its
        own stage and the retained context speaks for the rest.

        WHETHER a span states its own stage is the caller's question,
        and `_speaks_for` is where the two success-side stage folds ask
        it: an event that named no entry states nothing, so that fold
        passes nothing here and what the session opened against survives
        on the span.
        """
        agent = payload.get("agent")
        talking = agent if isinstance(agent, str) else trace.agent
        entries = _provider_attributes(trace.providers, talking)
        if states is not None:
            spoken = f"{PROVIDER_PREFIX}.{states}."
            entries = {
                name: held
                for name, held in entries.items()
                if not name.startswith(spoken)
            }
        return {**trace.identity, **entries}

    def _asr_span(self, session: str, emission: Emission) -> None:
        """One transcription, however it ended.

        Four outcomes and one span, because they are four ends of one
        stage rather than four stages: what differs is the outcome
        attribute, whether the span is marked failed, and which field
        says how long the call ran. An empty transcript gets a real span
        with a real duration and an outcome that says nothing was heard,
        which is the whole of the issue's motivating gap.
        """
        trace = self._sessions.get(session)
        if trace is None or trace.turn is None or trace.transcribed:
            # A turn has ONE ASR stage, and the second event that could
            # end one is not a second transcription of it. The shape
            # this refuses is the gate's: a barge-in candidate whose
            # confirmation fails emits `provider_failed` at the ASR
            # stage while the turn being spoken over is still open, and
            # the plan is explicit that a rejected candidate's failure
            # stays gate vocabulary on the turn it interrupted. So the
            # first ASR outcome builds the stage span and every later
            # one folds as the span event it is.
            self._span_event(session, emission)
            return
        payload = emission.payload
        outcome = payload.get(EVENT_FIELD)
        end = self._at(emission)
        # The event's own attributes decide whether the retained context
        # still speaks for the ASR stage here: an outcome that named the
        # ear it ran on states that stage whole, and one that named none
        # leaves what the session opened against standing.
        spoken = _attributes(payload, ASR_ATTRIBUTES)
        attributes = {
            **self._context(trace, payload, states=_speaks_for(ASR_STAGE, spoken)),
            **spoken,
        }
        # The one attribute on any span here that is not a payload
        # field: which of the four ends this was, which is the event's
        # own NAME rather than anything the event carried. It goes on
        # after the declared-shape gate because there is nothing for
        # that gate to check, the value being one of four strings this
        # module names itself.
        attributes[ASR_OUTCOME] = outcome
        span = self._tracer.start_span(
            ASR_SPAN,
            context=self._within(trace.turn),
            attributes=attributes,
            start_time=_before(end, payload.get(ASR_LENGTH.get(str(outcome), ""))),
        )
        if outcome == PROVIDER_FAILED:
            # The only stage span that is ever marked failed, and the
            # only one of the four ASR outcomes that IS a failure:
            # nothing failed when a transcript came back empty, and
            # nothing failed when the answer stopped being wanted.
            span.set_status(self._failed)
        span.end(end_time=end)
        trace.transcribed = True

    def _provider_failed(self, session: str, emission: Emission) -> None:
        """A provider failure, which is an ASR outcome or a span event.

        The stage is what decides. An ASR failure ends the turn's ASR
        stage and is one of its four ends; an LLM or TTS failure ends no
        interval this exporter draws, because the LLM and TTS spans are
        built from the rounds and the streams that finished, so it folds
        onto the turn with the fields the catalog gave it.
        """
        if emission.payload.get("stage") == ASR_STAGE:
            self._asr_span(session, emission)
            return
        self._span_event(session, emission)

    def _llm_span(self, session: str, emission: Emission) -> None:
        """One generation, with the settled GenAI vocabulary on it.

        The span carries the correspondence table exactly and nothing
        else of the provider: what a backend reads is the provider type,
        the model, the host, and the two token counts, under the keys
        the conventions chose for them, plus the configured entry's name
        under vinga's own.

        `first_token_ms` becomes a span event inside the round rather
        than an attribute beside it, because it is an INSTANT: a backend
        that draws a span draws it, and the gap between the round's
        start and that mark is the number a stalled reply is diagnosed
        by. A round that only asked for a tool timed no spoken token and
        gets no mark, which is a fact about the round rather than a
        missing measurement.
        """
        trace = self._sessions.get(session)
        if trace is None or trace.turn is None:
            self._span_event(session, emission)
            return
        payload = emission.payload
        end = self._at(emission)
        start = _before(end, payload.get("duration_ms"))
        span = self._tracer.start_span(
            LLM_SPAN,
            context=self._within(trace.turn),
            attributes={
                **self._context(trace, payload, states=LLM_STAGE),
                **_attributes(payload, LLM_ATTRIBUTES),
            },
            start_time=start,
        )
        first_token = _after(start, payload.get("first_token_ms"))
        if first_token is not None:
            span.add_event(FIRST_TOKEN, timestamp=first_token)
        span.end(end_time=end)

    def _tool_span(self, session: str, emission: Emission) -> None:
        """One tool call, as a child of the turn that asked for it.

        A span rather than the span event it used to be, and the span
        event goes away rather than staying beside it. #67's first
        walkthrough established that the backend this surface exists for
        ingests no span events at all, which is why an MCP call was
        invisible on a trace that recorded everything around it; and two
        carriers of one fact on one trace would be the locality rule
        broken in the module that has been most careful about it, with a
        backend that DOES ingest span events showing every call twice.

        Built retrospectively out of `duration_ms` with the same helper
        every stage span uses, so the failure mode where a call is
        misplaced in time is the known one rather than a new one.

        The retained identity and the event's own agent and thread, and
        deliberately not the provider entries: a tool call ran on no
        pipeline stage, so what the session opened against says nothing
        about it.
        """
        trace = self._sessions.get(session)
        if trace is None or trace.turn is None:
            self._span_event(session, emission)
            return
        payload = emission.payload
        end = self._at(emission)
        span = self._tracer.start_span(
            TOOL_SPAN,
            context=self._within(trace.turn),
            attributes={
                **trace.identity,
                GEN_AI_OPERATION: EXECUTE_TOOL,
                **_attributes(payload, TOOL_ATTRIBUTES),
            },
            start_time=_before(end, payload.get("duration_ms")),
        )
        span.end(end_time=end)

    def _tts_span(self, session: str, emission: Emission) -> None:
        """One sentence's synthesis stream, named for what it is.

        The extent is `stream_ms`, the stream's whole lifetime, which
        includes however long the paced consumer held the provider: the
        buffer holds one chunk, so playback decides when the next one is
        asked for, and pure synthesis time is unobservable for a
        streaming voice. That is why the span is not called synthesis
        and why the duration is not repeated as an attribute under a
        name that would claim to be one.

        `first_chunk_ms` is the number that IS the provider's: measured
        producer-side before backpressure can bite, and therefore an
        attribute a backend can compare across voices.
        """
        trace = self._sessions.get(session)
        if trace is None or trace.turn is None:
            self._span_event(session, emission)
            return
        payload = emission.payload
        end = self._at(emission)
        # As on the ASR span: the stream that named the voice it ran on
        # states the TTS stage itself, and the retained context goes on
        # speaking for every stage this event says nothing about.
        spoken = _attributes(payload, TTS_ATTRIBUTES)
        span = self._tracer.start_span(
            TTS_SPAN,
            context=self._within(trace.turn),
            attributes={
                **self._context(trace, payload, states=_speaks_for(TTS_STAGE, spoken)),
                **spoken,
            },
            start_time=_before(end, payload.get("stream_ms")),
        )
        span.end(end_time=end)

    def _open_playback(self, session: str, emission: Emission) -> None:
        """The paced interval opens at the first frame that reached the
        device.

        The one stage span with two ends, because it is the one interval
        the pipeline hands over as two instants rather than as a
        duration. Both are real deliveries: `speaking_started` is
        stamped at the first successful delivery and `speaking_finished`
        at the last, so what this bounds is what the pacer paces and not
        the reply's whole life.
        """
        trace = self._sessions.get(session)
        if trace is None or trace.turn is None or trace.playback is not None:
            self._span_event(session, emission)
            return
        trace.playback = self._tracer.start_span(
            PLAYBACK_SPAN,
            context=self._within(trace.turn),
            attributes={
                **self._context(trace, emission.payload),
                **_attributes(emission.payload, PLAYBACK_ATTRIBUTES),
            },
            start_time=self._at(emission),
        )

    def _close_playback(self, session: str, emission: Emission) -> None:
        """The last frame out, and the count of everything that went.

        The count is the reply's, kept across a handover: what the
        interval bounds is one reply's audio, however many agents
        produced it.
        """
        trace = self._sessions.get(session)
        if trace is None or trace.playback is None:
            self._span_event(session, emission)
            return
        span, trace.playback = trace.playback, None
        span.set_attributes(_attributes(emission.payload, PLAYBACK_ATTRIBUTES))
        span.end(end_time=self._at(emission))

    def _span_event(
        self, session: str, emission: Emission, at: int | None = None
    ) -> None:
        """One event that opens and closes nothing, on whichever span is
        open.

        The turn where there is one, so a barge-in suppression lands on
        the turn it interrupted; the session otherwise, which is where
        `session_idle`, `capture_started`, `handover` and any
        turn-scoped straggler that arrives between turns belong.
        """
        trace = self._sessions.get(session)
        if trace is None:
            return
        name = emission.payload.get(EVENT_FIELD)
        if not isinstance(name, str) or name not in APPROVED:
            # Again here, and not only at the fold's door: this is
            # reached from the server channel too, and the span event's
            # NAME is the one piece of exported content no attribute
            # table stands in front of.
            return
        span = trace.turn if trace.turn is not None else trace.span
        span.add_event(
            name,
            attributes=_event_attributes(emission.payload),
            # The caller's epoch where it had one, which is how an event
            # stamped on the server's clock reaches the session's
            # timeline: the conversion happened where the clock was
            # known.
            timestamp=self._at(emission) if at is None else at,
        )
        if name == HANDOVER:
            # The one span event that changes what later spans say about
            # themselves. Read from the event rather than tracked
            # anywhere else: which agent is talking is a fact the
            # catalog states, and a second copy of it here would be the
            # side channel the one-vocabulary rule exists to refuse.
            moved = emission.payload.get("to_agent")
            if isinstance(moved, str):
                trace.agent = moved

    def _at(self, emission: Emission) -> int:
        """One session emission's stamp as the epoch nanoseconds a span
        wants, through the session clock's one offset.

        Resolved here, at the first session emission, and never again.
        Reading it here means reading it ON the session loop, by the
        loop, which is the only place the loop's own clock can be
        compared with the wall clock at all.
        """
        if self._offset is None:
            self._offset = time.time() - session_clock()
        return _epoch_ns(emission.at, self._offset)


def _transcript_attributes(session: str, turn: TranscriptTurn) -> dict[str, Any]:
    """One turn's span attributes, written out here rather than folded
    from a payload (#495).

    Not through `_attributes` and its tables, and the difference is the
    point: those tables fold a DECLARED event's fields through the
    catalog's own value gate, and a transcript is not an event. What it
    is, is a projection of the conversation store read post hoc, so what
    a span may carry is decided here, field by field, from a type whose
    seven members are the whole of what crossed the seam.

    An absent half contributes no attribute rather than a null: a turn
    recorded before the text switch went on has nothing to say, and an
    attribute saying `None` would be a claim the store did not make.
    """
    attributes: dict[str, Any] = {
        **dict.fromkeys(SESSION_ID_NAMES, session),
        TURN_INDEX: turn.index,
        TURN_ID: turn.id,
        TURN_T_MS: turn.t_ms,
    }
    if turn.agent is not None:
        attributes[TURN_AGENT] = turn.agent
    if turn.heard is not None:
        attributes[OBSERVATION_INPUT] = turn.heard
    if turn.reply is not None:
        attributes[OBSERVATION_OUTPUT] = turn.reply
    legs = _legs(turn.legs)
    if legs is not None:
        attributes[TRANSCRIPT_LEGS] = legs
    return attributes


def _legs(held: Any) -> str | None:
    """A split reply's per-leg attribution as one canonical JSON string,
    or nothing at all (#495).

    Allowlisted rather than serialized: each leg contributes its agent
    and its text and nothing else, so the token halves the column also
    holds cannot reach a span through here even if the column grows a
    field. Canonical means sorted keys and no extra whitespace, which is
    what makes the exact string pinnable by a unit case and identical
    from one run to the next.

    Nothing for a turn no handover split, which is most turns: the reply
    column is the whole of those, and an empty array would be an
    attribute saying nothing.
    """
    if not isinstance(held, list) or not held:
        return None
    legs = [
        {
            field: leg[field]
            for field in LEG_FIELDS
            if isinstance(leg.get(field), str)
        }
        for leg in held
        if isinstance(leg, dict)
    ]
    if not legs:
        return None
    return json.dumps(legs, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _event_attributes(payload: dict[str, Any]) -> dict[str, Any]:
    """One span event's attributes: the fields the catalog declares for
    this event, keeping the names it gave them.

    The iteration is over the APPROVED table and not over the payload,
    which is the whole of the difference from what this used to do: a
    key the catalog does not declare for this event is not exported,
    whatever put it in the dict. The identities the emitter contributes
    are left out because they are already on the span this is being
    added to, and the event name because it IS the span event's name.
    """
    attributes: dict[str, Any] = {}
    for key, rule in _rules(payload).items():
        if key in _IDENTITIES:
            continue
        held = _as_attribute(payload.get(key), rule)
        if held is not None:
            attributes[key] = held
    return attributes


@dataclass
class _Tap:
    """One attachment point, as the events package's `EventTap`.

    A thin object over a bound method rather than two tap classes: what
    differs between the session and the server attachment is which fold
    an emission goes to, and nothing else. It exists at all because the
    protocol asks for an `emit`, and because the class NAME is what the
    events package reports when a tap raises, which is the one thing
    about a consumer that report is allowed to say.
    """

    fold: Callable[[Emission], None] = field(repr=False)

    def emit(self, emission: Emission) -> None:
        self.fold(emission)
