"""The OpenAI ASR provider against a mock transport.

No extra to skip on and no network: the openai client is a core
dependency, and it accepts an `http_client`, so the whole provider
(options, the WAV upload, the request shape, failures) runs here
through the real SDK serialization. What a unit test cannot judge is
how well it hears and what the round trip costs, which is the PR's
real-API verification step.
"""

import asyncio
import io
import logging
import wave
from collections.abc import Iterator

import httpx
import pytest

from tests.support.events import events as emitted
from tests.support.events import fields_of
from tests.support.leaks import chain
from tests.support.llm_sdk import Falsey
from tests.support.openai_sdk import mock_client
from vinga_server.boundary import Reach
from vinga_server.config.models import ProviderConfig
from vinga_server.config.provider_options import OpenaiAsrOptions
from vinga_server.conversations.records import TurnRecord
from vinga_server.events import (
    Emission,
    SessionEvents,
    assembly,
    attach_server_tap,
    detach_server_tap,
)
from vinga_server.logs import TEXT_FORMAT, JsonFormatter
from vinga_server.providers import (
    ProviderCallError,
    ProviderCallTimeout,
    build_entry,
    openai_asr,
)
from vinga_server.providers.base import AsrResult, ProviderError
from vinga_server.providers.kit import DEFAULT_TIMEOUT_S
from vinga_server.providers.openai_asr import OpenAiAsr
from vinga_server.providers.openai_endpoint import DEFAULT_BASE_URL
from vinga_server.runtime.turns import TurnUnderway

# One 16 kHz second of s16le silence, comfortably over the API minimum.
ONE_SECOND = b"\x00\x00" * 16000

# Not a real credential, and shaped so a substring check for it cannot
# match by accident. It stands in for what an endpoint can echo back
# into an error body.
SENTINEL = "sk-test-4f8b2c9e-never-a-real-credential"

# What the model hands back on the retry in the sentinel test below.
# The same shape, and a different value from the one above, so a hit
# says which path let it through: an error body the far side wrote, or
# a transcript a person spoke. A user reading a key aloud is a turn like
# any other, which is what makes this the honest stand-in for what a
# recovered transcript can be.
RECOVERED = "sk-test-9d3a7b1c-never-a-real-credential"


def provider(handler: object, **overrides: object) -> OpenAiAsr:
    """A provider wired to a mock transport, so nothing leaves the test."""
    client = mock_client(handler)
    options: dict[str, object] = {
        "model": "gpt-4o-mini-transcribe",
        "api_key": "test-key",
        "client": client,
    }
    options.update(overrides)
    return OpenAiAsr(**options)  # type: ignore[arg-type]


def transported(built: OpenAiAsr, handler: object) -> OpenAiAsr:
    """The provider the registry built, with its own client answering
    from the handler instead of from OpenAI.

    White-box, deliberately, and this is the only shape of reach-in this
    file keeps. The client a deployment gets is built inside the
    provider and handed to nobody, so how many attempts it makes, how
    long it waits, and what it puts on the wire are observable only
    against the real endpoint. Swapping the transport under that client
    is what puts it under a test at all; a hand-made client would be a
    different object carrying different settings.
    """
    built._client._client = httpx.AsyncClient(  # type: ignore[attr-defined]
        transport=httpx.MockTransport(handler)  # type: ignore[arg-type]
    )
    return built


def transcript_handler(text: str = "Hej hej") -> object:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"text": text})

    return handler


def reporting_handler(reported: object, text: str = "Hej hej") -> object:
    """A response that reports a language the way `gpt-transcribe` does:
    a `languages` list beside the text, on the plain `json` format this
    provider asks every model for."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"text": text, "languages": reported})

    return handler


# A response that carries no `languages` key at all, which is what the
# gpt-4o models answer and what a compatible endpoint may answer.
# Its own sentinel because `None` is a report a handler can send.
ABSENT_KEY = object()

# The session, thread and agent the pipeline hands the two calls below,
# spelled as the runtime mints them.
SESSION = "0123456789abcdef0123456789abcdef"
THREAD = "9f0c1d2e3a4b5c6d7e8f90a1b2c3d4e5"
AGENT = "household"




async def build_asr(**options: object) -> object:
    return await build_entry("asr", "ears", ProviderConfig.model_validate(options))


class Tap:
    """A server-scope consumer that keeps every emission it was handed.

    A clean `LogRecord` does not prove a clean consumer, which is what
    the server pin suite says about its own sentinels. Non-log taps are
    dispatched first and are handed the emission's own `args` tuple,
    whose members are deliberately not copied, so anything passed as a
    `%` argument reaches every consumer as the object itself. A claim
    that a value reaches no retained surface is therefore asserted here
    as well as at the log."""

    def __init__(self) -> None:
        self.seen: list[Emission] = []

    def emit(self, emission: Emission) -> None:
        self.seen.append(emission)

    def saw(self, event: str) -> list[Emission]:
        return [one for one in self.seen if one.payload.get("event") == event]

    def rendered(self) -> str:
        """Everything a consumer could read off what it was handed: the
        unrendered sentence, the payload, and every argument behind
        it."""
        parts: list[str] = []
        for emission in self.seen:
            parts += [emission.message, str(emission.payload), repr(emission.args)]
            for argument in emission.args:
                parts += [str(argument), repr(argument)]
        return "\n".join(parts)


@pytest.fixture
def tap() -> Iterator[Tap]:
    """A consumer attached to the server hub for one test, which is what
    a #66/#67 exporter will be. Detached however the test ends, since
    the hub outlives it."""
    consumer = Tap()
    attach_server_tap(consumer)
    try:
        yield consumer
    finally:
        detach_server_tap(consumer)


def only_heard(seen: Tap) -> Emission:
    """The one `heard` emission that reached a consumer.

    A guard that dropped the event leaves none, so this is where an
    implementation that handed a malformed code on fails: not on the
    field, which would be absent either way, but on the event that is
    no longer there."""
    (heard,) = seen.saw("heard")
    return heard


def downstream(asr: OpenAiAsr, result: AsrResult) -> tuple[Tap, TurnRecord | None]:
    """Where one transcription's answer lands: the consumer that saw its
    `heard` event, and the record the store would write.

    Both halves of `runtime/pipeline.py`'s own sequence, in its order,
    and through the calls it makes rather than through the builders
    under them. The distinction is the whole point of this helper. The
    event is emitted as a THUNK through `SessionEvents.emit`, whose
    guard catches a construction refusal and drops the event with the
    refusal reported, so what a malformed value costs is that event and
    not the reply. The record is the `TurnRecord` the store writes field
    for field (`conversations/store.py` maps `language` straight into a
    nullable `Text` column, and the `/api` turn model publishes it as a
    bare `str | None`), and nothing on that path checks a value at all:
    a code the event would decline is a code the record would keep.
    """
    events = SessionEvents(SESSION, clock=lambda: 1.0)
    consumer = Tap()
    events.attach(consumer)
    turn = TurnUnderway(conversation=THREAD, agent=AGENT)
    heard_at = events.emit(
        lambda: assembly.heard(
            AGENT,
            THREAD,
            asr,
            1.0,
            40,
            result.language,
            result.language_confidence,
            result.submitted_ms,
        )
    )
    turn.heard_utterance(
        heard_at, result.text, 1.0, result.language, result.language_confidence
    )
    return consumer, turn.record(AGENT, ())

def surfaces(record: logging.LogRecord) -> str:
    """Every retained rendering of one record: the unrendered template,
    the sentence a reader sees, the arguments substituted into it, the
    structured fields, and both shipped log formats."""
    return "\n".join(
        [
            str(record.msg),
            record.getMessage(),
            repr(record.args),
            str(fields_of(record)),
            logging.Formatter(TEXT_FORMAT).format(record),
            JsonFormatter().format(record),
        ]
    )


def uploaded_audio(request: httpx.Request) -> bytes:
    """The file part of a multipart body, as the far end receives it."""
    body = request.content
    start = body.index(b"RIFF")
    boundary = body[: body.index(b"\r\n")]
    return body[start : body.index(b"\r\n" + boundary, start)]


def form_field(request: httpx.Request, name: str) -> str | None:
    """One text field of a multipart body, None when it was not sent."""
    marker = f'name="{name}"\r\n\r\n'.encode()
    if marker not in request.content:
        return None
    start = request.content.index(marker) + len(marker)
    return request.content[start : request.content.index(b"\r\n", start)].decode()


def form_fields(request: httpx.Request, name: str) -> list[str]:
    """Every text field of a multipart body written under one name, in
    the order the parts arrive.

    The helper beside it finds exactly one part by exact name, which is
    right for every scalar this provider sends and blind to the one
    thing it sends as a list: a `languages` list is serialized as
    repeated parts named `languages[]`, one per element, never one
    comma-joined field. A test written on `form_field` would look for
    `languages`, find nothing, and pass while asserting nothing at all.
    """
    marker = f'name="{name}"\r\n\r\n'.encode()
    body = request.content
    found: list[str] = []
    start = body.find(marker)
    while start != -1:
        value = start + len(marker)
        found.append(body[value : body.index(b"\r\n", value)].decode())
        start = body.find(marker, value)
    return found


# --- options ---------------------------------------------------------


async def test_a_missing_api_key_env_fails_the_build() -> None:
    with pytest.raises(ProviderError, match="needs an API key"):
        await build_asr(type="openai")


async def test_an_unset_api_key_variable_fails_the_build(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_KEY", raising=False)
    with pytest.raises(ProviderError, match="references an unset environment variable"):
        await build_asr(type="openai", api_key_env="OPENAI_KEY")


async def test_an_unknown_option_fails_the_build(monkeypatch: pytest.MonkeyPatch) -> None:
    """A typo fails the build rather than silently configuring nothing,
    which is what `finish()` was for and what the closed door on
    `OpenaiAsrOptions` is for now.

    What the refusal no longer does is quote the key back. The reader
    named it, because there was no declared set to list instead; a type
    that declares its options has one, and a key that is not in it is a
    key an operator invented, which is as good a place to paste a
    credential as a value. The exact sentence is in the table below."""
    monkeypatch.setenv("OPENAI_KEY", "secret")
    with pytest.raises(ProviderError, match="an unrecognized key is not permitted") as caught:
        await build_asr(type="openai", api_key_env="OPENAI_KEY", beam_size=1)

    assert "beam_size" not in str(caught.value)


async def test_the_defaults_build(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_KEY", "secret")
    built = await build_asr(type="openai", api_key_env="OPENAI_KEY")
    assert isinstance(built, OpenAiAsr)


async def test_a_temperature_outside_the_api_range_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_KEY", "secret")
    with pytest.raises(ProviderError, match='"temperature" must be between'):
        await build_asr(type="openai", api_key_env="OPENAI_KEY", temperature=2.0)


@pytest.mark.parametrize(
    "base_url",
    [
        "https://api.openai.com/v1",
        "https://api.openai.com/v1/",
        "HTTPS://API.OPENAI.COM/v1",
        "https://api.openai.com:443/v1",
    ],
)
async def test_every_spelling_of_openai_keeps_the_startup_guarantees(
    base_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The host decides, not the spelling. A raw string comparison would
    let a trailing slash boot keyless and fail on the first utterance."""
    monkeypatch.delenv("OPENAI_KEY", raising=False)
    with pytest.raises(ProviderError, match="needs an API key"):
        await build_asr(type="openai", base_url=base_url)

    monkeypatch.setenv("OPENAI_KEY", "secret")
    with pytest.raises(ProviderError, match='"temperature" must be between'):
        await build_asr(type="openai", api_key_env="OPENAI_KEY", base_url=base_url, temperature=2.0)


