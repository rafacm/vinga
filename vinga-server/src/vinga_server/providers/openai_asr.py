"""Speech to text over the OpenAI transcription API.

The third of the cloud providers in issue #11, and the first that is
not a voice: multilingual accuracy better than a local `small` model,
without provisioning a GPU or downloading weights. No SDK to add and no
extra, for the reason the `openai` TTS type has none: the `openai`
client is already a core dependency, carried for the
`openai_compatible` LLM type, and transcription is a method on the
client that already ships. One key therefore serves all three stages.

`base_url` is the same door the other two `openai` types open. Several
self-hosted servers implement `/v1/audio/transcriptions`, so pointing
this type at one keeps a fully local pipeline available through the
same dialect. It defaults to OpenAI itself, and it is what decides
whether this provider sends anything off the host, which is why the
type cannot declare its own reach.

What this type accepts is declared once, as `OpenaiAsrOptions` in
`config/provider_options.py`, and reaches the builder below already
validated (#88). What did not move there is the pair of rules that are
about the endpoint rather than about a value: that `base_url` is a URL
this repository can classify, and that `temperature` is inside OpenAI's
own range when the endpoint is OpenAI. Both are `openai_endpoint`'s
question, and the model is on a path that cannot import it.

**This provider does not stream, and does not need to.** #11 asks a
network provider to stream or to justify not streaming. The stage's
interface is one whole utterance in, one whole transcript out, because
the LLM stage cannot begin on half a sentence; and the utterance is
already complete before `transcribe` is called, since the endpointer is
what decides the call happens. Streaming the response would therefore
deliver text deltas nothing downstream can consume, a turn's worth of
latency earlier than the turn can use them. The TTS stage is the
opposite case, and streams.

**This provider reports the language it heard, where it was not told
one.** The response carries `languages: [{"code": "de"}]` on the plain
`json` format, an ISO 639 code rather than the English name
`whisper-1` answers with under `verbose_json`. Which models answer at
all is theirs to decide: `gpt-transcribe` answers whenever it makes out
a language and the gpt-4o pair answers nothing ever. And a model that
does answer says so only where there was something to hear: silence and
laughter both came back `languages: []`, which is the endpoint's own
spelling of "I heard no language" and leaves the field empty without a
rule of ours, exactly as a response carrying no key at all does.

The condition is the whole of the rule. Measured against the live
endpoint on 2026-09-13: told a single language, the model hands that
code straight back rather than saying what it heard, so a reported code
is evidence about the audio only where this provider named no single
language, and reporting it regardless would put an entry's own
configuration into a metric under the name of a measurement. That is
the rule the pipeline already states where it builds the `heard` event,
"a mock or a pinned language adds no noise to the record", and this is
the first type for which it has teeth. What arrives is a signal in
aggregate rather than a verdict per turn: the code says what the model
decided, not what was said, and the clip this work started from, a
spoken German "Hallo", was transcribed `Hello.` and reported `en`.

No model reports a confidence, so `language_confidence` stays empty,
and a code is asked of `LanguageTag` before it travels, because
`events/assembly.py` constructs one with nothing catching it and a code
this module could not vouch for would break a turn that had already
been transcribed. The session-scoped lock (`lock_language`) is still
never asked for. The lock exists to spare faster-whisper a constant
encoder pass per utterance (#22); here detection happens inside the
model at no measurable cost, so there is nothing to spare.
"""

import asyncio
import io
import logging
import wave
from collections.abc import Mapping
from dataclasses import dataclass

from openai import NOT_GIVEN, APITimeoutError, AsyncOpenAI, Omit

from vinga_server.config.models import ProviderConfig
from vinga_server.config.provider_options import OpenaiAsrOptions
from vinga_server.events import ServerEvents
from vinga_server.events.catalog import (
    EchoConfirmed,
    EchoConfirmedEmpty,
    EchoRecovered,
    EchoRetryTimedOut,
    EchoSkipped,
)
from vinga_server.events.values import (
    EventValueError,
    Identifier,
    LanguageTag,
    Real,
    Whole,
)
from vinga_server.providers.base import (
    AsrProvider,
    AsrResult,
    ProviderCallError,
    ProviderError,
)
from vinga_server.providers.kit import (
    DEFAULT_TIMEOUT_S,
    MAX_RETRIES,
    OPENAI_FAILURES,
    call_failure,
)
from vinga_server.providers.openai_endpoint import (
    DEFAULT_BASE_URL,
    endpoint_api_key,
    endpoint_host,
    parse_base_url,
)

