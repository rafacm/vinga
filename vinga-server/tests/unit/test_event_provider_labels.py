"""Which configured entry a success-side stage event names (#450).

`heard` and `sentence_synthesized` carry the four entry names
`llm_round` carries, so that "ASR latency by provider" and "TTS latency
by provider" are answerable from the vocabulary. The catalog says the
two variants declare the four fields and the driver suite
(`test_event_baseline.py`) says the two paths produce them, and neither
can say anything about what is IN them: a `CARRIED` row is a set of
keys, so it stays green with `provider` and `type` swapped, with the
wrong provider object handed to a builder, or with a TTS record
labelled from ASR identity.

So the entries under test are stamped with eight values, four per
stage, every one of them distinguishable from every other, and each
record's four fields are asserted BY VALUE. A swap fails, a cross-stage
mislabel fails, and the two absences a real deployment produces (an
engine that runs in this process reaches no host; a type may have no
model to name) are pinned one at a time, separately from the
all-four-absent case a provider the registry never built produces.

Two claims here are not about values at all.

**The sentences did not move.** The four names are carried payload and
neither TEMPLATE nor ARGS gained a position, which is what makes the
change cheap to review; it is asserted rather than assumed, on the
unrendered message and the typed arguments of both records.

**A reused transcription is labelled with the ear that ran it.** A
confirmed barge-in transcribes to decide the cancel and the reply that
answers reuses the result, and the reply in flight can hand the
conversation over while that call is awaited, which rebinds the
session's providers. Reading the binding at the emit would put the
confirmation's latency and somebody else's identity in the two halves
of one record. The pin drives exactly that race, deterministically, by
suspending the confirmation inside the ear and handing over while it is
held.

The reads are through the log rather than through a tap because what is
claimed is about a record's fields, which is what a deployment keeps.
"""

import asyncio
from dataclasses import replace
from typing import Any, cast

import pytest

from tests.support.configs import BOTH_MAC, POET_MAC, base_config
from tests.support.events import events, only
from tests.support.providers import (
    EARS,
    OTHER_EARS,
    VOICE,
    IdentifiedAsr,
    IdentifiedTts,
    ScriptedEndpointer,
    built_world,
)
from tests.support.sessions import (
    agent_providers,
    device_session,
    drive_reply,
    end_utterance,
    events_of,
    hand_over_to,
    listening_in_realtime,
    plant_utterance,
    start_reply,
    turn_taking,
    wait_for_reply,
    with_device,
)
from tests.support.sockets import RecordingSocket
from tests.support.wire import speech_pcm
from vinga_server.config import Config
from vinga_server.providers.mock import MockAsr, MockTts

# The utterance a driven reply is handed: 20 ms of silence, which the
# mock ears answer whatever they hold.
UTTERANCE = b"\x00\x00" * 320

ASR_QUARTET = ("ears", "whisperish", "ears.example.com", "tiny-en-3")
TTS_QUARTET = ("voice", "speakish", "voice.example.com", "baritone-2")


def quartet(record: Any) -> tuple[Any, ...]:
    """The four entry names one record carries, in the order the
    declarations put them in, with None where the record carries no such
    field at all.

    Absence rather than emptiness is the answer these events give, so
    the read has to be able to tell "no key" apart from "a key holding
    nothing", which is what `getattr` with a default does and a
    subscript does not.
    """
    return tuple(getattr(record, name, None) for name in ("provider", "type", "host", "model"))


def labelled(asr: Any, tts: Any, config: Config | None = None) -> Any:
    """A session whose ears and voice are the entries this test stamped,
    on a socket that lets a reply run all the way through speaking."""
    settings = base_config() if config is None else config
    session = device_session(
        settings,
        POET_MAC,
        agent_providers(settings, None, {"asr": asr, "tts": tts}),
        websocket=cast(Any, RecordingSocket()),
    )
    return with_device(session, POET_MAC)


async def a_labelled_reply(
    caplog: pytest.LogCaptureFixture, asr: Any = None, tts: Any = None
) -> Any:
    """One whole reply against the stamped entries, at DEBUG, since
    `sentence_synthesized` is a DEBUG event and a run at the default
    level would prove nothing about it."""
    session = labelled(
        IdentifiedAsr(EARS) if asr is None else asr,
        IdentifiedTts(VOICE) if tts is None else tts,
    )
    with caplog.at_level("DEBUG"):
        await drive_reply(session, UTTERANCE)
    return session


# --- what each record names -------------------------------------------