@pytest.mark.parametrize("base_url", ["not-a-url", "api.openai.com/v1", "https://"])
async def test_a_base_url_that_is_not_a_url_fails_the_build(
    base_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Including the one that looks like OpenAI but has no scheme, which
    would otherwise be treated as a compatible endpoint and boot
    keyless."""
    monkeypatch.setenv("OPENAI_KEY", "secret")
    with pytest.raises(ProviderError, match='"base_url" must be a URL'):
        await build_asr(type="openai", api_key_env="OPENAI_KEY", base_url=base_url)


async def test_a_compatible_endpoint_keeps_its_own_temperature_range() -> None:
    """The range is a fact about OpenAI's models, not about the dialect,
    so guessing on a self-hosted server's behalf would reject a working
    configuration before the request is sent."""
    built = await build_asr(
        type="openai", base_url="http://localhost:8000/v1", temperature=2.0, reach="host"
    )
    assert isinstance(built, OpenAiAsr)


async def test_the_base_url_decides_the_reach_rather_than_the_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A self-hosted transcription server keeps the audio on the host and
    api.openai.com does not, so the type cannot know its own reach."""
    monkeypatch.setenv("OPENAI_KEY", "secret")
    assert OpenAiAsr.reach is None
    built = await build_asr(
        type="openai",
        api_key_env="OPENAI_KEY",
        base_url="http://localhost:8000/v1",
        reach="host",
    )
    assert isinstance(built, OpenAiAsr)


async def test_a_host_boundary_refuses_the_default_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_KEY", "secret")
    with pytest.raises(ProviderError, match="data boundary, which is host"):
        await build_entry(
            "asr",
            "ears",
            ProviderConfig.model_validate(
                {"type": "openai", "api_key_env": "OPENAI_KEY", "reach": "internet"}
            ),
            Reach.HOST,
        )


async def test_a_host_boundary_admits_a_local_endpoint_that_declares_itself() -> None:
    built = await build_entry(
        "asr",
        "ears",
        ProviderConfig.model_validate(
            {"type": "openai", "base_url": "http://localhost:8000/v1", "reach": "host"}
        ),
        Reach.HOST,
    )
    assert isinstance(built, OpenAiAsr)


async def test_a_network_boundary_admits_an_endpoint_on_the_network() -> None:
    """The tier the boolean could not say: a transcription server on the
    LAN is not on this host and is not the internet either, and an
    operator asserting exactly that is now telling the truth."""
    built = await build_entry(
        "asr",
        "ears",
        ProviderConfig.model_validate(
            {"type": "openai", "base_url": "http://whisper.lan:8000/v1", "reach": "network"}
        ),
        Reach.NETWORK,
    )
    assert isinstance(built, OpenAiAsr)


async def test_a_local_endpoint_needs_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """The SDK insists on a key; a self-hosted server usually does not."""
    monkeypatch.delenv("OPENAI_KEY", raising=False)
    built = await build_asr(type="openai", base_url="http://localhost:8000/v1")
    assert isinstance(built, OpenAiAsr)


# --- the refusals, word for word -------------------------------------
#
# Every way this type's factory can refuse an entry, pinned as the whole
# sentence rather than as a fragment of one. The conversion to a
# declared options model (#88) moved four of these from hand-built
# sentences in the builder to the shared validation rendering, and a
# `match=` against a few words could not have shown which ones moved or
# what they became. So the pins are exact and they are all here
# together: what a reader compares across that change is one table
# before and the same table after.
#
# Four moved and four did not, and which is which is the design read off
# a diff. What moved is everything that is a fact about a VALUE: an
# option this type does not declare, and a type the model refuses. What
# stayed is everything that is a fact about the ENDPOINT or about the
# environment: the missing key, the unset variable, the base_url that
# cannot be classified, and the temperature range, which is OpenAI's own
# and therefore conditional on the endpoint being OpenAI.
#
# The one thing lost in the move is the name of an unknown option, and
# it is lost on purpose rather than by accident: a key this repository
# did not declare is a key an operator invented, and printing it back
# is how a pasted credential reaches a boot log. The three types
# converted before this one answer the same way.
#
# The label in front of every one of them is the entry's own, which is
# what makes a bad option a five-second fix, and it is the half nothing
# here moves.

ENTRY = "providers.asr.ears"

# A variable this deployment does not have, for the one refusal that is
# about the environment rather than about the options.
UNSET_VARIABLE = "VINGA_OPENAI_ASR_PIN_UNSET"

REFUSED: list[tuple[str, dict[str, object], str]] = [
    (
        "no api_key_env at all",
        {},
        f'{ENTRY}: type "openai" needs an API key when it speaks to api.openai.com; '
        f'name the environment variable holding it with "api_key_env"',
    ),
    (
        "api_key_env naming nothing",
        {"api_key_env": UNSET_VARIABLE},
        f"{ENTRY}: api_key_env references an unset environment variable",
    ),
    (
        "an option this type does not have",
        {"api_key_env": "OPENAI_KEY", "beam_size": 1},
        f"invalid {ENTRY}:\n  - an unrecognized key is not permitted",
    ),
    (
        "a number where a string belongs",
        {"api_key_env": "OPENAI_KEY", "language": 5},
        f"invalid {ENTRY}:\n  - language: Input should be a valid string",
    ),
    (
        "a string where a number belongs",
        {"api_key_env": "OPENAI_KEY", "timeout_s": "soon"},
        f"invalid {ENTRY}:\n  - timeout_s: must be a number",
    ),
    (
        "a temperature outside the API's range, on OpenAI",
        {"api_key_env": "OPENAI_KEY", "temperature": 2.0},
        f'{ENTRY}: option "temperature" must be between 0.0 and 1.0',
    ),
    (
        "a base_url that is not a URL",
        {"api_key_env": "OPENAI_KEY", "base_url": "not-a-url"},
        f'{ENTRY}: option "base_url" must be a URL with a scheme and a host, '
        f'such as "https://api.openai.com/v1"',
    ),
    (
        "a null where a string with a default belongs",
        {"api_key_env": "OPENAI_KEY", "model": None},
        f"invalid {ENTRY}:\n  - model: Input should be a valid string",
    ),
    # The plural's own three, which are all facts about a value that
    # says nothing the endpoint can act on.
    (
        "an empty list of languages",
        {"api_key_env": "OPENAI_KEY", "languages": []},
        f"invalid {ENTRY}:\n  - languages: must be a non-empty list of language "
        f"codes, each written once",
    ),
    (
        "a language written twice",
        {"api_key_env": "OPENAI_KEY", "languages": ["sv", "sv"]},
        f"invalid {ENTRY}:\n  - languages: must be a non-empty list of language "
        f"codes, each written once",
    ),
    (
        "an entry that is not a language code",
        {"api_key_env": "OPENAI_KEY", "languages": ["not a language"]},
        f"invalid {ENTRY}:\n  - languages: must be a language code, such as sv or en-US",
    ),
    # And the cross-field one, which is the API's rule rather than this
    # repository's. Two lines because a model-level validator's error is
    # located at the model, so the rendering puts no field name in front
    # of either and each sentence names its own field. The write gate is
    # where this refusal matters and `test_config_store.py` is where
    # that is asserted; here it is the wording, beside the wording of
    # everything else this factory can say.
    (
        "both spellings of the language on one entry",
        {"api_key_env": "OPENAI_KEY", "language": "sv", "languages": ["sv", "en"]},
        f"invalid {ENTRY}:\n"
        f'  - "language" and "languages" cannot both be set: every model measured '
        f"answers 400 to a request naming both, so an entry writing both would "
        f"apply cleanly and fail on the first real transcription\n"
        f'  - "languages" is the form gpt-transcribe takes, and it is the one model '
        f"measured to accept it; whisper-1 and gpt-4o-mini-transcribe answered 400 "
        f'to it and take "language" instead',
    ),
]


@pytest.fixture
def environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """The environment every refusal below is judged against: one
    variable holding a key, and one name nothing holds."""
    monkeypatch.setenv("OPENAI_KEY", "secret")
    monkeypatch.delenv(UNSET_VARIABLE, raising=False)


@pytest.mark.parametrize(
    ("options", "sentence"),
    [(options, sentence) for _, options, sentence in REFUSED],
    ids=[name for name, _, _ in REFUSED],
)
@pytest.mark.usefixtures("environment")
async def test_a_refused_entry_says_exactly_this(
    options: dict[str, object], sentence: str
) -> None:
    with pytest.raises(ProviderError) as caught:
        await build_asr(type="openai", **options)

    assert str(caught.value) == sentence


ACCEPTED: list[tuple[str, dict[str, object]]] = [
    # Nothing but the key, which is the entry an operator writes first.
    ("nothing but a key", {"api_key_env": "OPENAI_KEY"}),
    # The spellings of absence this type's reader took, one per option
    # that has one. A deployment that wrote one of these has an entry
    # that builds today, so it is the compatibility surface the
    # conversion has to leave alone.
    ("a blank model", {"api_key_env": "OPENAI_KEY", "model": ""}),
    ("a blank language", {"api_key_env": "OPENAI_KEY", "language": ""}),
    ("a null language", {"api_key_env": "OPENAI_KEY", "language": None}),
    ("a blank prompt", {"api_key_env": "OPENAI_KEY", "prompt": ""}),
    ("a null prompt", {"api_key_env": "OPENAI_KEY", "prompt": None}),
    ("a null temperature", {"api_key_env": "OPENAI_KEY", "temperature": None}),
    # The plural on its own, which is the whole of what an entry that
    # describes a household writes.
    ("a list of languages", {"api_key_env": "OPENAI_KEY", "languages": ["sv", "en"]}),
    ("a list of one language", {"api_key_env": "OPENAI_KEY", "languages": ["sv"]}),
    # And the two knobs written as integers where the reader answered a
    # float, which is how an operator writes a whole number.
    ("a whole-number temperature", {"api_key_env": "OPENAI_KEY", "temperature": 1}),
    ("a whole-number timeout", {"api_key_env": "OPENAI_KEY", "timeout_s": 7}),
    # The range is OpenAI's, so a compatible endpoint keeps its own.
    (
        "a temperature outside OpenAI's range, off OpenAI",
        {"base_url": "http://localhost:8000/v1", "temperature": 2.0, "reach": "host"},
    ),
]


@pytest.mark.parametrize(
    "options",
    [options for _, options in ACCEPTED],
    ids=[name for name, _ in ACCEPTED],
)
@pytest.mark.usefixtures("environment")
async def test_an_entry_written_this_way_builds(options: dict[str, object]) -> None:
    """The other half of the pin, and the half a refusal table cannot
    carry: what a deployment may have written and must go on being able
    to write."""
    assert isinstance(await build_asr(type="openai", **options), OpenAiAsr)


def test_the_two_constants_the_model_restates_are_the_ones_that_ship() -> None:
    """The price of the options model living where no client library
    can be imported, paid here rather than left as a comment.

    `OpenaiAsrOptions` declares `base_url` and `timeout_s` as literals
    because `config/provider_options.py` weighs pydantic and
    `config.models` and nothing else: `openai_endpoint` imports the
    provider package and the kit speaks httpx. This file is on the side
    that may import both, which makes it the one place the two
    statements can be held against each other. The elevenlabs type pays
    the same price for the same timeout, in its own suite.
    """
    assert OpenaiAsrOptions.model_fields["base_url"].default == DEFAULT_BASE_URL
    assert OpenaiAsrOptions.model_fields["timeout_s"].default == DEFAULT_TIMEOUT_S


def test_the_language_syntax_the_model_restates_is_the_one_that_ships() -> None:
    """The third restatement, and the one whose other home is not a
    provider module.

    `languages` holds each code to the same syntax `LanguageTag` does,
    because that is the type a reported code becomes downstream and a
    second expression of one rule is a bug pending. The rule cannot be
    imported where it is enforced: `events/values.py` is deliberately
    outside the inventory of modules `config.cli` may load
    (`test_cli_import_weight.py`), so reaching for it would widen a set
    whose whole point is that widening it is a review event. This file
    may import both, which makes it the place the two statements can be
    held against each other, exactly as the base URL and the timeout
    above are.
    """
    from vinga_server.config import provider_options
    from vinga_server.config.provider_options import OptionsRefused, checked_options
    from vinga_server.events.values import LANGUAGE, EventValueError, LanguageTag

    assert provider_options.LANGUAGE_PATTERN == f"^{LANGUAGE.pattern}$"
    assert provider_options.LANGUAGE_MAX_LENGTH == LANGUAGE.max_length

    # And the claim in its own terms, so a pattern rewritten to spell
    # the same rule passes and one rewritten to spell another does not:
    # what the option accepts is what the value type holds, including
    # `not-a-language`, which both accept and which is the whole of why
    # this is a shape rather than a membership test.
    # Boundary cases carry this claim, not ordinary ones. The first
    # version of this case ran seven plain codes and passed while the
    # two homes genuinely disagreed: the restated pattern was anchored
    # with `$` and read with `match`, which admits a terminal newline
    # where the value type's `\Z` does not. So the list leads with the
    # whitespace edges, which is where two spellings of one rule come
    # apart.
    boundaries = ("en\n", "en\r", "en\n\n", "\nen", "en ", " en", "en\t")
    ordinary = ("sv", "en-US", "de_DE", "not-a-language", "s", "sv" * 9, "not a language")
    for code in boundaries + ordinary:
        held = True
        try:
            LanguageTag(code)
        except EventValueError:
            held = False
        accepted = True
        try:
            checked_options("invalid x:", "asr", "openai", {"languages": [code]})
        except OptionsRefused:
            accepted = False
        assert accepted is held, code


@pytest.mark.parametrize(
    ("entry", "asked_for"),
    [
        pytest.param({}, "gpt-transcribe", id="an entry naming no model"),
        pytest.param({"model": "whisper-1"}, "whisper-1", id="an entry naming one"),
    ],
)
@pytest.mark.usefixtures("environment")
async def test_the_model_on_the_wire_is_the_default_or_the_one_that_was_named(
    entry: dict[str, object], asked_for: str
) -> None:
    """The default's one home, read from the end that matters, and the
    entry that overrides it beside the entry that does not.

    The builder used to keep a `DEFAULT_MODEL` constant beside the
    field's job, and what makes the deletion safe is not that nothing
    imports it: it is that an entry naming no model still asks the API
    for the model the field declares. A second copy left behind would
    have kept this green while going stale.

    The default is spelled out here rather than read off the field,
    because the value is what every unconfigured deployment sends and
    an assertion against the field would agree with any rename. The
    field is asserted to be that same value in the line below, so the
    one-home claim survives alongside the literal.
    """
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"text": "Hej"})

    built = await build_asr(type="openai", api_key_env="OPENAI_KEY", **entry)
    assert isinstance(built, OpenAiAsr)
    await transported(built, handler).transcribe(ONE_SECOND, 16000)

    (request,) = seen
    assert form_field(request, "model") == asked_for
    if not entry:
        assert OpenaiAsrOptions.model_fields["model"].default == asked_for


