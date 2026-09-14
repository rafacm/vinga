"""The LLM input exporter: what it refuses, what it holds, what it
drops and what it says.

The widest content surface in this server, so this file is written the
way the transcript exporter's is and then further: what a default
deployment gets is nothing at all, every refusal is a fixed sentence
with no value and no chain, and the content that genuinely passes
through is hunted through both log formats, both events' payloads, every
emission an attached tap receives and every exception chain.

One seam is faked, the module's own: the telemetry the spans go through.
Nothing else is. The stage is the real one, the byte bound is the real
one, the drop accounting is the real one, the queue is the real bounded
one, the worker is the real daemon thread, and the rendering is the real
canonical JSON that would actually be exported.

The sentinel section is two claims, and the first is the INVERSE of the
usual one. What this surface is authorized to send is the whole
assembled prompt, tool arguments and results included, so the planted
credential-shaped value MUST reach the span writer; what it must not do
is appear in a log line, an event payload, an emission or an exception
chain on the way, and with the flag off it must not be assembled at all.
"""

import asyncio
import gc
import json
import logging
import threading
import time
import weakref
from typing import Any

import pytest

from tests.support.events import both_formats, fields_of
from tests.support.llm_input import A_CONTEXT, Exported, a_tool, a_turn, exporting
from vinga_server.boundary import Reach
from vinga_server.config import ConfigError
from vinga_server.config.models import ServerConfig
from vinga_server.events import (
    Emission,
    EventTap,
    attach_server_tap,
    detach_server_tap,
)
from vinga_server.events.values import LlmInputExportFailure
from vinga_server.llm_input_export import (
    LLM_INPUT_KEY,
    LLM_INPUT_NEEDS_TELEMETRY,
    POLL_S,
    LlmInputExport,
    build_llm_input_export,
)
from vinga_server.providers.base import ToolCall, ToolResult
from vinga_server.telemetry import Delivery

SESSION = "0123456789abcdef0123456789abcdef"

# What this surface IS authorized to send, planted in each half of a
# request that genuinely carries it. Credential-shaped on purpose,
# because the whole assembled prompt is what travels here: these are the
# shape of thing an operator would most regret finding somewhere else.
SYSTEM_SENTINEL = "system-sk-live-0LLMINPUT-SENTINEL"
HISTORY_SENTINEL = "history-sk-live-0LLMINPUT-SENTINEL"
ARGUMENTS_SENTINEL = "arguments-sk-live-0LLMINPUT-SENTINEL"
RESULT_SENTINEL = "result-sk-live-0LLMINPUT-SENTINEL"
SCHEMA_SENTINEL = "schema-sk-live-0LLMINPUT-SENTINEL"

SENTINELS = (
    SYSTEM_SENTINEL,
    HISTORY_SENTINEL,
    ARGUMENTS_SENTINEL,
    RESULT_SENTINEL,
    SCHEMA_SENTINEL,
)


def a_server(**server: Any) -> ServerConfig:
    """One server section, with telemetry and the export on unless a
    case says otherwise."""
    return ServerConfig.model_validate(
        {"telemetry": {"enabled": True, "export_llm_input": True}, **server}
    )


def an_exporter(
    *,
    contexts: dict[str, Any] | None = None,
    telemetry: Any = None,
    backlog: int = 8,
    **options: Any,
) -> tuple[LlmInputExport, Exported]:
    """An exporter over its one faked seam, with the real everything
    else."""
    held, recorded = (
        (telemetry, telemetry)
        if telemetry is not None
        else exporting(contexts if contexts is not None else {SESSION: A_CONTEXT})
    )
    exporter = LlmInputExport(
        telemetry=held,
        backlog=backlog,
        shutdown_timeout_s=options.pop("shutdown_timeout_s", 10.0),
        **options,
    )
    return exporter, recorded


def stage(
    exporter: LlmInputExport,
    session: str = SESSION,
    *,
    recap: bool = False,
    agent: str | None = "alpha",
    system: str = "You are a household assistant.",
    turns: Any = None,
    tools: Any = None,
    choice: str = "auto",
    invocation: str = "0123456789abcdef0123456789abcdef",
) -> None:
    """One round staged through whichever of the two verbs a case is
    about."""
    verb = exporter.stage_recap if recap else exporter.stage_reply
    verb(
        session,
        invocation=invocation,
        agent=agent,
        system=system,
        turns=[a_turn()] if turns is None else turns,
        tools=[] if tools is None else tools,
        choice=choice,
    )


async def drained(
    exporter: LlmInputExport,
    ready: Any = None,
    complaint: str = "the worker never finished its job",
) -> None:
    """Wait for the work a case is about, then stop the worker.

    The wait is not politeness. A shutdown INTERRUPTS this exporter:
    anything still queued when the stop flag goes up is dropped with its
    event, which is the contract. So a case that shut down without
    waiting would be driving the drop path every time, whatever it meant
    to drive.

    A case whose claim is that NOTHING happens passes no signal and gets
    a moment the worker could have used instead.
    """
    if ready is None:
        await asyncio.sleep(0.25)
    else:
        deadline = time.monotonic() + 10.0
        while not ready():
            assert time.monotonic() < deadline, complaint
            await asyncio.sleep(0.01)
    await exporter.shutdown()