logger = logging.getLogger(__name__)

# The provider scope's emitter, on the channel this module already logged
# on. One per module rather than one per provider: an entry's identity is
# the host it speaks to, which every event names, and the guard's outcome
# is about the endpoint rather than about the object holding the client.
events = ServerEvents(__name__)

# How this provider names itself in the message a failed request
# carries.
LABEL = "openai asr"

# The API's own range for `temperature`.
TEMPERATURE_RANGE = (0.0, 1.0)

# OpenAI refuses audio shorter than this, and the barge-in path is what
# would send it: a snippet classified as speech mid-reply is
# transcribed to decide whether the interruption was real (#28), and
# the shortest of those are tens of milliseconds. An HTTP 400 there
# would be logged as a failed confirmation and suppress a barge-in that
# was never going to be confirmed anyway, so the empty answer is given
# here instead, without a round trip.
#
# Measured against OpenAI's endpoint, so it is applied only there. A
# compatible server may accept shorter audio, and suppressing a clip it
# would have answered would silently drop a barge-in it could have
# confirmed; that endpoint decides its own minimum, the same way it
# decides its own model rules and its own temperature range.
MIN_AUDIO_S = 0.1

# The API decides the format from the extension, so the name matters
# even though there is no file.
UPLOAD_NAME = "utterance.wav"

# The least of the shared timeout worth spending on the echo retry.
# The retry answers to the same timeout_s as the request that tripped
# the guard (see transcribe), so a first request that ate nearly the
# whole budget leaves the retry more likely to be cut off than to
# answer: field round trips on the short clips that echo ran about
# half a second, so under a second of remaining budget the retry
# would mostly buy a longer wait for the same discard.
RETRY_FLOOR_S = 1.0

# Sentence-final punctuation an echoed prompt can come back wearing:
# the model is transcribing, so it writes what it returns as a
# sentence. Measured, and rare rather than theoretical: of 45 echoes
# provoked against `gpt-4o-mini-transcribe`, 44 were the prompt exactly
# (in either case) and one carried a trailing full stop. Ignoring it
# would leave the fix passing a spurious utterance through once in
# tens of turns, which is the frequency the field report itself had.
TRAILING = ".!?…。！？"


def _normalized(text: str) -> str:
    """A transcript reduced to what makes it the same words as another:
    surrounding space, sentence-final punctuation, and case."""
    return text.strip().rstrip(TRAILING).strip().casefold()


@dataclass(frozen=True)
class _Hearing:
    """What one request heard: a transcript, and the language reported
    with it or None.

    One value rather than two, because the echo retry below replaces a
    first response's answer with a second response's and the two halves
    have to be replaceable together. A language assigned beside the text
    could be the discarded response's, which is a turn labelled with a
    language nothing in it was heard in; the outcomes that discard
    answer no language because they answer no text.
    """

    text: str
    language: str | None = None


def _code_of(entry: object) -> object:
    """One reported entry's `code`, however the SDK models the entry.

    A mapping today and a typed object the day the SDK declares the
    field, which is one name read one way rather than two shapes to
    branch on twice. Anything carrying no such name answers None, which
    is what a list of bare strings does.
    """
    if isinstance(entry, Mapping):
        return entry.get("code")
    return getattr(entry, "code", None)


def _reported_language(response: object) -> str | None:
    """The one language code a transcription response reports, or None
    for anything this server cannot hand on as one.

    Read through `getattr` rather than off `model_extra`, so a field the
    SDK declares later and an extra one today are the same read, and
    read defensively at every step: no key, a value that is not a list,
    an empty list (which is the endpoint's own spelling of "I heard no
    language", on silence and on laughter), more than one entry, an
    entry with no `code`, and a `code` that is not a string all answer
    None.

    The code itself is asked of `LanguageTag` rather than of a pattern
    written here, the way `events/catalog.py::_named` asks `EventName`
    and for the same reason: that is the type this value becomes in
    `events/assembly.py`, which constructs it with nothing catching the
    refusal, so a code accepted here and refused there would break a
    turn that had already been transcribed. A far-side value decides
    what one field says and never whether the turn survives.
    """
    reported = getattr(response, "languages", None)
    if not isinstance(reported, list) or len(reported) != 1:
        return None
    code = _code_of(reported[0])
    if not isinstance(code, str):
        return None
    try:
        LanguageTag(code)
    except EventValueError:
        return None
    return code