@pytest.mark.usefixtures("environment")
async def test_a_refused_option_carries_nothing_of_what_was_written() -> None:
    """The no-leak lens on this factory's own refusals.

    A rejected option is exactly where a pasted credential lands, so the
    value is looked for in the sentence, in the repr, and through every
    cause and context a renderer could walk.

    Planted in a DECLARED field's rejected value, which is the half this
    case owns: `temperature` is this repository's own word and travels,
    and what was written under it is the caller's and may not. The other
    half, that a key an operator invented is not quoted back either,
    belongs to `test_an_unknown_option_fails_the_build` above and to the
    refusal table beside it, which assert the name's absence where the
    name is the thing at risk. This docstring used to claim the
    opposite, that an unknown key is deliberately named back; that was
    the reader's policy, and declaring the type's options ended it."""
    with pytest.raises(ProviderError) as caught:
        await build_asr(type="openai", api_key_env="OPENAI_KEY", temperature=SENTINEL)

    assert SENTINEL not in f"{caught.value!r}{chain(caught.value)}"


# --- the request -----------------------------------------------------


async def test_the_request_carries_the_model_and_key() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"text": "Hej hej"})

    result = await provider(handler).transcribe(ONE_SECOND, 16000)

    (request,) = seen
    assert request.method == "POST"
    assert request.url.path == "/v1/audio/transcriptions"
    assert request.headers["authorization"] == "Bearer test-key"
    assert form_field(request, "model") == "gpt-4o-mini-transcribe"
    assert form_field(request, "response_format") == "json"
    assert result.text == "Hej hej"


