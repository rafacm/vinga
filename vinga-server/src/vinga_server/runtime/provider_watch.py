"""Watching a provider call: reporting it when it fails, bounding an
LLM's first token, and reporting a generation that finished.

The sibling of [`pipeline.py`](pipeline.py), and the two are told apart
by what they know about a call. The runtime knows why it is making one
and what to do with the answer; this module knows how a failing call is
reported without being swallowed, how a stream's own failure is told
apart from its consumer's, how long a first token may take and what
happens when it does not come, and what a finished round says and
files. The runtime's reply reads as a reply because none of that is
written inline in it.

Everything here reports and nothing here decides: a failure is said and
then raised on, exactly as it would have been raised without the watch,
and the reply's own arms decide what a failed call means for the turn.
The one thing this module does act on is the first-token bound, whose
retry is the whole of its job.

`conversations` are the device session's, and what this module reads
there is who is talking: every record it writes names the agent and the
thread. Read inside each emission's thunk rather than taken once or at a
call's start, because a handover can land in any await a watched call
makes, and the record of a call that straddled one names the pair it
ended on, which is what every other emitter in a session does.
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator, Callable, Sequence
from typing import TYPE_CHECKING, Any

from vinga_server.events import SessionEvents, assembly
from vinga_server.events.values import LlmPurpose
from vinga_server.providers import LlmEvent, StreamStarted, Turn, Usage
from vinga_server.runtime.turns import TurnUnderway
from vinga_server.session_conversations import SessionConversations

if TYPE_CHECKING:
    # Named rather than imported, for the reason the runtime gives:
    # `llm_input_export.py` imports `telemetry.py`, and a watch that only
    # ever holds the export should not make a reply pay for that import.
    from vinga_server.llm_input_export import LlmInputExport


class FirstTokenTimeout(TimeoutError):
    """The LLM produced nothing within the first-token watchdog window,
    twice in a row. The class name is what the `provider_failed` event
    carries in `error`, which is what makes a provider that stalls
    before answering distinguishable in the retained logs from one
    whose own SDK timed out."""


def _reported(usage: Usage | None) -> tuple[int | None, int | None]:
    """What a round says about its size.

    Token counts appear where the provider reported them; their absence
    is a fact about the endpoint rather than a zero. Plain numbers,
    because the same two answers are read twice over: the event wraps
    them in its own value types, and the turn's record counts them.
    """
    return (
        usage.prompt_tokens if usage is not None else None,
        usage.completion_tokens if usage is not None else None,
    )


class ProviderWatch:
    """One session's watch over the provider calls its replies make.

    `events` is what it says things through, and `conversations` is
    where it reads who is talking, at the moment it says them.
    `first_token_timeout_s` is the bound on an LLM's first event, taken
    at construction because it is read from the server section, the
    file half that no reload replaces, so a value taken once is the
    same answer at every call. `llm_input` is the post-close export a
    deployment asked for, or None; a round that ends, however it ends,
    tells it the round is over.

    What a caller hands in per call is what belongs to the call: the
    provider, the invocation, and for a reply round the round number and
    the turn it is filed on. The round is the reply's to count and the
    turn is the reply's to replace, so neither is held here.
    """

    def __init__(
        self,
        events: SessionEvents,
        conversations: SessionConversations,
        first_token_timeout_s: float,
        llm_input: "LlmInputExport | None",
    ) -> None:
        self._events = events
        self._conversations = conversations
        self._first_token_timeout_s = first_token_timeout_s
        self._llm_input = llm_input

    def _agent(self) -> str | None:
        """The agent talking at the moment of asking. A method rather
        than a value kept, for the reason the module gives: every
        emission reads the pair standing when it is said."""
        active = self._conversations.active
        return None if active is None else active.agent

    def _conversation(self) -> str | None:
        """The thread that agent is on at the moment of asking."""
        active = self._conversations.active
        return None if active is None else active.conversation

    @contextlib.asynccontextmanager
    async def watching(self, stage: str, provider: object) -> AsyncIterator[None]:
        """Report a provider that fails, then let the failure carry on
        as before.

        A failing ASR, LLM or TTS call used to reach the operator as a
        traceback under "reply failed", with none of the fields every
        other conversation record is queried by: no `event`, no
        `session`, no provider, and above all no host, which is the one
        an outbound policy is diagnosed from. The reply still ends the
        same way, and the traceback is still logged where it was; this
        adds the structured half the observability ADR says is the
        surface (#53)."""
        started = asyncio.get_running_loop().time()
        try:
            yield
        except Exception as exc:
            self.failed(
                stage, provider, exc, asyncio.get_running_loop().time() - started
            )
            raise

    async def watched(
        self,
        provider: object,
        events: AsyncIterator[Any],
        *,
        invocation: str,
        purpose: LlmPurpose,
    ) -> AsyncIterator[Any]:
        """An LLM stream, with a failure raised by the stream itself
        reported as that provider's.

        A plain `async with` around the consuming loop would blame the
        LLM for a TTS failure raised while speaking what the model had
        already said, and report one failure twice. Pulling the stream
        by hand is what separates the two: what the consumer raises
        closes this generator rather than passing through the guard."""
        started = asyncio.get_running_loop().time()
        iterator = events.__aiter__()
        while True:
            try:
                event = await iterator.__anext__()
            except StopAsyncIteration:
                return
            except Exception as exc:
                self.failed(
                    "llm",
                    provider,
                    exc,
                    asyncio.get_running_loop().time() - started,
                    invocation=invocation,
                    purpose=purpose,
                )
                raise
            yield event

    async def reply_stream(
        self,
        provider: object,
        make_stream: Callable[[], AsyncIterator[LlmEvent]],
        *,
        invocation: str,
        round_: int,
    ) -> AsyncIterator[LlmEvent]:
        """An LLM stream whose wait for the first event is bounded.

        Nothing used to bound the gap between sending the request and
        the first byte of the answer, so a provider that stalled there
        froze the pipeline: a 17 s stall held the session in replying,
        deaf to a user who politely waits, until a barge-in rescued it
        (#68). The bound covers only that gap. Once anything has
        arrived the stream is streaming and no timeout applies, because
        a long generation that is delivering is healthy: a 17.7 s story
        round with a 635 ms first token is fine.

        "First token" is the stream's first event of any kind. The
        adapters announce their first raw chunk off the wire as a
        `StreamStarted`, because both buffer tool-call fragments until
        the stream has ended: without the announcement a round that
        streams only a tool call (a handover does) would look exactly
        like a stalled request and be cancelled at the timeout while
        healthily delivering. The announcement is consumed here, being
        evidence rather than content, so nothing downstream sees it.

        One timeout cancels the request and retries the round once,
        since the field data says the retry answers quickly (6.16 s
        total against the 17 s stall it replaced). A second timeout
        gives up: the failure is reported as the provider's, with
        `FirstTokenTimeout` telling it apart from the provider's own
        classes, and the reply ends the way any provider failure ends
        it, so the failure mode is a silent turn rather than a wedged
        session. Barge-in keeps working through the whole window: it
        cancels the reply task, and that cancellation lands in the wait
        here like in any other await.

        The provider's own timeout classes pass through untouched: the
        `expired()` check is what keeps an SDK timeout raised just
        before the watchdog's deadline from being retried as if the
        watchdog had fired.

        `round_` is the reply's round this stream is, counted by the
        caller across the whole reply, which is what the retry line
        names. This is itself the generator a caller iterates, with no
        second one wrapped around it, so a cancellation lands in the
        wait above rather than in an await added on the way to it."""
        timeout_s = self._first_token_timeout_s
        loop = asyncio.get_running_loop()
        for attempt in ("first", "retry"):
            events = self.watched(
                provider,
                make_stream(),
                invocation=invocation,
                purpose=LlmPurpose.REPLY,
            )
            started = loop.time()
            stalled: float | None = None
            try:
                async with asyncio.timeout(timeout_s) as watchdog:
                    first = await events.__anext__()
            except StopAsyncIteration:
                return
            except TimeoutError:
                if not watchdog.expired():
                    raise
                stalled = loop.time() - started
            if stalled is not None:
                elapsed = stalled
                if attempt == "retry":
                    # Raised out here rather than in the arm above, and
                    # without `from`: inside the arm the `TimeoutError`
                    # asyncio made for the expiry is the active one, and
                    # the cancellation behind it, so the failure would
                    # leave carrying both as its context whatever its
                    # cause said. What gave the round up is the watchdog,
                    # which the class says; the library's chain is not
                    # this server's to hand a traceback or an exporter.
                    failure = FirstTokenTimeout(
                        f"no first token within {timeout_s:.0f} s, twice"
                    )
                    self.failed(
                        "llm",
                        provider,
                        failure,
                        elapsed,
                        invocation=invocation,
                        purpose=LlmPurpose.REPLY,
                    )
                    raise failure
                # The loop variable is read by a thunk the emitter calls
                # before this iteration ends, so there is no late binding
                # for B023 to be about.
                self._events.emit(
                    lambda: assembly.llm_retried(
                        self._agent(),
                        self._conversation(),
                        "llm",
                        provider,
                        round_,
                        elapsed,  # noqa: B023
                    )
                )
                continue
            if not isinstance(first, StreamStarted):
                yield first
            async for event in events:
                yield event
            return

    def reply_round_done(
        self,
        turn: TurnUnderway,
        round_: int,
        provider: object,
        working: Sequence[Turn],
        began: float,
        first_token_at: float | None,
        usage: Usage | None,
        *,
        invocation: str,
    ) -> None:
        """A round of a reply finished: its `llm_round`, numbered
        `round_`, and the round filed on `turn`, the record of the turn
        it belongs to."""
        elapsed, first_token_ms, inputs, outputs = self._rounded(
            provider,
            working,
            began,
            first_token_at,
            usage,
            invocation=invocation,
            purpose=LlmPurpose.REPLY,
            round_=round_,
        )
        # Counted here rather than where the round starts, so that the
        # turn's rounds, its summed duration and its token totals all
        # describe one set of rounds: the ones that finished, which is
        # the set an `llm_round` row exists for.
        turn.round_done(round(elapsed * 1000), first_token_ms, inputs, outputs)

    def recap_round_done(
        self,
        provider: object,
        working: Sequence[Turn],
        began: float,
        first_token_at: float | None,
        usage: Usage | None,
        *,
        invocation: str,
    ) -> None:
        """A recap's summarization finished: its `llm_round`, with no
        round number and filed on no turn.

        A recap is a generation but not a round of the reply, so it
        counts on no record. Its own method rather than a flag on the
        reply's, because a flag would make a recap with a round number,
        or a reply round filed nowhere, something a caller could ask
        for."""
        self._rounded(
            provider,
            working,
            began,
            first_token_at,
            usage,
            invocation=invocation,
            purpose=LlmPurpose.RECAP,
            round_=None,
        )

    def _rounded(
        self,
        provider: object,
        working: Sequence[Turn],
        began: float,
        first_token_at: float | None,
        usage: Usage | None,
        *,
        invocation: str,
        purpose: LlmPurpose,
        round_: int | None,
    ) -> tuple[float, int | None, int | None, int | None]:
        """One `llm_round` event, which is where a slow reply becomes
        attributable.

        Stage latency was otherwise inferred from the gaps between
        events, and the gap between `heard` and `speaking_started`
        holds the LLM and the TTS time to first byte with nothing
        between them. A field session lost 19.04 s inside that gap
        against a session median of 1.18 s, and the logs could not say
        whether the payload or the vendor was responsible (#55).

        `turns` is the cheap proxy for payload size, and `round` counts
        the whole reply rather than one agent's leg, so the generation
        after a handover is a round of its own rather than another
        first round. Token counts appear when the provider reported
        them; their absence is a fact about the endpoint. They are named
        `input_tokens` and `output_tokens`, the GenAI conventions'
        vocabulary adapted to this project's field style (#120), which
        is also what the store's `turns` columns have been called since
        their first migration. The `Usage` dataclass keeps the SDK-shaped
        names it is filled from: it is not surface.

        `first_token_ms` times the first spoken token, so a round that
        only asked for a tool carries none: there was no token, and
        timing the tool call instead would report the whole generation
        as its own time to first token, since both providers assemble
        calls after the stream has ended.

        Answers what it measured, the elapsed seconds, the first token
        and the two token counts, for the one caller that files them."""
        loop = asyncio.get_running_loop()
        elapsed = loop.time() - began
        first_token_ms = (
            None if first_token_at is None else round((first_token_at - began) * 1000)
        )
        inputs, outputs = _reported(usage)
        if self._llm_input is not None:
            self._llm_input.finish(invocation)
        self._events.emit(
            lambda: assembly.llm_rounded(
                self._agent(),
                self._conversation(),
                "llm",
                provider,
                round_,
                len(working),
                elapsed,
                inputs,
                outputs,
                first_token_ms,
                invocation,
                purpose,
            )
        )
        return elapsed, first_token_ms, inputs, outputs

    def failed(
        self,
        stage: str,
        provider: object,
        exc: BaseException,
        elapsed: float,
        *,
        invocation: str | None = None,
        purpose: LlmPurpose | None = None,
    ) -> None:
        """One `provider_failed` event, and the sentence that goes with
        it. A timeout is worded as one, because where traffic is
        dropped rather than refused the whole symptom is a wait.

        Which failure is a wait is a question of type. Every provider
        raises `ProviderCallTimeout` for its SDK's timeouts and that is
        a `TimeoutError`, as are `asyncio.TimeoutError` and the
        watchdog's own `FirstTokenTimeout`, so one `isinstance` covers
        the lot (#137). It used to be decided by looking for "Timeout"
        in the class name, because the SDKs' own classes agreed on
        nothing: `openai.APITimeoutError` is an `APIConnectionError` and
        `httpx.TimeoutException` inherits from neither.

        The class name is reported and the exception's message is not.
        The five real providers raise the request-time taxonomy, whose
        messages carry trusted metadata only (`providers/kit.py`), but
        this takes a `BaseException` from four call sites and one of
        them is the LLM stream, so anything an SDK or a transport
        raises can arrive here unwrapped, and an exception raised near
        a response body can embed one in its message. That would land
        in the sentence, in the record's arguments, and from there in
        front of every consumer attached to the session, which is the
        same reason the reply's catch in `PipelineRuntime._reply` prints
        a class name and nothing else. What the class does not say, the
        fields do: the stage, the entry, its type, and the host.
        """
        if stage == "llm" and invocation is not None and self._llm_input is not None:
            self._llm_input.finish(invocation)
        self._events.emit(
            lambda: assembly.provider_failure(
                self._agent(),
                self._conversation(),
                stage,
                provider,
                exc,
                elapsed,
                invocation=invocation,
                purpose=purpose,
            )
        )