def wav_bytes(pcm: bytes, sample_rate: int) -> bytes:
    """s16le mono PCM in a WAV container.

    The endpoint takes an audio file rather than a buffer and a rate,
    and WAV is the one accepted format that holds this stage's PCM as
    it already is: a 44 byte header in front of the samples, no
    re-encoding, no dependency, and no quality lost on the way. The
    rate is written from the argument rather than assumed, so this
    provider transcribes whatever the pipeline is running at."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as container:
        container.setnchannels(1)
        container.setsampwidth(2)
        container.setframerate(sample_rate)
        container.writeframes(pcm)
    return buffer.getvalue()


class OpenAiAsr(AsrProvider):
    # The base_url decides: a self-hosted transcription server on
    # localhost keeps the audio on the host, api.openai.com does not.
    # Under a declared server.data_boundary the entry therefore needs
    # its own explicit `reach` declaration, exactly as openai_compatible
    # does.
    reach = None

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        language: str | None = None,
        prompt: str | None = None,
        temperature: float | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        min_audio_s: float = MIN_AUDIO_S,
        client: AsyncOpenAI | None = None,
    ) -> None:
        self.model = model
        self.host = endpoint_host(base_url)
        self._language = language
        self._prompt = prompt
        self._temperature = temperature
        # Kept for the echo retry's deadline: the whole transcribe call,
        # retry included, answers to this one budget (see transcribe).
        self._timeout_s = timeout_s
        # Shortest audio worth sending. The endpoint sets it, so a
        # compatible one that accepts anything gets 0: see MIN_AUDIO_S.
        self._min_audio_s = min_audio_s
        # One client per provider entry, so its connection pool is
        # reused across turns and sessions: a fresh TLS handshake per
        # utterance would land squarely in the gap between the user
        # finishing their sentence and the assistant answering.
        # It lives exactly as long as this entry does, which is until an
        # apply rewrites the entry or the process ends, and `close`
        # below is where the pool goes.
        self._client = (
            client
            if client is not None
            else AsyncOpenAI(
                api_key=api_key,
                base_url=base_url,
                timeout=timeout_s,
                max_retries=MAX_RETRIES,
            )
        )

    async def close(self) -> None:
        """Shut the SDK client's connection pool. An entry an apply has
        rewritten is built again as a new object, and this one holds
        sockets to a host nothing is going to ask anything of again."""
        await self._client.close()

    async def transcribe(
        self, pcm: bytes, sample_rate: int, language_hint: str | None = None
    ) -> AsrResult:
        if not pcm or len(pcm) < int(self._min_audio_s * sample_rate) * 2:
            logger.debug(
                "openai asr: %d bytes is under the %.2fs minimum, nothing to transcribe",
                len(pcm),
                self._min_audio_s,
            )
            # Nothing was sent, so nothing was billed, and the answer
            # says so with a measured zero rather than with silence:
            # "this ear submitted nothing" is a fact about the floor,
            # where an absent measurement would be a fact about the
            # engine.
            return AsrResult(text="", submitted_ms=0)
        # A configured language always beats the hint, as elsewhere. The
        # hint can only be a lock some provider asked for, and this one
        # never does, so in practice it is the configured language or
        # nothing.
        pinned = self._language or language_hint
        # One deadline for the whole call, echo retry included. The
        # client's retries are off (MAX_RETRIES) precisely so timeout_s
        # bounds what a user can be left waiting on one utterance, and
        # a retry with a fresh timeout of its own would quietly double
        # that bound.
        deadline = asyncio.get_running_loop().time() + self._timeout_s
        # The taxonomy applies to the failure of this call as a whole,
        # not to every request inside it: the echo retry below
        # deliberately converts its own timeout into an empty transcript
        # and an asr_prompt_echo event, and that discard is a decision
        # rather than a failure. What is left here is a call that could
        # not answer at all, which is a failed provider call.
        # Cancellation, a genuine bug, and another vendor's SDK error are
        # outside OPENAI_FAILURES and pass through as themselves.
        failure: ProviderCallError | None = None
        # How much audio this call put on the wire, counted per REQUEST
        # rather than per utterance. The first request always sends the
        # whole clip; the echo retry below sends the same bytes a second
        # time, and a clip the deadline left no room for sends nothing.
        clip_ms = round(len(pcm) / 2 / sample_rate * 1000)
        submitted_ms = 0
        try:
            heard = await self._request(pcm, sample_rate, pinned, self._prompt)
            submitted_ms = clip_ms
            if self._is_echoed_prompt(heard.text):
                heard, resent = await self._retry_without_prompt(pcm, sample_rate, pinned, deadline)
                if resent:
                    submitted_ms += clip_ms
        except OPENAI_FAILURES as exc:
            failure = call_failure(LABEL, exc)
        # Raised out here rather than in the except arm, so the SDK
        # exception is not even the new error's `__context__`: `from
        # None` suppresses its rendering but leaves it reachable, and
        # what it can carry is the reason the message is metadata only.
        if failure is not None:
            raise failure from None
        # The transcript and the language as one hearing answered them,
        # never one of them beside the other's: where the retry replaced
        # the text it replaced the language with it. No confidence,
        # because no model reports one, and no lock, because there is no
        # encoder pass here to spare.
        return AsrResult(text=heard.text, language=heard.language, submitted_ms=submitted_ms)

    async def _request(
        self,
        pcm: bytes,
        sample_rate: int,
        pinned: str | None,
        prompt: str | None,
        timeout_s: float | None = None,
    ) -> _Hearing:
        # The single language this request names, or None where it names
        # none. Read below as well as sent here, so what suppresses the
        # report is exactly what the model was told: a blank `language`
        # puts no field on the wire and is therefore not a pin.
        single = pinned if pinned else None
        response = await self._client.audio.transcriptions.create(
            file=(UPLOAD_NAME, wav_bytes(pcm, sample_rate), "audio/wav"),
            model=self.model,
            # The one format every model and every compatible server
            # answers in, and the one the language report arrives on:
            # `verbose_json` is whisper-1 only and adds nothing usable
            # here. See the module docstring on language.
            response_format="json",
            language=single if single is not None else Omit(),
            prompt=prompt if prompt else Omit(),
            temperature=self._temperature if self._temperature is not None else Omit(),
            # The client's own timeout, unless this request is a retry
            # living on what the first request left of it. NOT_GIVEN,
            # not Omit(): Omit is a serialization sentinel for request
            # fields, and timeout is a client option, so an Omit here
            # flows through the SDK into httpx as the literal connect
            # timeout and fails every call at connect time (#75).
            timeout=timeout_s if timeout_s is not None else NOT_GIVEN,
        )
        # A reported code is evidence about the audio only where this
        # request named no single language: told one, the model hands
        # that code back rather than saying what it heard. See the
        # module docstring for the measurement.
        return _Hearing(
            response.text.strip(),
            None if single is not None else _reported_language(response),
        )

    async def _retry_without_prompt(
        self, pcm: bytes, sample_rate: int, pinned: str | None, deadline: float
    ) -> tuple[_Hearing, bool]:
        """A second hearing for a clip whose transcript was the prompt
        handed back, and whether the clip was actually sent again.

        What it answers replaces the first response's hearing whole, the
        transcript and the language together, and the four outcomes that
        discard answer an empty hearing: they answer no text, so they
        answer no language either.

        The flag is what the caller bills on. Four of the five ways this
        ends put the clip on the wire a second time, the deadline timeout
        included, because bytes a request was cancelled in the middle of
        are bytes the far side received; only the skip below sends
        nothing. A caller counting retries by their OUTCOME would miss
        the two that answer nothing at all, which are exactly the ones a
        suspicious clip is most likely to produce.

        The guard used to treat the echo as proof of silence, and the
        field data says it is not: nine echoes in two days of testing,
        every one on a clip of 0.78 to 1.92 s, two of them a user
        answering "yes, please" and being ignored (#69). Short
        acknowledgements are exactly the clips the model is most likely
        to echo the prompt on, so the same audio is transcribed once
        more with the prompt withheld: real speech transcribes fine
        without the prompt's help, and real silence comes back empty
        (or as another hallucination the guard still catches). Only
        this suspicious path pays the second round trip, at roughly the
        cost of the first one; the normal path is one request, as
        before.

        The retry lives on what the first request left of the shared
        deadline, and is skipped outright when less than RETRY_FLOOR_S
        remains: timeout_s is the bound on what a user can be left
        waiting, and a retry outliving it would break that promise. A
        retry the deadline cuts off is the discarding outcome rather
        than an error, since the reply it would have ended is one the
        guard was about to end anyway.

        The #54 rationale stands: an exact echo of the prompt is never
        handed to the session as an utterance, retried or not."""
        duration_s = round(len(pcm) / 2 / sample_rate, 2)
        loop = asyncio.get_running_loop()
        remaining_s = deadline - loop.time()
        if remaining_s < RETRY_FLOOR_S:
            events.emit(
                lambda: EchoSkipped(
                    duration_s=Real(duration_s),
                    host=Identifier(self.host),
                    remaining_s=Real(remaining_s),
                )
            )
            return _Hearing(""), False
        logger.warning(
            "openai asr: the transcript came back as the configured prompt, "
            "retrying %.2f s of audio without it",
            duration_s,
        )
        started = loop.time()
        try:
            # The asyncio deadline is what makes the budget absolute.
            # The SDK's timeout argument is an httpx timeout, which is
            # per phase: remaining_s passed there alone would let the
            # retry spend that long on each of connect, write and read,
            # exceeding the shared budget end to end. The per-request
            # override is still passed as belt and braces, so the
            # request machinery gives up on its own where it can rather
            # than being cancelled mid-phase.
            async with asyncio.timeout(remaining_s):
                retry = await self._request(
                    pcm, sample_rate, pinned, None, timeout_s=remaining_s
                )
        except (TimeoutError, APITimeoutError):
            retry_ms = round((loop.time() - started) * 1000)
            events.emit(
                lambda: EchoRetryTimedOut(
                    duration_s=Real(duration_s),
                    host=Identifier(self.host),
                    retry_ms=Whole(retry_ms),
                    remaining_s=Real(remaining_s),
                )
            )
            return _Hearing(""), True
        retry_ms = round((loop.time() - started) * 1000)
        if self._is_echoed_prompt(retry.text):
            events.emit(
                lambda: EchoConfirmed(
                    duration_s=Real(duration_s),
                    host=Identifier(self.host),
                    retry_ms=Whole(retry_ms),
                )
            )
            return _Hearing(""), True
        if not retry.text:
            events.emit(
                lambda: EchoConfirmedEmpty(
                    duration_s=Real(duration_s),
                    host=Identifier(self.host),
                    retry_ms=Whole(retry_ms),
                )
            )
            return _Hearing(""), True
        # The recovered transcript is not in the sentence, and naming
        # that one exists would add no diagnostic the fields lack.
        # Conversation-derived text is banned on the events without
        # exception (the content-and-telemetry ADR, as amended
        # 2026-08-17), however it was recovered; what was said reaches
        # the session below and, when recording is on, the conversation
        # store, which is the surface that holds content.
        events.emit(
            lambda: EchoRecovered(
                duration_s=Real(duration_s),
                host=Identifier(self.host),
                retry_ms=Whole(retry_ms),
            )
        )
        return retry, True


    def _is_echoed_prompt(self, text: str) -> bool:
        """Whether the model handed the prompt back instead of hearing
        anything. A known shape on short or low-content audio, and not a
        cosmetic one: an echo is fed to the session as an utterance the
        user never said, so a prompt naming the agents can trigger a
        handover nobody asked for.

        Equality rather than containment: a longer transcript that
        happens to open with the prompt is a person saying those words.
        A real utterance that is exactly the prompt string loses nothing
        worth keeping."""
        if not self._prompt:
            return False
        return _normalized(text) == _normalized(self._prompt)


def build(label: str, config: ProviderConfig, options: OpenaiAsrOptions) -> OpenAiAsr:
    """The entry's validated options as the provider's own arguments.

    What is left at this seam is what an options model cannot answer:
    which endpoint this entry speaks to, the two rules that follow from
    that, and the credential.

    The temperature range is one of those two, and it stays here rather
    than moving onto the field. The range is OpenAI's own, so it applies
    only when the endpoint is OpenAI, and `openai_endpoint` is the one
    home for deciding that; `config/provider_options.py` weighs pydantic
    and `config.models` and nothing else, so a model that asked the
    question would break that contract and a model that restated the
    URL rules would be a second home for them. What the model owns is
    the shape of a temperature; what it cannot own is whose rules apply.

    Nothing here refuses an option for its type. Every one of them was
    checked against `OpenaiAsrOptions` before this was called, which is
    the ordering the reader's `finish()` used to hold.
    """
    is_openai = parse_base_url(label, options.base_url)
    low, high = TEMPERATURE_RANGE
    # Only on OpenAI itself, for the reason the TTS type checks its
    # steering knobs only there: the range is a fact about OpenAI's
    # models, and a compatible server is free to accept another.
    if is_openai and options.temperature is not None and not low <= options.temperature <= high:
        raise ProviderError(f'{label}: option "temperature" must be between {low} and {high}')
    return OpenAiAsr(
        model=options.model,
        api_key=endpoint_api_key(label, config.type, config.api_key_env, is_openai),
        base_url=options.base_url,
        language=options.language,
        prompt=options.prompt,
        temperature=options.temperature,
        timeout_s=options.timeout_s,
        min_audio_s=MIN_AUDIO_S if is_openai else 0.0,
    )