async def test_the_audio_is_uploaded_as_wav_at_the_rate_it_was_given() -> None:
    """The header carries the rate from the call, so the provider follows
    whatever the pipeline runs at rather than pinning one."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"text": ""})

    await provider(handler).transcribe(b"\x01\x02" * 4800, 24000)

    with wave.open(io.BytesIO(uploaded_audio(seen[0])), "rb") as container:
        assert container.getframerate() == 24000
        assert container.getnchannels() == 1
        assert container.getsampwidth() == 2
        assert container.readframes(4800) == b"\x01\x02" * 4800


async def test_the_upload_is_named_so_the_api_can_read_the_format() -> None:
    """There is no file, but the endpoint decides the format from the
    extension, so the name it is given still has to be right."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"text": ""})

    await provider(handler).transcribe(ONE_SECOND, 16000)
    assert b'filename="utterance.wav"' in seen[0].content


async def test_optional_fields_are_sent_only_when_configured() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"text": ""})

    await provider(handler).transcribe(ONE_SECOND, 16000)
    assert form_field(seen[0], "language") is None
    assert form_field(seen[0], "prompt") is None
    assert form_field(seen[0], "temperature") is None
    # The plural is the one that has to be absent rather than empty:
    # whisper-1 and gpt-4o-mini-transcribe answer 400 to the key itself,
    # so an unset option that still put something on the wire would
    # break every entry naming one of them.
    assert form_fields(seen[0], "languages[]") == []
    assert form_field(seen[0], "languages") is None

    configured = provider(handler, language="sv", prompt="vinga", temperature=0.2)
    await configured.transcribe(ONE_SECOND, 16000)
    assert form_field(seen[1], "language") == "sv"
    assert form_field(seen[1], "prompt") == "vinga"
    assert form_field(seen[1], "temperature") == "0.2"


async def test_a_configured_language_beats_the_session_hint() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"text": ""})

    await provider(handler, language="sv").transcribe(ONE_SECOND, 16000, language_hint="en")
    assert form_field(seen[0], "language") == "sv"

    await provider(handler).transcribe(ONE_SECOND, 16000, language_hint="en")
    assert form_field(seen[1], "language") == "en"


# --- what it reports -------------------------------------------------


async def test_the_transcript_is_stripped() -> None:
    result = await provider(transcript_handler("  Hej hej  \n")).transcribe(ONE_SECOND, 16000)
    assert result.text == "Hej hej"


# --- an echoed prompt ------------------------------------------------


async def test_a_transcript_that_is_the_prompt_is_treated_as_nothing_said() -> None:
    """The model hands the prompt back on short or low-content audio.
    It reached a field session as an utterance the user never said, and
    the prompt named the agents, so the model read it as a request and
    handed over."""
    asr = provider(
        transcript_handler("vinga, Oliver, Greta, Mateo"),
        prompt="vinga, Oliver, Greta, Mateo",
    )
    assert (await asr.transcribe(ONE_SECOND, 16000)).text == ""


async def test_the_echo_is_matched_trimmed_and_case_insensitively() -> None:
    asr = provider(transcript_handler("  VINGA, oliver  \n"), prompt=" vinga, Oliver ")
    assert (await asr.transcribe(ONE_SECOND, 16000)).text == ""


async def test_an_echo_written_as_a_sentence_is_still_an_echo() -> None:
    """The model is transcribing, so it sometimes ends the prompt it
    hands back with a full stop. Seen once in 45 provoked echoes."""
    asr = provider(
        transcript_handler("Vinga, Oliver, Greta, Mateo."),
        prompt="vinga, Oliver, Greta, Mateo",
    )
    assert (await asr.transcribe(ONE_SECOND, 16000)).text == ""