class Unrenderable:
    """A value no rendering can make sense of, which is what a defect in
    this server looks like from the stage's side.

    `default=str` is the rendering's totality clause, so what defeats it
    has to defeat `str()` too. Deliberately not a value the provider
    seam can actually carry: the reachable hostile value is the lone
    surrogate above, and this one stands in for the class of bug the
    third count exists to make visible.
    """

    def __str__(self) -> str:
        raise RuntimeError(f"nothing about this is printable: {RESULT_SENTINEL}")

    __repr__ = __str__


def held_rounds(exporter: LlmInputExport, session: str = SESSION) -> list[Any]:
    """What one session is holding right now, read the way the wiring
    suite reads it: the claim in this section is about a call that had
    to RETURN, so there is no close to read it through."""
    stage = exporter._staged.get(session)  # noqa: SLF001
    return [] if stage is None else [one.round for one in stage.rounds]


def reasons(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Every failure reason this run reported, in order."""
    return [
        str(fields_of(record)["reason"])
        for record in caplog.records
        if getattr(record, "event", None) == "llm_input_export_failed"
    ]


def exports(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "llm_input_exported"
    ]


def only_export(caplog: pytest.LogCaptureFixture) -> dict[str, object]:
    """The one export event this run produced, as its structured
    fields."""
    (record,) = exports(caplog)
    return fields_of(record)


# --- nothing at all ----------------------------------------------------


def test_no_telemetry_section_builds_nothing() -> None:
    """The default, and it costs a server nothing: no object, no thread,
    no callback, and above all no render."""
    assert build_llm_input_export(a_server(telemetry=None), telemetry=None) is None


def test_the_flag_off_builds_nothing() -> None:
    """Telemetry on and this export off is the ordinary traced
    deployment, and it must not acquire the widest content surface here
    by being traced."""
    held, _ = exporting()

    assert (
        build_llm_input_export(
            a_server(telemetry={"enabled": True}), telemetry=held
        )
        is None
    )


def test_the_sibling_exports_do_not_imply_this_one() -> None:
    """The family rule's last clause: a class implies nothing about its
    siblings, in either direction. A deployment already sending what was
    said must not start sending what the model was given because it
    upgraded."""
    held, _ = exporting()
    config = a_server(
        conversations={"enabled": True, "text": True},
        telemetry={
            "enabled": True,
            "export_audio": True,
            "export_transcripts": True,
        },
    )

    assert build_llm_input_export(config, telemetry=held) is None


def test_the_flag_on_with_telemetry_off_is_refused() -> None:
    """An observation is written onto a trace this server exported, so
    there is nothing to write onto. A fixed sentence naming the two keys
    and the two ways out, and no value of any kind."""
    config = a_server(telemetry={"enabled": False, "export_llm_input": True})

    with pytest.raises(ConfigError) as refusal:
        build_llm_input_export(config, telemetry=None)

    assert str(refusal.value) == LLM_INPUT_NEEDS_TELEMETRY
    assert refusal.value.__cause__ is None
    assert refusal.value.__context__ is None


@pytest.mark.parametrize(
    ("reach", "boundary"),
    [
        pytest.param(Reach.INTERNET, Reach.HOST, id="internet under host"),
        pytest.param(Reach.INTERNET, Reach.NETWORK, id="internet under network"),
        pytest.param(Reach.NETWORK, Reach.HOST, id="network under host"),
    ],
)
def test_a_narrower_boundary_refuses_before_anything_is_built(
    reach: Reach, boundary: Reach
) -> None:
    """Asked before any construction and any thread, which is the only
    way the refusal can honestly say nothing was built. The sentence
    names the switch, the reach, the boundary and the key the reach came
    from, and nothing about an endpoint."""
    held, _ = exporting()
    config = a_server(
        telemetry={"enabled": True, "export_llm_input": True, "reach": reach}
    )

    with pytest.raises(ConfigError) as refusal:
        build_llm_input_export(config, telemetry=held, boundary=boundary)

    said = str(refusal.value)
    assert LLM_INPUT_KEY in said
    assert "server.telemetry.reach" in said
    assert str(boundary) in said


@pytest.mark.parametrize(
    ("reach", "boundary"),
    [
        pytest.param(Reach.HOST, Reach.HOST, id="host under host"),
        pytest.param(Reach.NETWORK, Reach.NETWORK, id="network under network"),
        pytest.param(Reach.HOST, Reach.INTERNET, id="host under internet"),
    ],
)
def test_a_declared_reach_inside_the_boundary_is_admitted(
    reach: Reach, boundary: Reach
) -> None:
    """The key M4b added, doing for this export what it does for the
    three beside it: a collector the operator says is near enough is
    near enough."""
    held, _ = exporting()
    config = a_server(
        telemetry={"enabled": True, "export_llm_input": True, "reach": reach}
    )

    assert build_llm_input_export(config, telemetry=held, boundary=boundary) is not None


def test_no_second_switch_can_make_it_a_no_op() -> None:
    """The one place this builder differs from both of its siblings.
    The family rule's no-op arm applies where a class has a local
    surface with a switch of its own; this class has none, so recording
    nothing and capturing nothing leave it building normally rather than
    answering None."""
    held, _ = exporting()
    config = a_server(conversations=None, capture=None)

    assert build_llm_input_export(config, telemetry=held) is not None


# --- what one session stages ------------------------------------------


@pytest.mark.asyncio
async def test_an_ordinary_single_round_reply_is_one_observation() -> None:
    """The ordinary path, and the unit the whole surface counts in: one
    logical round is one observation."""
    exporter, telemetry = an_exporter()
    stage(exporter)

    exporter.session_closed(SESSION)
    await drained(exporter, lambda: telemetry.jobs)

    (one,) = telemetry.rounds
    assert one.index == 1
    assert one.purpose == "reply"
    assert one.agent == "alpha"


@pytest.mark.asyncio
async def test_a_reply_with_tool_follow_up_rounds_is_one_observation_each() -> None:
    """A tool loop is several requests inside one turn, and each of them
    is a thing the model was given: what a reader asking "what did it
    see" wants is all of them, in the order they were assembled."""
    exporter, telemetry = an_exporter()
    for _ in range(3):
        stage(exporter)

    exporter.session_closed(SESSION)
    await drained(exporter, lambda: telemetry.jobs)

    assert [one.index for one in telemetry.rounds] == [1, 2, 3]


@pytest.mark.asyncio
async def test_a_recap_round_is_staged_and_says_which_it_is() -> None:
    """The second call shape, which a reader wants for the same reason
    and has to be able to tell apart: a summarization nobody is
    listening to yet is not an answer to anybody."""
    exporter, telemetry = an_exporter()
    stage(exporter, recap=True)
    stage(exporter)

    exporter.session_closed(SESSION)
    await drained(exporter, lambda: telemetry.jobs)

    assert [one.purpose for one in telemetry.rounds] == ["recap", "reply"]


@pytest.mark.asyncio
async def test_a_round_staged_once_is_one_observation_however_often_it_is_sent() -> None:
    """The finding this milestone turns into a rule. The first-token
    watchdog re-sends content fixed before the first attempt, so staging
    sits where a round is ASSEMBLED and not where it is sent; a case
    that staged per attempt would put the same bytes on the trace twice
    and claim the model was given two things.

    Driven as the pipeline drives it: one assembly, and whatever
    happened to it afterwards is not this surface's business.
    """
    exporter, telemetry = an_exporter()
    stage(exporter)

    exporter.session_closed(SESSION)
    await drained(exporter, lambda: telemetry.jobs)

    assert len(telemetry.rounds) == 1
    assert [one.index for one in telemetry.rounds] == [1]


@pytest.mark.asyncio
async def test_a_round_whose_provider_failed_is_still_staged() -> None:
    """The model was given it whatever came back, which is the whole
    claim of this class: an operator diagnosing a failed round is
    exactly the reader who needs to see what was sent.

    Staging happens before the call, so nothing about the call's outcome
    reaches this module at all; the case drives the shape and asserts
    the absence of any second opinion.
    """
    exporter, telemetry = an_exporter()
    stage(exporter)

    exporter.session_closed(SESSION)
    await drained(exporter, lambda: telemetry.jobs)

    assert len(telemetry.rounds) == 1


@pytest.mark.asyncio
async def test_two_sessions_stage_separately() -> None:
    """The stage is per session, so a busy server's conversations cannot
    read each other's prompts into one export."""
    other = "ffffffffffffffffffffffffffffffff"
    exporter, telemetry = an_exporter(
        contexts={SESSION: A_CONTEXT, other: "another-context"}
    )
    stage(exporter, SESSION, system="the first session")
    stage(exporter, other, system="the second session")

    exporter.session_closed(SESSION)
    await drained(exporter, lambda: telemetry.jobs)

    (session, _, rounds) = telemetry.jobs[0]
    assert session == SESSION
    assert len(rounds) == 1
    assert "the first session" in rounds[0].request
    assert "the second session" not in rounds[0].request


@pytest.mark.asyncio
async def test_the_stage_is_dropped_at_the_close_whatever_happened(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The retention answer made mechanical: the pop is unconditional
    and comes first, so a session that exported cleanly and one with no
    trace at all each leave exactly nothing behind.

    A second close is what makes the claim falsifiable, because it is
    the only way to ask from outside whether anything is still held: the
    stage is private and the module's whole promise about it is that it
    is gone. A held stage answers the second close as well as the first,
    which is one export too many for the clean session and one failure
    too many for the traceless one.
    """
    caplog.set_level(logging.DEBUG)
    exporter, telemetry = an_exporter()
    stage(exporter)
    exporter.session_closed(SESSION)
    await drained(exporter, lambda: telemetry.jobs)

    exporter.session_closed(SESSION)
    await asyncio.sleep(0.1)

    assert len(telemetry.jobs) == 1, "the close left the stage behind"
    assert len(exports(caplog)) == 1
    assert reasons(caplog) == []


@pytest.mark.asyncio
async def test_a_session_with_no_trace_leaves_nothing_behind_either(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The same claim on the path that reports a failure, which is the
    one where forgetting the pop would be worst: a session whose trace
    had aged out would go on holding the whole of what its model saw,
    for the life of the process."""
    caplog.set_level(logging.DEBUG)
    exporter, telemetry = an_exporter(contexts={})
    stage(exporter)
    exporter.session_closed(SESSION)

    exporter.session_closed(SESSION)
    await drained(exporter)

    assert telemetry.jobs == []
    assert reasons(caplog) == [LlmInputExportFailure.NO_TRACE]


@pytest.mark.asyncio
async def test_a_session_that_staged_nothing_says_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Every connection refused before it spoke, which is most of what a
    busy server's close path sees: there is no export to report and no
    absence worth a line."""
    caplog.set_level(logging.DEBUG)
    exporter, telemetry = an_exporter()

    exporter.session_closed(SESSION)
    await drained(exporter)

    assert telemetry.jobs == []
    assert exports(caplog) == []
    assert reasons(caplog) == []


# --- what the worker keeps between jobs --------------------------------


class Forgetful(Exported):
    """A seam that keeps a WEAK reference to what crossed it and no
    strong one.

    The only way to ask from outside whether the worker let go. The
    recorder above deliberately keeps every round it was handed, which
    is what makes every other claim in this file assertable and what
    makes this one unaskable through it: a job the worker had released
    would still be alive because the recorder was holding it.
    """

    def __init__(self, contexts: dict[str, Any] | None = None) -> None:
        super().__init__(contexts)
        self.witness: weakref.ref[Any] | None = None
        self.delivered = threading.Event()

    def export_llm_input(self, session: str, context: Any, rounds: Any) -> Delivery:
        held = list(rounds)
        self.witness = weakref.ref(held[0])
        self.delivered.set()
        # Deliberately NOT `super()`, which would keep the rounds: this
        # seam is the one place a strong reference would defeat the
        # question being asked.
        return Delivery.DELIVERED


@pytest.mark.asyncio
async def test_an_idle_worker_holds_no_part_of_the_last_export() -> None:
    """The retention boundary, driven rather than described.

    "For the session, then in a bounded delivery job until it is
    delivered or dropped, and nowhere after that" is the strictest
    retention answer in this repository and the reason this class was
    allowed to exist with no store behind it. A worker that left its
    last job bound while it sat in its next poll would hold the whole of
    what a model saw for as long as the server stayed quiet, which is
    exactly the case an idle household produces.

    Asked through a weak reference, because the claim is about what is
    NOT held and there is nothing to read: the export is waited for, the
    worker is given a moment to return to polling, and what the model
    saw has to be collectible with the worker still alive and still
    idle.
    """
    telemetry = Forgetful({SESSION: A_CONTEXT})
    exporter, _ = an_exporter(telemetry=telemetry)
    stage(exporter)

    exporter.session_closed(SESSION)
    assert telemetry.delivered.wait(10.0), "the worker never took the job"
    # Long enough for the attempt to return and the next `get` to time
    # out at least once, which is the moment a leaked binding would
    # still be holding.
    await asyncio.sleep(POLL_S * 4)
    gc.collect()

    assert telemetry.witness is not None
    assert telemetry.witness() is None, (
        "the idle worker is still holding the last session's assembled request"
    )
    await exporter.shutdown()


# --- the bound ---------------------------------------------------------


@pytest.mark.asyncio
async def test_a_request_over_the_ceiling_is_dropped_whole_and_counted(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Dropped rather than truncated, which is the plan's own decision
    and this class's reason for existing: a shortened request is not the
    request the model was given, so an approximate item is worse than a
    missing one."""
    caplog.set_level(logging.INFO)
    exporter, telemetry = an_exporter(max_request_bytes=512)
    stage(exporter, system="a")
    stage(exporter, system="x" * 4096)
    stage(exporter, system="b")

    exporter.session_closed(SESSION)
    await drained(exporter, lambda: telemetry.jobs)

    assert [one.index for one in telemetry.rounds] == [1, 3]
    said = only_export(caplog)
    assert said["rounds"] == 2
    assert said["oversized"] == 1
    assert said["over_budget"] == 0


@pytest.mark.asyncio
async def test_a_session_over_its_budget_drops_oldest_first_and_counts(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Whole requests, oldest first, which is the posture the retentions
    in `telemetry.py` already take: what a reader wants from a session
    that outgrew its budget is the end of the conversation rather than
    the beginning of it."""
    caplog.set_level(logging.INFO)
    exporter, telemetry = an_exporter(
        max_request_bytes=4096, session_budget_bytes=2048
    )
    for index in range(6):
        stage(exporter, system=f"{index}" * 700)

    exporter.session_closed(SESSION)
    await drained(exporter, lambda: telemetry.jobs)

    kept = [one.index for one in telemetry.rounds]
    assert kept, "the budget dropped everything"
    assert kept == sorted(kept)
    assert kept[-1] == 6, "the newest round was dropped rather than the oldest"
    said = only_export(caplog)
    assert said["rounds"] == len(kept)
    assert said["oversized"] == 0
    assert said["over_budget"] == 6 - len(kept)


@pytest.mark.asyncio
async def test_more_rounds_than_the_entry_cap_drop_oldest_first_too(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The cheap guard behind the byte budget, and it reports the same
    reason because it is the same bound's entry half: a session that
    held more rounds than it may is a session that held more than its
    budget allows for."""
    caplog.set_level(logging.INFO)
    exporter, telemetry = an_exporter(max_rounds=3)
    for _ in range(5):
        stage(exporter)

    exporter.session_closed(SESSION)
    await drained(exporter, lambda: telemetry.jobs)

    assert [one.index for one in telemetry.rounds] == [3, 4, 5]
    said = only_export(caplog)
    assert said["rounds"] == 3
    assert said["oversized"] == 0
    assert said["over_budget"] == 2


@pytest.mark.asyncio
async def test_the_two_drop_reasons_are_told_apart_on_one_event(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The reason the event carries two counts rather than one. They
    mean different things to whoever is reading: one request was too
    large to carry, or the conversation outgrew what may be held for
    it."""
    caplog.set_level(logging.INFO)
    exporter, telemetry = an_exporter(
        max_request_bytes=2048, session_budget_bytes=3072
    )
    stage(exporter, system="x" * 4096)
    for index in range(4):
        stage(exporter, system=f"{index}" * 1000)

    exporter.session_closed(SESSION)
    await drained(exporter, lambda: telemetry.jobs)

    said = only_export(caplog)
    assert said["oversized"] == 1
    assert said["over_budget"] >= 1
    assert said["rounds"] == len(telemetry.rounds)


@pytest.mark.asyncio
async def test_the_ordinal_counts_every_round_the_session_assembled(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Which is what makes a partial export legible on the trace as well
    as in the event: a reader looking at rounds 1, 2 and 5 can see that
    two are missing without counting anything."""
    caplog.set_level(logging.INFO)
    exporter, telemetry = an_exporter(max_request_bytes=512)
    stage(exporter, system="a")
    stage(exporter, system="b")
    stage(exporter, system="x" * 4096)
    stage(exporter, system="y" * 4096)
    stage(exporter, system="c")

    exporter.session_closed(SESSION)
    await drained(exporter, lambda: telemetry.jobs)

    assert [one.index for one in telemetry.rounds] == [1, 2, 5]


@pytest.mark.asyncio
async def test_a_session_whose_every_round_was_dropped_still_says_so(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The absence is the whole of what a reader would otherwise have to
    guess at, so it is reported with no rounds rather than passed over
    as silence."""
    caplog.set_level(logging.INFO)
    exporter, telemetry = an_exporter(max_request_bytes=64)
    stage(exporter, system="x" * 4096)

    exporter.session_closed(SESSION)
    await drained(exporter, lambda: exports(caplog))

    said = only_export(caplog)
    assert said["rounds"] == 0
    assert said["oversized"] == 1
    assert telemetry.jobs == [(SESSION, A_CONTEXT, [])]


# --- what the far side can put in a round ------------------------------
#
# A lone surrogate is reachable from outside this process: Python's JSON
# decoder accepts a `\udXXX` escape, so an MCP server's tool result can
# carry one, and a tool result is staged content. It is not encodable as
# UTF-8, which makes it the one hostile value that can reach the
# rendering and the one this section exists for.

LONE_SURROGATE = json.loads(r'"a \ud800 b"')


@pytest.mark.asyncio
async def test_a_lone_surrogate_in_a_tool_result_never_reaches_the_caller() -> None:
    """The standing posture of every surface on this ladder: **no
    content export may fail a conversation.**

    Staging runs on the reply path, before the provider call, so a
    rendering that raised would take the reply with it. The value comes
    in the way a real one would, as a tool result, and the assertion is
    that the call returns at all.
    """
    exporter, _ = an_exporter()

    stage(
        exporter,
        turns=[
            a_turn(
                role="tool",
                content="",
                results=(ToolResult(tool_call_id="c1", content=LONE_SURROGATE),),
            )
        ],
    )

    assert held_rounds(exporter), "the round vanished rather than being staged"


@pytest.mark.asyncio
async def test_a_lone_surrogate_rides_out_as_a_json_escape() -> None:
    """And it is not lost either, which is the second half of the same
    claim: what cannot be spelled as UTF-8 can be spelled as the JSON
    escape the far side sent, so the round is exported exactly rather
    than dropped for being awkward.
    """
    exporter, telemetry = an_exporter()
    stage(
        exporter,
        turns=[
            a_turn(
                role="tool",
                content="",
                results=(ToolResult(tool_call_id="c1", content=LONE_SURROGATE),),
            )
        ],
    )

    exporter.session_closed(SESSION)
    await drained(exporter, lambda: telemetry.jobs)

    (one,) = telemetry.rounds
    assert "\\ud800" in one.request, "the surrogate was not escaped into the request"
    assert one.request.encode("utf-8"), "the request is still not encodable"
    assert json.loads(one.request)["messages"][0]["tool_results"][0]["content"] == (
        LONE_SURROGATE
    )


@pytest.mark.asyncio
async def test_a_round_this_server_could_not_render_is_counted(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The third absence, which is a defect in this server rather than a
    conversation that outgrew its budget.

    It gets a count of its own rather than being folded into either
    bound's, because those two are the bound's vocabulary and mean
    something exact to whoever is reading: reporting a ceiling that was
    never reached would send an operator to tune a number that had
    nothing to do with it. What it may NOT be is invisible, which is
    what the plan's exhaustive accounting exists to prevent.
    """
    caplog.set_level(logging.INFO)
    exporter, telemetry = an_exporter()
    stage(exporter)
    stage(exporter, turns=[a_turn(content=Unrenderable())])
    stage(exporter)

    exporter.session_closed(SESSION)
    await drained(exporter, lambda: telemetry.jobs)

    assert [one.index for one in telemetry.rounds] == [1, 3]
    said = only_export(caplog)
    assert said["rounds"] == 2
    assert said["unrenderable"] == 1
    assert said["oversized"] == 0
    assert said["over_budget"] == 0


@pytest.mark.asyncio
async def test_a_session_whose_only_round_was_unrenderable_still_says_so(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The close's own half of the same rule. A session whose every
    round vanished used to emit no outcome event at all, so the absence
    was not merely unexplained: it was unreported."""
    caplog.set_level(logging.INFO)
    exporter, telemetry = an_exporter()
    stage(exporter, turns=[a_turn(content=Unrenderable())])

    exporter.session_closed(SESSION)
    await drained(exporter, lambda: exports(caplog))

    said = only_export(caplog)
    assert said["rounds"] == 0
    assert said["unrenderable"] == 1
    assert telemetry.jobs == [(SESSION, A_CONTEXT, [])]


@pytest.mark.asyncio
async def test_nothing_of_an_unrenderable_round_is_said_out_loud(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The value-free rule holds on the one path that has a value in
    hand and no way to render it: the line names the count and the
    consequence, and nothing it was carrying."""
    caplog.set_level(logging.DEBUG)
    exporter, _ = an_exporter()

    stage(exporter, system=SYSTEM_SENTINEL, turns=[a_turn(content=Unrenderable())])

    written = both_formats(caplog)
    assert "could not be rendered" in written
    assert SYSTEM_SENTINEL not in written
    assert RESULT_SENTINEL not in written


# --- what the rendering contains ---------------------------------------


async def rendered(exporter: LlmInputExport, telemetry: Exported) -> dict[str, Any]:
    """One staged round's request, parsed back.

    Parsed rather than matched as a string, because what these cases are
    about is which facts crossed rather than how they are spelled; the
    spelling has its own case below.
    """
    exporter.session_closed(SESSION)
    await drained(exporter, lambda: telemetry.jobs)
    (one,) = telemetry.rounds
    return json.loads(one.request)


@pytest.mark.asyncio
async def test_the_request_carries_the_four_arguments_the_provider_was_given() -> None:
    """The fidelity boundary, pinned as data: the system prompt, the
    history, the tool schemas and the tool choice, which is the
    enumeration the issue itself settles."""
    exporter, telemetry = an_exporter()
    stage(
        exporter,
        system="You are a household assistant.",
        turns=[a_turn(content="turn the light on")],
        tools=[a_tool()],
        choice="auto",
    )

    request = await rendered(exporter, telemetry)

    assert request["system"] == "You are a household assistant."
    assert request["messages"] == [
        {"role": "user", "content": "turn the light on"}
    ]
    assert request["tools"][0]["name"] == "remember"
    assert request["tools"][0]["input_schema"]["type"] == "object"
    assert request["tool_choice"] == "auto"


@pytest.mark.asyncio
async def test_the_request_carries_nothing_the_model_was_not_handed() -> None:
    """Four keys and not five. Which call shape assembled a round is
    vinga's own label, so it rides the span as an attribute and stays
    out of the request: a class whose value is that it is exactly what
    was sent must not quietly grow a field the model never saw."""
    exporter, telemetry = an_exporter()
    stage(exporter, recap=True)

    request = await rendered(exporter, telemetry)

    assert sorted(request) == ["messages", "system", "tool_choice", "tools"]
    (one,) = telemetry.rounds
    assert one.purpose == "recap", "the label is gone rather than moved"


@pytest.mark.asyncio
async def test_the_tool_arguments_and_results_are_in_it() -> None:
    """The half a transcript deliberately does not carry, and the half
    that makes this class a superset of that one: what the model asked
    for and what it was handed back are part of what it saw."""
    exporter, telemetry = an_exporter()
    stage(
        exporter,
        turns=[
            a_turn(
                role="assistant",
                content="Let me check.",
                calls=(ToolCall(id="c1", name="remember", arguments={"fact": "it"}),),
            ),
            a_turn(
                role="tool",
                content="",
                results=(ToolResult(tool_call_id="c1", content="done"),),
            ),
        ],
    )

    request = await rendered(exporter, telemetry)

    assert request["messages"][0]["tool_calls"] == [
        {"id": "c1", "name": "remember", "arguments": {"fact": "it"}}
    ]
    assert request["messages"][1]["tool_results"] == [
        {"tool_call_id": "c1", "content": "done", "is_error": False}
    ]


@pytest.mark.asyncio
async def test_arguments_a_model_mangled_ride_the_field_the_seam_keeps_them_in() -> None:
    """A model that streamed something that is not a JSON object is
    exactly the model an operator opens this surface to diagnose, so the
    raw text it sent is part of what it produced."""
    exporter, telemetry = an_exporter()
    stage(
        exporter,
        turns=[
            a_turn(
                role="assistant",
                content="",
                calls=(
                    ToolCall(
                        id="c1",
                        name="remember",
                        malformed_arguments='{"fact": ',
                    ),
                ),
            )
        ],
    )

    request = await rendered(exporter, telemetry)

    assert request["messages"][0]["tool_calls"][0]["malformed_arguments"] == '{"fact": '


@pytest.mark.asyncio
async def test_an_ordinary_turn_carries_no_empty_tool_arrays() -> None:
    """Every turn of a persistent history has neither half, and an empty
    array on each of them would be bytes against the budget saying
    nothing."""
    exporter, telemetry = an_exporter()
    stage(exporter, turns=[a_turn()])

    request = await rendered(exporter, telemetry)

    assert request["messages"] == [{"role": "user", "content": "turn the light on"}]


@pytest.mark.asyncio
async def test_the_rendering_is_canonical_so_the_same_round_weighs_the_same() -> None:
    """Sorted and unpadded, which is what makes the byte bound a fact
    rather than a reading: the same round renders to the same bytes on
    every run, and the string that was weighed is the string that goes.
    """
    exporter, telemetry = an_exporter()
    stage(exporter, turns=[a_turn()], tools=[])

    exporter.session_closed(SESSION)
    await drained(exporter, lambda: telemetry.jobs)

    (one,) = telemetry.rounds
    assert one.request.startswith('{"messages":')
    assert ", " not in one.request


# --- the failures ------------------------------------------------------


@pytest.mark.asyncio
async def test_a_session_with_no_trace_is_reported_at_admission(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Decided where the session closed rather than where the worker
    reached it, which is what makes `no_trace` an answer about the
    moment it is about."""
    caplog.set_level(logging.DEBUG)
    exporter, telemetry = an_exporter(contexts={})
    stage(exporter)

    exporter.session_closed(SESSION)
    await drained(exporter, lambda: reasons(caplog))

    assert reasons(caplog) == [LlmInputExportFailure.NO_TRACE]
    assert telemetry.jobs == []


@pytest.mark.asyncio
async def test_a_delivery_the_far_side_refuses_is_reported(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    exporter, _ = an_exporter(
        telemetry=Exported({SESSION: A_CONTEXT}, answer=Delivery.UNDELIVERED)
    )
    stage(exporter)

    exporter.session_closed(SESSION)
    await drained(exporter, lambda: reasons(caplog))

    assert reasons(caplog) == [LlmInputExportFailure.UNDELIVERED]


@pytest.mark.asyncio
async def test_a_sampled_away_batch_is_reported_as_no_trace(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A source decision is not described as a refusal by the backend."""
    caplog.set_level(logging.DEBUG)
    exporter, _ = an_exporter(
        telemetry=Exported({SESSION: A_CONTEXT}, answer=Delivery.NO_TRACE)
    )
    stage(exporter)

    exporter.session_closed(SESSION)
    await drained(exporter, lambda: reasons(caplog))

    assert reasons(caplog) == [LlmInputExportFailure.NO_TRACE]


@pytest.mark.asyncio
async def test_a_delivery_that_raises_is_reported_too(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A worker never dies of a job, and what a raising delivery is
    holding is the endpoint and the whole of what a model was given."""
    caplog.set_level(logging.DEBUG)
    exporter, _ = an_exporter(
        telemetry=Exported(
            {SESSION: A_CONTEXT}, raises=RuntimeError(f"https://u:p@h {SYSTEM_SENTINEL}")
        )
    )
    stage(exporter, system=SYSTEM_SENTINEL)

    exporter.session_closed(SESSION)
    await drained(exporter, lambda: reasons(caplog))

    assert reasons(caplog) == [LlmInputExportFailure.UNDELIVERED]
    assert SYSTEM_SENTINEL not in both_formats(caplog)


@pytest.mark.asyncio
async def test_an_exporter_that_has_stopped_is_reported_as_dropped(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Nothing was attempted, so nothing can be said about the backend,
    which is why it is the drop rather than a delivery answer."""
    caplog.set_level(logging.DEBUG)
    exporter, _ = an_exporter(
        telemetry=Exported({SESSION: A_CONTEXT}, answer=Delivery.STOPPED)
    )
    stage(exporter)

    exporter.session_closed(SESSION)
    await drained(exporter, lambda: reasons(caplog))

    assert reasons(caplog) == [LlmInputExportFailure.DROPPED]


@pytest.mark.asyncio
async def test_a_full_backlog_drops_the_job_and_says_so(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The bound is honest about what it cannot promise: a job it turns
    away is dropped WITH its event, which is the drop stated rather than
    hidden."""
    caplog.set_level(logging.DEBUG)
    blocking = asyncio.Event()

    class Slow(Exported):
        def export_llm_input(self, session: str, context: Any, rounds: Any) -> Delivery:
            while not blocking.is_set():
                time.sleep(0.01)
            return super().export_llm_input(session, context, rounds)

    exporter, _ = an_exporter(telemetry=Slow({SESSION: A_CONTEXT}), backlog=1)
    for index in range(6):
        one = f"{index:032x}"
        exporter._telemetry.contexts[one] = A_CONTEXT  # noqa: SLF001
        stage(exporter, one)
        exporter.session_closed(one)

    await drained(exporter, lambda: reasons(caplog))
    blocking.set()

    assert LlmInputExportFailure.DROPPED in reasons(caplog)


@pytest.mark.asyncio
async def test_a_shutdown_answers_everything_still_queued(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The drain, and on this surface it is the whole of what survives:
    nothing is persisted and nothing is left on the host, so a job
    nobody exported is a fact a reader is entitled to."""
    caplog.set_level(logging.DEBUG)
    released = asyncio.Event()

    class Held(Exported):
        def export_llm_input(self, session: str, context: Any, rounds: Any) -> Delivery:
            while not released.is_set():
                time.sleep(0.01)
            return super().export_llm_input(session, context, rounds)

    exporter, _ = an_exporter(telemetry=Held({}), backlog=8)
    for index in range(3):
        one = f"{index:032x}"
        exporter._telemetry.contexts[one] = A_CONTEXT  # noqa: SLF001
        stage(exporter, one)
        exporter.session_closed(one)
    await asyncio.sleep(0.1)

    shutting = asyncio.create_task(exporter.shutdown())
    await asyncio.sleep(0.1)
    released.set()
    await shutting

    assert reasons(caplog).count(LlmInputExportFailure.DROPPED) >= 1


@pytest.mark.asyncio
async def test_a_session_closing_behind_a_shutdown_is_answered(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A drain closes every live session at once, and one arriving after
    the stop flag has no worker to run it: the drop is said rather than
    left as a job nothing will ever answer."""
    caplog.set_level(logging.DEBUG)
    exporter, telemetry = an_exporter()
    await exporter.shutdown()
    stage(exporter)

    exporter.session_closed(SESSION)

    assert reasons(caplog) == [LlmInputExportFailure.DROPPED]
    assert telemetry.jobs == []


@pytest.mark.asyncio
async def test_a_close_never_waits_on_the_worker() -> None:
    """The claim that keeps this off the conversation's own clock: the
    hand-over is a pop, a map read and a queue put, whatever the backend
    is doing."""
    blocking = asyncio.Event()

    class Slow(Exported):
        def export_llm_input(self, session: str, context: Any, rounds: Any) -> Delivery:
            while not blocking.is_set():
                time.sleep(0.01)
            return super().export_llm_input(session, context, rounds)

    exporter, _ = an_exporter(telemetry=Slow({SESSION: A_CONTEXT}))
    stage(exporter)

    began = time.monotonic()
    exporter.session_closed(SESSION)
    elapsed = time.monotonic() - began

    blocking.set()
    await exporter.shutdown()
    assert elapsed < 0.5, "the close waited on the export"


# --- the sentinels -----------------------------------------------------


class Tap:
    """Every emission an attached consumer is offered, which is where a
    leak would go that never reached a log."""

    def __init__(self) -> None:
        self.seen: list[Emission] = []

    def emit(self, emission: Emission) -> None:
        self.seen.append(emission)


def a_planted_round(exporter: LlmInputExport) -> None:
    """One round carrying a credential-shaped value in every
    content-bearing half of an assembled request."""
    stage(
        exporter,
        system=SYSTEM_SENTINEL,
        turns=[
            a_turn(content=HISTORY_SENTINEL),
            a_turn(
                role="assistant",
                content="",
                calls=(
                    ToolCall(
                        id="c1",
                        name="remember",
                        arguments={"fact": ARGUMENTS_SENTINEL},
                    ),
                ),
            ),
            a_turn(
                role="tool",
                content="",
                results=(ToolResult(tool_call_id="c1", content=RESULT_SENTINEL),),
            ),
        ],
        tools=[a_tool(description=SCHEMA_SENTINEL)],
    )


@pytest.mark.asyncio
async def test_the_authorized_content_reaches_the_span_writer_and_nowhere_else(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The inverse of the usual claim, and this file's reason for
    existing. What this surface exists to send is the whole assembled
    prompt, so every planted value HAS to arrive at the one place that
    sends it; what it must not do is appear in a log line, an event
    payload, an emission or an exception chain on the way.
    """
    caplog.set_level(logging.DEBUG)
    tap = Tap()
    events_seen: EventTap = tap
    exporter, telemetry = an_exporter()

    attach_server_tap(events_seen)
    try:
        a_planted_round(exporter)
        exporter.session_closed(SESSION)
        await drained(exporter, lambda: telemetry.jobs)
    finally:
        detach_server_tap(events_seen)

    (one,) = telemetry.rounds
    for sentinel in SENTINELS:
        assert sentinel in one.request, f"{sentinel} never reached the span writer"
    written = both_formats(caplog)
    offered = repr([emission.payload for emission in tap.seen])
    for sentinel in SENTINELS:
        assert sentinel not in written, f"{sentinel} reached a log record"
        assert sentinel not in offered, f"{sentinel} reached an emission"


@pytest.mark.asyncio
async def test_every_failure_family_says_nothing_of_what_it_was_carrying(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Each failure in turn, over a round that carries every sentinel:
    the reason is a token from a closed set, and nothing of the request
    rides beside it."""
    caplog.set_level(logging.DEBUG)
    families: list[Exported] = [
        Exported({}),
        Exported({SESSION: A_CONTEXT}, answer=Delivery.UNDELIVERED),
        Exported({SESSION: A_CONTEXT}, answer=Delivery.STOPPED),
        Exported(
            {SESSION: A_CONTEXT}, raises=RuntimeError(f"carrying {RESULT_SENTINEL}")
        ),
    ]
    for index, telemetry in enumerate(families, start=1):
        exporter, _ = an_exporter(telemetry=telemetry)
        a_planted_round(exporter)
        exporter.session_closed(SESSION)
        await drained(
            exporter,
            lambda index=index: len(reasons(caplog)) >= index,
            "a failure family said nothing at all",
        )

    assert sorted(set(reasons(caplog))) == sorted(
        {
            LlmInputExportFailure.NO_TRACE,
            LlmInputExportFailure.UNDELIVERED,
            LlmInputExportFailure.DROPPED,
        }
    )
    written = both_formats(caplog)
    for sentinel in SENTINELS:
        assert sentinel not in written, f"{sentinel} rode a failure"


def test_a_refusal_renders_nothing_it_was_configured_with(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every refusal this builder can raise, against an environment set
    to credential-shaped values: the sentences name keys and reaches and
    never an endpoint, a host or a credential, and nothing is chained
    behind them."""
    for name in (
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "OTEL_EXPORTER_OTLP_HEADERS",
        "LANGFUSE_HOST",
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
    ):
        monkeypatch.setenv(name, f"https://user:{RESULT_SENTINEL}@host/{RESULT_SENTINEL}")
    held, _ = exporting()
    refusals = []
    for config, telemetry, boundary in (
        (a_server(telemetry={"enabled": False, "export_llm_input": True}), None, None),
        (a_server(), None, None),
        (a_server(), held, Reach.HOST),
    ):
        with pytest.raises(ConfigError) as refusal:
            build_llm_input_export(config, telemetry=telemetry, boundary=boundary)
        refusals.append(refusal.value)

    assert len(refusals) == 3
    for raised in refusals:
        assert RESULT_SENTINEL not in str(raised)
        assert raised.__cause__ is None
        assert raised.__context__ is None