async def test_heard_names_the_entry_that_transcribed_and_no_other(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """By value and in order, so `provider` holding the type or `type`
    holding the entry name is a failure. And nothing of the voice is on
    it: the two stages ran in the same reply, so a builder handed the
    wrong object in scope would still produce four well-formed names."""
    await a_labelled_reply(caplog)

    heard = only(caplog, "heard")
    assert quartet(heard) == ASR_QUARTET
    assert not any(name in str(vars(heard)) for name in TTS_QUARTET)


async def test_sentence_synthesized_names_the_entry_that_spoke_and_no_other(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The same claim from the other side of the reply. The voice is the
    one the synthesis ran through, which is the one a failure on that
    stream would be reported against, so both halves of the TTS stage
    name one entry."""
    await a_labelled_reply(caplog)

    spoken = only(caplog, "sentence_synthesized")
    assert quartet(spoken) == TTS_QUARTET
    assert not any(name in str(vars(spoken)) for name in ASR_QUARTET)


# --- the two absences a real deployment produces ----------------------


async def test_an_engine_running_in_this_process_names_no_host(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`host` absent on its own, which is what a local engine leaves: it
    reaches no host, and the entry, its type and its model are all still
    named. Absent rather than null, so the record carries no key at
    all."""
    await a_labelled_reply(caplog, asr=IdentifiedAsr(replace(EARS, host=None)))

    heard = only(caplog, "heard")
    assert quartet(heard) == ("ears", "whisperish", None, "tiny-en-3")
    assert not hasattr(heard, "host")


async def test_a_type_with_no_model_to_name_carries_none(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`model` absent on its own, at the other stage and in the other
    position, which is what a voice whose type names no model leaves."""
    await a_labelled_reply(caplog, tts=IdentifiedTts(replace(VOICE, model=None)))

    spoken = only(caplog, "sentence_synthesized")
    assert quartet(spoken) == ("voice", "speakish", "voice.example.com", None)
    assert not hasattr(spoken, "model")


# --- the quartet is atomic --------------------------------------------


async def test_ears_the_registry_never_built_label_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Four absences, never an entry name with no type beside it. The
    voice in the same reply still names its own entry, so what is being
    shown is a fact about one provider rather than about the run."""
    await a_labelled_reply(caplog, asr=MockAsr(text="hello there"))

    heard = only(caplog, "heard")
    assert quartet(heard) == (None, None, None, None)
    # And the event still answers what it exists for.
    assert heard.duration_s == 0.02  # type: ignore[attr-defined]
    assert quartet(only(caplog, "sentence_synthesized")) == TTS_QUARTET


async def test_a_voice_the_registry_never_built_labels_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The same rule at the TTS stage."""
    await a_labelled_reply(
        caplog, tts=MockTts(sample_rate=24000, ms_per_char=1.0, min_ms=60.0)
    )

    spoken = only(caplog, "sentence_synthesized")
    assert quartet(spoken) == (None, None, None, None)
    assert isinstance(spoken.stream_ms, int)  # type: ignore[attr-defined]
    assert quartet(only(caplog, "heard")) == ASR_QUARTET


# --- and neither sentence moved ---------------------------------------


async def test_neither_sentence_moved(caplog: pytest.LogCaptureFixture) -> None:
    """The four names are carried payload and no TEMPLATE or ARGS gained
    a position, which is the whole reason this change is cheap to
    review. Asserted on the unrendered message and on the typed
    arguments, because a rendered line would pass while an argument list
    grew a fifth entry nothing printed."""
    session = await a_labelled_reply(caplog)
    said = events_of(session).session_id

    heard = only(caplog, "heard")
    assert heard.msg == "session %s: heard %.2f s of speech"
    assert heard.args == (said, 0.02)

    spoken = only(caplog, "sentence_synthesized")
    assert spoken.msg == "session %s: sentence %d synthesized in %d ms"
    assert spoken.args is not None
    where, index, stream_ms = spoken.args
    assert (where, index) == (said, 0)
    assert isinstance(stream_ms, int)


# --- the race a handover opens ----------------------------------------


def two_eared(config: Config, poet_ears: Any, tutor_ears: Any) -> tuple[Any, Any]:
    """A session whose two agents hear through different entries, so
    which one a record names is a fact and not a coincidence.

    Built rather than substituted through a stage, because `stages`
    replaces one stage for EVERY agent and the whole of this scenario is
    the two agents differing.
    """
    world = built_world(config)
    agents = dict(world.agents)
    agents["poet"] = replace(agents["poet"], asr=poet_ears)
    agents["tutor"] = replace(agents["tutor"], asr=tutor_ears)
    socket = RecordingSocket()
    session = device_session(
        config,
        BOTH_MAC,
        replace(world, agents=agents),
        websocket=cast(Any, socket),
    )
    listening_in_realtime(session)
    return with_device(session, BOTH_MAC), socket


async def test_a_reused_transcription_names_the_ear_that_ran_it(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The race, driven rather than reasoned about.

    A reply is speaking when the user cuts in. The gate transcribes to
    decide the cancel, and that call is held open inside the ear while
    the session hands the conversation over, which is the one write to
    the session's providers. The gate then confirms, the reply in flight
    is cancelled, and the reply that answers reuses the transcription.

    Its `heard` reports what that confirmation cost, so it has to report
    the ear that ran the confirmation. The tutor is answering by then,
    which the record itself says, and the tutor's ears transcribed
    nothing at all: they are asserted never to have been called, so a
    record naming them could only be naming the current binding.
    """
    poet_ears = IdentifiedAsr(EARS, text="stop and listen", hold_from=2)
    tutor_ears = IdentifiedAsr(OTHER_EARS)
    config = base_config()
    session, socket = two_eared(config, poet_ears, tutor_ears)

    with caplog.at_level("DEBUG"):
        turn_taking(session).endpointer = ScriptedEndpointer(speech_ms=600)
        start_reply(session, speech_pcm(600), speech_ms=600)
        while socket.frames < 3:
            await asyncio.sleep(0.02)
        # The interruption, ended in a task: the gate is about to spend
        # a whole ASR call and this test is what releases it.
        plant_utterance(session, speech_pcm(600))
        ending = asyncio.create_task(end_utterance(session))
        await asyncio.wait_for(poet_ears.started.wait(), 5.0)
        hand_over_to(session, "tutor")
        poet_ears.release.set()
        await ending
        await wait_for_reply(session)

    heard = events(caplog, "heard")
    assert len(heard) == 2, "the interrupted reply and the one that answered"
    reused = heard[-1]
    # The rebinding really landed: the tutor is the agent answering.
    assert reused.agent == "tutor"  # type: ignore[attr-defined]
    # And the quartet names the ear that transcribed, not the one bound.
    assert quartet(reused) == ASR_QUARTET
    assert reused.asr_ms >= 0  # type: ignore[attr-defined]
    assert tutor_ears.calls == 0, "the tutor's ears never transcribed anything"