async def test_a_transcript_that_merely_contains_the_prompt_is_kept() -> None:
    """Someone can say the words in the prompt. Only a transcript that
    is the prompt and nothing else is an echo."""
    asr = provider(transcript_handler("vinga, are you there?"), prompt="vinga")
    assert (await asr.transcribe(ONE_SECOND, 16000)).text == "vinga, are you there?"


async def test_an_entry_with_no_prompt_suppresses_nothing() -> None:
    asr = provider(transcript_handler("vinga"))
    assert (await asr.transcribe(ONE_SECOND, 16000)).text == "vinga"


# --- what the ear says it was sent ------------------------------------


async def test_a_transcription_reports_the_audio_it_actually_submitted() -> None:
    """The ordinary case: one request, the whole clip, counted in
    milliseconds.

    It is a separate number from how long the user spoke, and the two
    cases below are why: this adapter can send nothing at all and can
    send the same clip twice, and a billing number taken from the
    utterance is wrong in both directions.
    """
    result = await provider(transcript_handler()).transcribe(ONE_SECOND, 16000)

    assert result.submitted_ms == 1000


async def test_audio_under_the_floor_is_billed_for_nothing() -> None:
    """A clip below the endpoint's own minimum never leaves this
    process, so the ear was sent nothing and says so.

    Zero rather than no answer, which is the distinction this field
    exists to make: the floor is a fact this adapter knows, and an
    absent measurement would claim it did not. What it must NOT say is
    the clip's own length, which is the cost this transcription would
    have had if it had happened.
    """
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"text": "Hej"})

    # Half the 0.1 s floor, so nothing is sent at all.
    result = await provider(handler).transcribe(b"\x00\x00" * 800, 16000)

    assert seen == [], "the adapter sent a clip it said was under the floor"
    assert result.submitted_ms == 0
    assert result.submitted_ms != 50, "the clip's own length was reported as usage"


async def test_an_echo_retry_is_billed_for_both_hearings() -> None:
    """The same bytes twice is twice the usage.

    The retry re-sends the clip rather than a part of it, so an operator
    reading cost off the utterance would see half of what the vendor
    charged, on exactly the short acknowledgements the echo guard fires
    on most.
    """
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        text = "vinga, Oliver" if len(seen) == 1 else "Yes, please."
        return httpx.Response(200, json={"text": text})

    result = await provider(handler, prompt="vinga, Oliver").transcribe(ONE_SECOND, 16000)

    assert len(seen) == 2, "the echo retry did not run, so this proves nothing"
    assert result.text == "Yes, please."
    assert result.submitted_ms == 2000


# --- the retry behind the echo guard (#69) ---------------------------


async def test_an_echo_is_retried_without_the_prompt_and_the_retry_is_heard(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The field test behind #69: a user answers "yes, please", the
    model echoes the prompt, and the guard used to treat the echo as
    proof of silence. The same clip transcribes fine without the
    prompt's help, so the retry's transcript is the one the session
    hears."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        text = "vinga, Oliver" if len(seen) == 1 else "Yes, please."
        return httpx.Response(200, json={"text": text})

    asr = provider(handler, prompt="vinga, Oliver", language="sv", temperature=0.2)
    with caplog.at_level("INFO"):
        result = await asr.transcribe(ONE_SECOND, 16000)

    assert result.text == "Yes, please."
    assert len(seen) == 2
    # The retry withholds only the prompt; the pinned language and the
    # temperature still steer the second hearing like the first.
    assert form_field(seen[0], "prompt") == "vinga, Oliver"
    assert form_field(seen[1], "prompt") is None
    assert form_field(seen[1], "language") == "sv"
    assert form_field(seen[1], "temperature") == "0.2"
    (event,) = [r for r in caplog.records if getattr(r, "event", None) == "asr_prompt_echo"]
    assert event.outcome == "recovered"  # type: ignore[attr-defined]
    assert event.duration_s == 1.0  # type: ignore[attr-defined]


async def test_a_recovered_transcript_reaches_no_record_or_consumer(
    caplog: pytest.LogCaptureFixture, tap: Tap
) -> None:
    """The sentinel for the one echo-guard outcome that has a transcript
    in hand. It used to be quoted into the `recovered` sentence, and
    conversation-derived text is banned on the events without exception
    (the content-and-telemetry ADR, as amended 2026-08-17): a transcript
    is content however it was recovered. Planted as a credential,
    because that is what the ban is worth: a user reading a key aloud is
    a turn like any other, and the retained log is not where it belongs.

    Both retained surfaces, because a clean record does not prove a
    clean consumer: the tap sees the emission before the log does.

    And every record rather than the event's, because the retained log
    is the whole log. This path writes plain `logger` calls beside its
    events (the retry announcement is one of them, on the very branch
    that has the transcript in hand), and a sentinel that filtered to
    `asr_prompt_echo` first would watch one line and bless the file."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        text = "vinga, Oliver" if len(seen) == 1 else RECOVERED
        return httpx.Response(200, json={"text": text})

    asr = provider(handler, prompt="vinga, Oliver")
    with caplog.at_level("DEBUG"):
        result = await asr.transcribe(ONE_SECOND, 16000)

    # The session is supposed to hear it. The surfaces are not.
    assert result.text == RECOVERED
    assert len(seen) == 2

    # Every line the run wrote, whatever channel it landed on and
    # whether or not it was an event.
    assert caplog.records, "nothing was logged at all, so this proves nothing"
    for record in caplog.records:
        assert RECOVERED not in surfaces(record), record.name

    records = emitted(caplog, "asr_prompt_echo")
    assert records, "the guard never fired, so this proves nothing"
    for record in records:
        assert record.outcome == "recovered"  # type: ignore[attr-defined]

    consumed = tap.saw("asr_prompt_echo")
    assert consumed, "it reached no tap at all, so this proves nothing"
    for emission in consumed:
        assert emission.payload["outcome"] == "recovered"
        assert RECOVERED not in emission.message
        assert RECOVERED not in repr(emission.args)
        assert RECOVERED not in str(emission.payload)
    assert RECOVERED not in tap.rendered()

    # And the diagnosis survives it: how much audio the guard was about
    # to discard, and what the second hearing cost.
    (event,) = records
    assert event.duration_s == 1.0  # type: ignore[attr-defined]
    assert event.retry_ms >= 0  # type: ignore[attr-defined]


async def test_a_retry_that_echoes_again_confirms_nothing_was_said(
    caplog: pytest.LogCaptureFixture,
) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"text": "vinga, Oliver"})

    asr = provider(handler, prompt="vinga, Oliver")
    with caplog.at_level("INFO"):
        result = await asr.transcribe(ONE_SECOND, 16000)

    assert result.text == ""
    assert len(seen) == 2
    (event,) = [r for r in caplog.records if getattr(r, "event", None) == "asr_prompt_echo"]
    assert event.outcome == "confirmed_echo"  # type: ignore[attr-defined]


async def test_a_retry_that_comes_back_empty_confirms_the_silence(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Genuine silence or noise transcribes to nothing once the prompt
    is withheld, which is the guard's original story confirmed."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        text = "vinga, Oliver" if len(seen) == 1 else ""
        return httpx.Response(200, json={"text": text})

    asr = provider(handler, prompt="vinga, Oliver")
    with caplog.at_level("INFO"):
        result = await asr.transcribe(ONE_SECOND, 16000)

    assert result.text == ""
    assert len(seen) == 2
    (event,) = [r for r in caplog.records if getattr(r, "event", None) == "asr_prompt_echo"]
    assert event.outcome == "confirmed_empty"  # type: ignore[attr-defined]


async def test_a_transcript_that_is_not_the_prompt_is_never_retried(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Only the tripped guard pays for a second round trip; the normal
    path stays one request per utterance."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"text": "Hej hej"})

    asr = provider(handler, prompt="vinga, Oliver")
    with caplog.at_level("INFO"):
        result = await asr.transcribe(ONE_SECOND, 16000)

    assert result.text == "Hej hej"
    assert len(seen) == 1
    assert not [r for r in caplog.records if getattr(r, "event", None) == "asr_prompt_echo"]


async def test_every_timeout_reaching_the_transport_is_a_real_number() -> None:
    """The per-request timeout is a client option, not a form field, so
    it may never carry the Omit serialization sentinel the neighbouring
    fields use: Omit is not a NotGiven to the SDK, so it flows through
    to httpx as the literal connect timeout and fails every ordinary
    call at connect time. A mock transport never connects, which is how
    the suite missed it and the deployment did not (#75); what the
    transport CAN see is the request's timeout extension, so this pins
    every phase of it to a real number or None, on the ordinary path
    where no per-request timeout is given at all."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"text": "Hej hej"})

    asr = provider(handler)
    await asr.transcribe(ONE_SECOND, 16000)

    (request,) = seen
    for phase, value in request.extensions["timeout"].items():
        assert value is None or isinstance(value, (int, float)), (phase, value)


async def test_the_retry_lives_on_what_the_first_request_left_of_the_timeout() -> None:
    """Client retries are off so timeout_s bounds the user's wait, and
    a retry with a fresh timeout of its own would quietly double that
    bound. The retry request therefore carries the remaining budget as
    its own deadline."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        text = "vinga, Oliver" if len(seen) == 1 else "Yes, please."
        return httpx.Response(200, json={"text": text})

    asr = provider(handler, prompt="vinga, Oliver", timeout_s=30.0)
    result = await asr.transcribe(ONE_SECOND, 16000)

    assert result.text == "Yes, please."
    # httpx carries the per-request override in the request extensions,
    # which is where the far end of the mock transport can see it.
    assert seen[1].extensions["timeout"]["read"] <= 30.0


async def test_an_echo_with_no_budget_left_is_not_retried(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A first request that ate nearly the whole timeout leaves the
    retry more likely to be cut off than to answer, so it is skipped
    and the clip discarded directly rather than making the user wait
    out a request that was never going to land."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        # The discarded response reports a language, so a provider that
        # kept the first hearing's half would be visible here rather
        # than only on the two outcomes that answer a second response.
        return httpx.Response(200, json={"text": "vinga, Oliver", "languages": [{"code": "en"}]})

    # The budget is below the one-second retry floor before the first
    # request even starts, which stands in for a first request that
    # consumed almost all of a real timeout without a slow test.
    asr = provider(handler, prompt="vinga, Oliver", timeout_s=0.5)
    with caplog.at_level("INFO"):
        result = await asr.transcribe(ONE_SECOND, 16000)

    assert result.text == ""
    assert result.language is None
    assert len(seen) == 1
    (event,) = [r for r in caplog.records if getattr(r, "event", None) == "asr_prompt_echo"]
    assert event.outcome == "skipped"  # type: ignore[attr-defined]
    assert not hasattr(event, "retry_ms")


async def test_the_deadline_is_absolute_rather_than_per_connection_phase(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The SDK's timeout argument is an httpx timeout, which is per
    phase: passed alone, the retry could spend the remaining budget on
    each of connect, write and read. The asyncio deadline around the
    request is what makes the budget end to end, so a retry that keeps
    one phase alive without answering is still cut off when the shared
    budget runs out. The mock transport enforces no httpx timeout at
    all, so this test hangs for the whole sleep if the absolute
    deadline is ever removed."""
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            # Reporting a language, for the reason the skipped case
            # gives: a cut-off retry answers no text, so it answers no
            # language either.
            return httpx.Response(
                200, json={"text": "vinga, Oliver", "languages": [{"code": "en"}]}
            )
        # Far longer than the whole budget, inside what would be a
        # single read phase.
        await asyncio.sleep(30)
        return httpx.Response(200, json={"text": "never delivered"})

    # A tiny budget keeps the test fast; the floor comes down with it
    # so the retry is still sent rather than skipped.
    monkeypatch.setattr(openai_asr, "RETRY_FLOOR_S", 0.0)
    asr = provider(handler, prompt="vinga, Oliver", timeout_s=0.05)
    loop = asyncio.get_running_loop()
    with caplog.at_level("INFO"):
        started = loop.time()
        result = await asr.transcribe(ONE_SECOND, 16000)
        elapsed = loop.time() - started

    assert result.text == ""
    assert result.language is None
    assert calls == 2
    assert elapsed < 1.0
    (event,) = [r for r in caplog.records if getattr(r, "event", None) == "asr_prompt_echo"]
    assert event.outcome == "timed_out"  # type: ignore[attr-defined]


async def test_a_retry_cut_off_by_the_deadline_discards_rather_than_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The reply a timed-out retry would end is one the guard was about
    to end anyway, so the timeout is the discarding outcome rather than
    an error surfaced to the session. Raised by the transport here, so
    this pins the SDK's own timeout class beside the asyncio deadline
    the test above pins."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if len(seen) == 1:
            return httpx.Response(
                200, json={"text": "vinga, Oliver", "languages": [{"code": "en"}]}
            )
        raise httpx.ReadTimeout("the deadline came first", request=request)

    asr = provider(handler, prompt="vinga, Oliver")
    with caplog.at_level("INFO"):
        result = await asr.transcribe(ONE_SECOND, 16000)

    assert result.text == ""
    assert result.language is None
    assert len(seen) == 2
    (event,) = [r for r in caplog.records if getattr(r, "event", None) == "asr_prompt_echo"]
    assert event.outcome == "timed_out"  # type: ignore[attr-defined]
    assert event.retry_ms >= 0  # type: ignore[attr-defined]


# --- the language the model heard -------------------------------------


async def test_the_language_the_model_reports_reaches_the_record() -> None:
    """Unhinted, the report is a detection, and it is the one thing this
    provider could not say before: an operator watching a pipeline
    mishear Swedish as English had nothing on any surface to see it
    with.

    The confidence and the lock stay empty beside it, and neither is an
    oversight: no model reports a confidence at all, and the
    session-scoped lock exists to spare a local encoder pass there is
    none of here."""
    asr = provider(reporting_handler([{"code": "de"}]))
    result = await asr.transcribe(ONE_SECOND, 16000)
    seen, record = downstream(asr, result)

    assert result.language == "de"
    assert result.language_confidence is None
    assert result.lock_language is None
    (heard,) = seen.saw("heard")
    assert heard.payload["language"] == "de"
    assert record is not None
    assert record.language == "de"


@pytest.mark.parametrize(
    ("configured", "hint"),
    [
        pytest.param({"language": "sv"}, None, id="configured"),
        pytest.param({}, "sv", id="hinted"),
        pytest.param({"language": "sv"}, "en", id="both"),
    ],
)
async def test_a_language_this_request_named_is_never_reported_back(
    configured: dict[str, object], hint: str | None
) -> None:
    """Told a single language, `gpt-transcribe` hands that code back
    rather than saying what it heard: measured against the live endpoint
    on 2026-09-13, German speech sent with `language: sv` answered
    `languages: [{"code": "sv"}]`. So a code is evidence about the audio
    only where this request named none, and filling the field regardless
    would put an entry's own configuration into a metric under the name
    of a measurement.

    The session hint suppresses it for the same reason and not by
    accident: it reaches the request as `language`, which is the same
    thing the model is told."""
    asr = provider(reporting_handler([{"code": "sv"}]), **configured)
    result = await asr.transcribe(ONE_SECOND, 16000, language_hint=hint)
    seen, record = downstream(asr, result)

    assert result.language is None
    assert "language" not in only_heard(seen).payload
    assert record is not None
    assert record.language is None


async def test_a_blank_language_names_nothing_and_suppresses_nothing() -> None:
    """`language: ""` is a spelling this type has always accepted, and
    it puts no field on the wire: the request names no language, so what
    comes back is a detection like any other.

    The claim under it is that the suppression is read off the value the
    request sent rather than off the configured one. Those are two
    structures that have to agree, and this is the case where a rule
    written over the configuration instead would disagree with the
    request it is about.
    """
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"text": "Hej hej", "languages": [{"code": "de"}]})

    result = await provider(handler, language="").transcribe(ONE_SECOND, 16000)

    assert form_field(seen[0], "language") is None
    assert result.language == "de"


async def test_a_clip_with_no_speech_in_it_reports_no_language() -> None:
    """An empty list is the endpoint's own spelling of "I heard no
    language", answered on silence and on laughter, and it maps onto the
    absent field without a rule of ours."""
    asr = provider(reporting_handler([], text="..."))
    result = await asr.transcribe(ONE_SECOND, 16000)
    seen, record = downstream(asr, result)

    assert result.language is None
    assert "language" not in only_heard(seen).payload
    assert record is not None
    assert record.language is None


# The malformed answers an endpoint can give, each with the string a
# reader could recognize it by where it has one, so the claim that
# nothing of it survives is checked rather than assumed. `None` is for
# the two shapes that carry no recognizable value: no key at all, and a
# code that is the empty string.
MALFORMED = [
    pytest.param(ABSENT_KEY, None, id="no key at all"),
    pytest.param("nevervalid", "nevervalid", id="a string where the list belongs"),
    pytest.param(["nevervalid"], "nevervalid", id="a list of bare strings"),
    pytest.param([{"language": "nevervalid"}], "nevervalid", id="an entry with no code"),
    pytest.param([{"code": 5550123}], "5550123", id="a code that is not a string"),
    pytest.param([{"code": ""}], None, id="an empty code"),
    pytest.param([{"code": "nevervalid" * 4}], "nevervalid", id="an overlong code"),
    pytest.param([{"code": "de"}, {"code": "en"}], None, id="two entries"),
]


@pytest.mark.parametrize(("reported", "marker"), MALFORMED)
async def test_a_malformed_report_costs_one_field_and_nothing_else(
    reported: object, marker: str | None, caplog: pytest.LogCaptureFixture
) -> None:
    """Asserted down the path production takes, because that is the path
    that decides what a malformed code costs, and it is not what this
    plan first claimed.

    `LanguageTag("")` and a forty-character value both raise, and
    `events/assembly.py` constructs one without catching. But the site
    hands `SessionEvents.emit` a THUNK, so the construction happens
    inside the emitter's guard: a refusal is reported and the whole
    `heard` event is dropped, and the reply carries on. The turn record
    has no such guard and no value type either. So an unnormalized code
    costs the event that carries this turn's duration, its `asr_ms` and
    its submitted audio, and puts the far side's string into a durable
    record and onto the read surface over it, for a field whose absence
    means only that the language was not learned. That is the trade this
    normalization exists to refuse.

    What is asserted here is that none of it happens: the event
    survives, carries no language, the record carries none either, and
    nothing of what the endpoint answered reaches any of the retained
    surfaces."""
    handler = transcript_handler() if reported is ABSENT_KEY else reporting_handler(reported)
    asr = provider(handler)
    with caplog.at_level(logging.DEBUG):
        result = await asr.transcribe(ONE_SECOND, 16000)
        seen, record = downstream(asr, result)

    assert result.text == "Hej hej"
    assert result.language is None
    # The event is here at all, which is the half an implementation
    # without the normalization loses: the guard would have dropped it.
    assert "language" not in only_heard(seen).payload
    assert record is not None
    assert record.language is None
    if marker is not None:
        assert marker not in seen.rendered()
        assert marker not in caplog.text


async def test_the_recovered_hearing_carries_its_own_language() -> None:
    """The retry's transcript and the retry's language, never the
    discarded response's beside the recovered text.

    The two responses report different codes on purpose: a provider that
    let the language travel as a variable the two paths both assign
    would hand back the recovered words labelled with the language of a
    response it threw away, and no test of a single response would see
    it."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if len(seen) == 1:
            return httpx.Response(200, json={"text": "vinga", "languages": [{"code": "en"}]})
        return httpx.Response(200, json={"text": "Ja tack", "languages": [{"code": "sv"}]})

    asr = provider(handler, prompt="vinga")
    result = await asr.transcribe(ONE_SECOND, 16000)

    assert result.text == "Ja tack"
    assert result.language == "sv"
    assert only_heard(downstream(asr, result)[0]).payload["language"] == "sv"


@pytest.mark.parametrize(
    "outcome",
    [
        pytest.param("vinga", id="the echo confirmed"),
        pytest.param("", id="the retry empty"),
    ],
)
async def test_a_discarded_hearing_answers_no_language(outcome: str) -> None:
    """The outcomes that discard answer no text, so they answer no
    language: a turn nothing was heard in is not a turn to label."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        text = "vinga" if len(seen) == 1 else outcome
        return httpx.Response(200, json={"text": text, "languages": [{"code": "en"}]})

    result = await provider(handler, prompt="vinga").transcribe(ONE_SECOND, 16000)

    assert result.text == ""
    assert result.language is None


# --- the languages a household speaks ---------------------------------


async def test_the_languages_list_is_sent_as_repeated_parts_in_the_order_written() -> None:
    """How the list reaches the endpoint, asserted on the bytes.

    Three claims, and the first two need the repeated-part reader
    because the SDK serializes `extra_body={"languages": [...]}` into
    one part per element named `languages[]`. There is no scalar
    `languages` part and no comma-joined one, which is what a test built
    on `form_field` would have failed to notice; and the order is the
    order the entry wrote, since the endpoint is free to weigh it and
    reordering here would be this provider inventing a policy.

    The third is that no singular `language` part is sent beside them.
    That is the combination the endpoint refuses, and it is the one an
    entry with this option set must never produce.
    """
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"text": "Hej"})

    # Written in an order that is not the sorted one, which is what
    # makes the order claim say anything: with [de, en] a provider that
    # sorted on the way out would agree with this case.
    await provider(handler, languages=["sv", "de"]).transcribe(ONE_SECOND, 16000)

    (request,) = seen
    assert form_fields(request, "languages[]") == ["sv", "de"]
    assert form_field(request, "languages") is None
    assert form_field(request, "language") is None
    # And not one field holding both, which is the shape a hand-rolled
    # serialization would have produced and the endpoint would refuse.
    assert b"sv,de" not in request.content


async def test_a_session_hint_is_not_sent_beside_a_configured_list() -> None:
    """The precedence the options model cannot enforce, because the hint
    is not written anywhere it can see.

    `language_hint` arrives per call from the session, and the lock that
    sets it is session-scoped and deliberately survives an agent switch,
    so a session whose first agent transcribes with `faster_whisper`
    hands one to an agent using this type. Sent as `language` beside a
    `languages` list it would be exactly the pair the endpoint refuses,
    which is a conversation failing for a reason no log explains. So
    while `languages` is set the hint is not sent at all, in either
    spelling.

    Asserted on the echo retry as well as on the first request, because
    the retry composes its own call: a precedence written once in
    `transcribe` and forgotten in the retry would 400 only on the clips
    the echo guard already found suspicious.
    """
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        text = "vinga" if len(seen) == 1 else "Ja tack"
        return httpx.Response(200, json={"text": text})

    asr = provider(handler, languages=["sv", "de"], prompt="vinga")
    result = await asr.transcribe(ONE_SECOND, 16000, language_hint="en")

    assert result.text == "Ja tack"
    assert len(seen) == 2, "the echo guard did not retry, so the retry is untested"
    for request in seen:
        assert form_field(request, "language") is None
        assert form_fields(request, "languages[]") == ["sv", "de"]


@pytest.mark.parametrize(
    ("languages", "reported"),
    [
        pytest.param(["de"], None, id="a list of one is a pin"),
        pytest.param(["de", "en"], "de", id="a list of two is a choice"),
    ],
)
async def test_what_a_set_reports_depends_on_how_many_it_names(
    languages: list[str], reported: str | None
) -> None:
    """The report rule, extended by this option rather than rewritten.

    The rule is about what the request NAMED. Told a single language the
    model hands that code straight back rather than saying what it
    heard, and a list of exactly one is such a single language however
    it is spelled: a legitimate way to write "this household speaks
    German", and what an operator migrating from `language` writes. Told
    two or more the model chooses between them, and what comes back is
    which one it chose, which is a detection inside a declared set.

    Both ids answer the same `languages: [{"code": "de"}]`, so what
    separates them is the rule and not the response.
    """
    asr = provider(reporting_handler([{"code": "de"}]), languages=languages)
    result = await asr.transcribe(ONE_SECOND, 16000)
    seen, record = downstream(asr, result)

    assert result.language == reported
    assert only_heard(seen).payload.get("language") == reported
    assert record is not None
    assert record.language == reported


# --- audio too short to send -----------------------------------------


async def test_audio_under_the_api_minimum_is_answered_without_a_request() -> None:
    """The barge-in path transcribes snippets of tens of milliseconds to
    decide whether an interruption was real. The API refuses those, and
    the refusal would be logged as a failure rather than the non-answer
    it is."""
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"text": "should not be reached"})

    asr = provider(handler)
    # 50 ms at 16 kHz, under the API's 0.1 s minimum.
    result = await asr.transcribe(b"\x00\x00" * 800, 16000)
    assert result.text == ""
    assert calls == 0

    # 100 ms exactly is sent.
    await asr.transcribe(b"\x00\x00" * 1600, 16000)
    assert calls == 1


async def test_the_minimum_belongs_to_the_endpoint_not_the_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The 0.1 s floor was measured against OpenAI, so it is applied
    only there, like the model rules and the temperature range."""
    monkeypatch.setenv("OPENAI_KEY", "secret")
    # 50 ms at 16 kHz: under the floor OpenAI was measured against.
    short = b"\x00\x00" * 800
    at_openai: list[bytes] = []
    at_compatible: list[bytes] = []

    def watching(seen: list[bytes]) -> object:
        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.content)
            return httpx.Response(200, json={"text": "ja"})

        return handler

    openai = await build_asr(type="openai", api_key_env="OPENAI_KEY")
    compatible = await build_asr(
        type="openai", base_url="http://localhost:8000/v1", reach="host"
    )
    assert isinstance(openai, OpenAiAsr)
    assert isinstance(compatible, OpenAiAsr)
    transported(openai, watching(at_openai))
    transported(compatible, watching(at_compatible))

    assert (await openai.transcribe(short, 16000)).text == ""
    assert at_openai == [], "the clip went to OpenAI, which would refuse it"
    assert (await compatible.transcribe(short, 16000)).text == "ja"
    assert len(at_compatible) == 1


async def test_a_compatible_endpoint_receives_the_short_clip_openai_would_refuse() -> None:
    """A self-hosted server may accept shorter audio, and dropping a clip
    it would have answered would silently suppress a barge-in it could
    have confirmed."""
    seen: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.content)
        return httpx.Response(200, json={"text": "ja"})

    built = await build_asr(type="openai", base_url="http://localhost:8000/v1", reach="host")
    assert isinstance(built, OpenAiAsr)
    transported(built, handler)

    # 50 ms: refused by OpenAI, and dropped by the guard against it.
    result = await built.transcribe(b"\x00\x00" * 800, 16000)
    assert len(seen) == 1
    assert result.text == "ja"


async def test_empty_audio_is_never_sent_anywhere() -> None:
    """Not even to an endpoint that declared no minimum: there is
    nothing in the buffer to transcribe."""
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"text": "should not be reached"})

    built = await build_asr(type="openai", base_url="http://localhost:8000/v1", reach="host")
    assert isinstance(built, OpenAiAsr)
    transported(built, handler)

    assert (await built.transcribe(b"", 16000)).text == ""
    assert calls == 0


async def test_the_minimum_follows_the_sample_rate() -> None:
    """Bytes are not milliseconds: the same buffer is long enough at
    16 kHz and too short at 48 kHz."""
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"text": ""})

    asr = provider(handler)
    await asr.transcribe(b"\x00\x00" * 1600, 16000)
    assert calls == 1
    await asr.transcribe(b"\x00\x00" * 1600, 48000)
    assert calls == 1


# --- failures --------------------------------------------------------


async def test_an_api_error_raises_the_taxonomy_with_the_status_and_no_body() -> None:
    """The taxonomy applies to the failure of transcribe as a whole. The
    status and the SDK class are trusted metadata; the vendor's own
    sentence is not, because the SDK embeds the response body in it and
    a compatible endpoint decides what that body says (#137)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": f"invalid api key {SENTINEL}"}})

    with pytest.raises(ProviderCallError) as failure:
        await provider(handler).transcribe(ONE_SECOND, 16000)

    assert not isinstance(failure.value, ProviderCallTimeout)
    assert "HTTP 401" in str(failure.value)
    # The SDK's own class for a 401, which is the half of the message
    # that says what kind of failure it was.
    assert "AuthenticationError" in str(failure.value)
    assert SENTINEL not in chain(failure.value)


async def test_a_first_request_that_timed_out_surfaces_as_a_timeout() -> None:
    """The other half of the split the echo retry forces: a timeout on
    the request that opens the call is a failure the session hears
    about, while a timeout inside the echo retry stays the discarding
    outcome the test below pins."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("the endpoint never answered", request=request)

    with pytest.raises(ProviderCallTimeout, match="APITimeoutError"):
        await provider(handler).transcribe(ONE_SECOND, 16000)


async def test_a_non_sdk_failure_passes_through_unwrapped() -> None:
    """The taxonomy claims request failures, not all failures: a bug in
    this process must reach logger.exception as itself.

    Raised by a client double rather than by the mock transport, because
    this provider reads the whole response inside the SDK's request
    path, and the SDK converts everything raised down there into an
    APIConnectionError of its own before this provider sees it. A bug in
    the calling code above it is what remains, and this is it."""

    class Transcriptions:
        async def create(self, **_options: object) -> object:
            raise ValueError("a local bug")

    client = type(
        "Client", (), {"audio": type("Audio", (), {"transcriptions": Transcriptions()})()}
    )()
    asr = OpenAiAsr(model="gpt-4o-mini-transcribe", api_key="test-key", client=client)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="a local bug"):
        await asr.transcribe(ONE_SECOND, 16000)


async def test_a_failed_request_leaks_nothing_into_the_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"message": f"upstream said {SENTINEL}"}})

    with caplog.at_level("DEBUG"), pytest.raises(ProviderCallError) as failure:
        await provider(handler).transcribe(ONE_SECOND, 16000)

    assert SENTINEL not in chain(failure.value)
    assert SENTINEL not in caplog.text
    assert all(SENTINEL not in str(record.__dict__) for record in caplog.records)


async def test_a_failing_utterance_is_attempted_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """The SDK retries twice by default, which would make timeout_s a
    third of the truth: three attempts plus backoff with the user
    waiting on an answer that is already late."""
    monkeypatch.setenv("OPENAI_KEY", "secret")
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(500, json={"error": {"message": "upstream boom"}})

    built = await build_asr(type="openai", api_key_env="OPENAI_KEY")
    assert isinstance(built, OpenAiAsr)
    transported(built, handler)

    with pytest.raises(ProviderCallError):
        await built.transcribe(ONE_SECOND, 16000)
    assert attempts == 1


async def test_the_timeout_is_the_one_the_entry_asked_for(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_KEY", "secret")
    built = await build_asr(type="openai", api_key_env="OPENAI_KEY", timeout_s=7)
    assert isinstance(built, OpenAiAsr)
    # White-box, deliberately: a deployment's client is built inside the
    # provider and handed to nobody, so its timeout and its retry budget
    # are observable only against the real vendor. What they bound is one
    # turn's worst case, which is why they are asserted at all.
    assert built._client.timeout == 7  # type: ignore[attr-defined]
    assert built._client.max_retries == 0  # type: ignore[attr-defined]


async def test_a_falsey_injected_client_is_still_the_one_used() -> None:
    """`client or ...` drops a double that answers False to a truth test,
    which any object defining __bool__ or __len__ does, and builds a real
    client in its place. Asked the way a caller would see it: the
    transcript only arrives if the request went to the injected client's
    transport, and a dropped one would have gone to OpenAI."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"text": "Hej hej"})

    asr = provider(handler, client=Falsey(mock_client(handler)))

    assert (await asr.transcribe(ONE_SECOND, 16000)).text == "Hej hej"
    assert len(seen) == 1
