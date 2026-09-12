"""The reach marking and the server.data_boundary boot check (#30, #493).

Every provider type carries a class-level `reach` marking of its own,
and the operator declares the outermost reach session data may have.
The one rule is a rank comparison: `host < network < internet`, and a
reach exceeding the boundary fails the boot with an error naming the
stage and the provider. A class that declared no marking, or declared
something outside the closed set, fails in any mode (#136).
openai_compatible and the two openai endpoint types are the special
case: their base_url decides, so under a declared boundary the entry
needs the operator's own `reach`.

The rank table below is the file's centre, because three values with an
order are what #493 added to a mechanism that was otherwise sound. The
cells that differ from the old boolean are named in its docstring: they
are the ones an implementation that merely renamed the boolean would
still get wrong.
"""

import importlib.util
from collections.abc import Callable

import pytest
from cryptography.fernet import Fernet, MultiFernet
from sqlalchemy import insert

from tests.support.providers import built_world
from tests.support.stores import planted
from vinga_server.boundary import BoundaryRefusal, Reach, check_mcp_server, check_provider
from vinga_server.config import Config, ConfigError
from vinga_server.config.loader import load_file_config
from vinga_server.config.models import (
    DatabaseConfig,
    McpServerConfig,
    ProviderConfig,
)
from vinga_server.config.secrets import generate_key
from vinga_server.config.store import ConfigStore
from vinga_server.db import open_database, schema
from vinga_server.providers import (
    AsrProvider,
    LlmProvider,
    Provider,
    ProviderError,
    TtsProvider,
    VadProvider,
    build_entry,
    registry,
)
from vinga_server.providers.anthropic_llm import AnthropicLlm
from vinga_server.providers.mock import MockAsr, MockLlm, MockTts, MockVad
from vinga_server.providers.openai_llm import OpenAiCompatibleLlm
from vinga_server.providers.silero import SileroVad

HAS_FASTER_WHISPER = importlib.util.find_spec("faster_whisper") is not None
HAS_PIPER = importlib.util.find_spec("piper") is not None

LOCAL_BASE_URL = "http://localhost:11434/v1"

# A base_url shaped like a credential, planted so a sentence that quoted
# what it read would be caught saying it. Nothing about an endpoint
# belongs in a refusal about distance.
PLANTED_BASE_URL = "http://sk-test-4f19c0d2-never-a-real-credential.invalid/v1"


def provider_config(**data: object) -> ProviderConfig:
    return ProviderConfig.model_validate(data)


def config_with_llm(llm_entry: dict[str, object], boundary: Reach | None) -> Config:
    """One agent on the given LLM entry, mocks for the other stages."""
    return Config(
        server={"data_boundary": boundary},
        providers={
            "llm": {"brain": llm_entry},
            "asr": {"ears": {"type": "mock"}},
            "tts": {"voice": {"type": "mock"}},
            "vad": {"gate": {"type": "mock"}},
        },
        agents={
            "assistant": {"llm": "brain", "asr": "ears", "tts": "voice", "vad": "gate"}
        },
        default_agent="assistant",
    )


async def build_a_throwaway_llm(
    monkeypatch: pytest.MonkeyPatch,
    make: Callable[[], object],
    boundary: Reach | None = None,
) -> object:
    """Build a throwaway provider class through `build_provider`.

    The marking is checked where a provider is built rather than where
    its class is defined, so a test about a class that declares wrongly,
    or about a marking no packaged type carries, has to reach the build.
    The factory table is rebuilt on every call, which is why the type is
    registered by replacing the function that returns it."""
    monkeypatch.setattr(
        registry,
        "_registrations",
        lambda: {"llm": {"throwaway": registry.Registration(lambda label, config: make())}},
    )
    return await build_entry("llm", "brain", provider_config(type="throwaway"), boundary)


def a_class_marked(reach: Reach | None) -> type:
    """A provider class carrying exactly this marking, which is how the
    rank table reaches a `network`-marked type: no packaged type is one,
    and the rule has to be provable for a marking rather than only for
    an operator's assertion."""

    class Marked(Provider):
        pass

    Marked.reach = reach  # type: ignore[misc]
    return Marked


# --- the rank table ----------------------------------------------------

# Every effective reach against every boundary state, and what the build
# does. Four boundary states, because absent and explicit `internet` are
# different promises: absent declares nothing, `internet` forbids
# nothing and still demands that every entry say where it goes.
#
# Five of these cells are the ones the old boolean could not express,
# and each of them would stay green under a rename that kept two values:
#
# - network at network builds (the boolean had no `network`);
# - network at host refuses (a boolean reading "not host" would too, but
#   only by accident: see network-at-network beside it);
# - internet at network refuses (the boolean's `local_only` was host);
# - internet at internet builds (a boolean would read any declared
#   boundary as "refuse what leaves");
# - undeclared refuses at internet while booting with the key absent.
CELLS = [
    pytest.param(Reach.HOST, None, True, id="host-with-no-boundary"),
    pytest.param(Reach.HOST, Reach.HOST, True, id="host-at-host"),
    pytest.param(Reach.HOST, Reach.NETWORK, True, id="host-at-network"),
    pytest.param(Reach.HOST, Reach.INTERNET, True, id="host-at-internet"),
    pytest.param(Reach.NETWORK, None, True, id="network-with-no-boundary"),
    pytest.param(Reach.NETWORK, Reach.HOST, False, id="network-at-host"),
    pytest.param(Reach.NETWORK, Reach.NETWORK, True, id="network-at-network"),
    pytest.param(Reach.NETWORK, Reach.INTERNET, True, id="network-at-internet"),
    pytest.param(Reach.INTERNET, None, True, id="internet-with-no-boundary"),
    pytest.param(Reach.INTERNET, Reach.HOST, False, id="internet-at-host"),
    pytest.param(Reach.INTERNET, Reach.NETWORK, False, id="internet-at-network"),
    pytest.param(Reach.INTERNET, Reach.INTERNET, True, id="internet-at-internet"),
]


@pytest.mark.parametrize(("reach", "boundary", "builds"), CELLS)
async def test_a_marked_types_reach_is_ranked_against_the_boundary(
    monkeypatch: pytest.MonkeyPatch, reach: Reach, boundary: Reach | None, builds: bool
) -> None:
    """The table for a reach the TYPE knows, which is where the rank
    rule has to hold first: the class marking is authoritative and no
    key on the entry can move it."""
    if builds:
        assert await build_a_throwaway_llm(monkeypatch, a_class_marked(reach), boundary)
        return
    with pytest.raises(ProviderError) as excinfo:
        await build_a_throwaway_llm(monkeypatch, a_class_marked(reach), boundary)
    message = str(excinfo.value)
    assert "providers.llm.brain" in message
    assert f"data boundary is {boundary}" in message


@pytest.mark.parametrize(("reach", "boundary", "builds"), CELLS)
def test_an_operators_reach_is_ranked_against_the_boundary(
    reach: Reach, boundary: Reach | None, builds: bool
) -> None:
    """The same table for a reach the OPERATOR asserts on an entry whose
    type cannot know its own, driven through a real provider build.

    `internet` is accepted as a value here, deliberately: refusing an
    operator's honest statement of the worst case would be the mechanism
    teaching dishonesty from the other side. It simply refuses under
    every narrower boundary, which is the three cells above it.
    """
    config = config_with_llm(
        {
            "type": "openai_compatible",
            "base_url": LOCAL_BASE_URL,
            "model": "qwen3:8b",
            "reach": reach.value,
        },
        boundary,
    )
    if builds:
        assert isinstance(built_world(config).agents["assistant"].llm, OpenAiCompatibleLlm)
        return
    with pytest.raises(ProviderError) as excinfo:
        built_world(config)
    message = str(excinfo.value)
    assert "providers.llm.brain" in message
    assert f"boundary, which is {boundary}" in message


@pytest.mark.parametrize(
    ("boundary", "builds"),
    [
        pytest.param(None, True, id="undeclared-with-no-boundary"),
        pytest.param(Reach.HOST, False, id="undeclared-at-host"),
        pytest.param(Reach.NETWORK, False, id="undeclared-at-network"),
        pytest.param(Reach.INTERNET, False, id="undeclared-at-internet"),
    ],
)
def test_an_undeclared_entry_fails_closed_whenever_a_boundary_is_declared(
    boundary: Reach | None, builds: bool
) -> None:
    """The undeclared row, and the distinction the first draft of this
    lost: ABSENT is no boundary and boots exactly as a server without
    one always did, while an EXPLICIT `internet` forbids nothing and
    still refuses an entry that will not say where it goes."""
    config = config_with_llm(
        {"type": "openai_compatible", "base_url": LOCAL_BASE_URL, "model": "qwen3:8b"},
        boundary,
    )
    if builds:
        assert isinstance(built_world(config).agents["assistant"].llm, OpenAiCompatibleLlm)
        return
    with pytest.raises(ProviderError) as excinfo:
        built_world(config)
    message = str(excinfo.value)
    assert "providers.llm.brain" in message
    assert '"reach: host"' in message


# --- the markings themselves -------------------------------------------


def test_local_engines_and_mocks_are_marked_for_the_host() -> None:
    assert SileroVad.reach is Reach.HOST
    for mock_class in (MockLlm, MockAsr, MockTts, MockVad):
        assert mock_class.reach is Reach.HOST


@pytest.mark.skipif(not HAS_FASTER_WHISPER, reason="faster-whisper extra not installed")
def test_faster_whisper_is_marked_for_the_host() -> None:
    from vinga_server.providers.faster_whisper import FasterWhisperAsr

    assert FasterWhisperAsr.reach is Reach.HOST


@pytest.mark.skipif(not HAS_PIPER, reason="piper extra not installed")
def test_piper_is_marked_for_the_host() -> None:
    from vinga_server.providers.piper_tts import PiperTts

    assert PiperTts.reach is Reach.HOST


def test_the_cloud_and_configurable_types_carry_their_marking() -> None:
    assert AnthropicLlm.reach is Reach.INTERNET
    assert OpenAiCompatibleLlm.reach is None


async def test_a_type_that_forgot_to_declare_is_refused_at_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Forgetful(Provider):
        pass

    with pytest.raises(ProviderError) as excinfo:
        await build_a_throwaway_llm(monkeypatch, Forgetful)
    message = str(excinfo.value)
    assert "providers.llm.brain" in message
    assert "Forgetful" in message


def test_the_provider_bases_declare_no_reach_at_runtime() -> None:
    # A default on a base is the same hole as a default in the check:
    # every subclass would inherit an answer nobody wrote.
    for base in (Provider, VadProvider, AsrProvider, LlmProvider, TtsProvider):
        assert not hasattr(base, "reach")


async def test_an_unmarked_subclass_does_not_ride_its_parents_marking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Quiet(MockLlm):
        pass

    with pytest.raises(ProviderError) as excinfo:
        await build_a_throwaway_llm(monkeypatch, lambda: Quiet("hello"))
    message = str(excinfo.value)
    assert "Quiet" in message


# A marking shaped like a credential, so the closed-set refusal is
# proved not to print what it read. A typo in a class body is as good a
# place to leave one as a configuration file is.
CREDENTIAL_SHAPED_MARKING = "sk-test-6c81ae37-never-a-real-credential"


@pytest.mark.parametrize(
    "marking", [0, CREDENTIAL_SHAPED_MARKING, "host"], ids=["zero", "credential", "lookalike"]
)
async def test_a_marking_outside_the_closed_set_is_refused(
    monkeypatch: pytest.MonkeyPatch, marking: object
) -> None:
    """Membership of the closed set rather than truthiness, which is
    what keeps `reach = 0` from passing for something.

    The bare `"host"` is the third case and the one the enum added: a
    `StrEnum` compares and hashes equal to its own value, so a lookalike
    would rank correctly today and go on doing so right up until the set
    grows a member nobody spelled the same way.
    """

    class Sloppy(Provider):
        pass

    Sloppy.reach = marking  # type: ignore[assignment]

    with pytest.raises(ProviderError) as excinfo:
        await build_a_throwaway_llm(monkeypatch, Sloppy)
    message = str(excinfo.value)
    assert "Sloppy" in message


async def test_the_closed_set_refusal_prints_no_marking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Value-free like every other refusal: what was read never reaches
    the message, so a marking holding a credential-shaped typo cannot
    print one. Driven on the credential-shaped marking alone, because
    the sentence lists the lawful spellings and a lookalike would match
    itself in that list."""

    class Sloppy(Provider):
        pass

    Sloppy.reach = CREDENTIAL_SHAPED_MARKING  # type: ignore[assignment]

    with pytest.raises(ProviderError) as excinfo:
        await build_a_throwaway_llm(monkeypatch, Sloppy)

    assert CREDENTIAL_SHAPED_MARKING not in str(excinfo.value)
    assert "sk-test" not in str(excinfo.value)


# --- the resolve ladder ------------------------------------------------


@pytest.mark.parametrize("boundary", [None, Reach.HOST, Reach.NETWORK, Reach.INTERNET])
async def test_a_reach_on_a_type_that_knows_its_own_is_rejected(
    boundary: Reach | None,
) -> None:
    """In any mode, because it is not a deployment's choice to make: the
    class marking is authoritative everywhere, so a key beside it is an
    operator believing something the build will not honour."""
    with pytest.raises(ProviderError) as excinfo:
        await build_entry(
            "asr", "ears", provider_config(type="mock", reach="host"), boundary
        )
    message = str(excinfo.value)
    assert "providers.asr.ears" in message
    assert 'decided by type "mock"' in message


async def test_the_class_marking_beats_the_entry_for_the_rank_too() -> None:
    """The ladder's own claim, from the other side: a mock reaches the
    host whatever an entry says, and the entry cannot widen it, because
    the entry is refused before any ranking happens."""
    with pytest.raises(ProviderError, match='decided by type "mock"'):
        await build_entry(
            "vad", "gate", provider_config(type="mock", reach="internet"), Reach.HOST
        )


# --- value freedom -----------------------------------------------------


@pytest.mark.parametrize(
    "entry",
    [
        pytest.param({"type": "openai_compatible", "model": "m"}, id="undeclared"),
        pytest.param(
            {"type": "openai_compatible", "model": "m", "reach": "internet"},
            id="declared-too-far",
        ),
    ],
)
def test_no_boundary_refusal_quotes_the_endpoint(entry: dict[str, object]) -> None:
    """The rule the sentences are written to: a refusal about distance
    names the entry, the type, the key and the operator's own boundary,
    and never a value read off the entry. A base_url is the value most
    likely to be carrying a credential."""
    config = config_with_llm({**entry, "base_url": PLANTED_BASE_URL}, Reach.HOST)

    with pytest.raises(ProviderError) as excinfo:
        built_world(config)

    said = str(excinfo.value)
    assert PLANTED_BASE_URL not in said
    assert "sk-test" not in said


# --- the MCP entry point -----------------------------------------------


def an_mcp_entry(**overrides: object) -> McpServerConfig:
    return McpServerConfig.model_validate(
        {"transport": "stdio", "command": "uvx"} | overrides
    )


@pytest.mark.parametrize(("reach", "boundary", "permits"), CELLS)
def test_the_mcp_entry_point_ranks_the_same_way(
    reach: Reach, boundary: Reach | None, permits: bool
) -> None:
    """The same table at the other entry point, because it is a
    different function: `check_mcp_server` reads the operator's
    declaration off an entry rather than a marking off a class, and an
    implementation there that treated every non-host reach as a refusal
    would pass everything above."""
    entry = an_mcp_entry(reach=reach.value)
    if permits:
        check_mcp_server("mcp_servers.tools", entry, boundary)
        return
    with pytest.raises(BoundaryRefusal) as excinfo:
        check_mcp_server("mcp_servers.tools", entry, boundary)
    assert f"boundary, which is {boundary}" in str(excinfo.value)


def test_an_mcp_refusal_names_no_command_or_url() -> None:
    """Value-free at this entry point too, where the planted string is
    the command a stdio entry spawns."""
    entry = an_mcp_entry(command=PLANTED_BASE_URL)

    with pytest.raises(BoundaryRefusal) as excinfo:
        check_mcp_server("mcp_servers.tools", entry, Reach.HOST)

    assert PLANTED_BASE_URL not in str(excinfo.value)


# --- the old spellings -------------------------------------------------


def test_the_server_section_refuses_the_replaced_key(tmp_path) -> None:
    """`server.local_only` is gone with no alias, and the closed model
    answers it as an unrecognized key: the SECTION is named and the key
    is not quoted back, which is this repository's standing rule for a
    key a caller wrote. Driven through the real file load, because the
    sentence an operator meets is the loader's rendering rather than
    pydantic's."""
    path = tmp_path / "vinga.yaml"
    path.write_text("server:\n  local_only: true\n")

    with pytest.raises(ConfigError) as excinfo:
        load_file_config(path)

    said = str(excinfo.value)
    assert "server: an unrecognized key is not permitted" in said
    assert "local_only" not in said
    assert excinfo.value.__cause__ is None


# What an operator most plausibly has in a stale `egress`, and what they
# least want back: the key took a boolean, so a pasted string there is
# either a typo or a credential in the wrong field, and a refusal cannot
# tell which.
CREDENTIAL_SHAPED_LEGACY = "sk-test-0a5e7b34-never-a-real-credential"

# Both provider types, because the options layer could only ever have
# answered the first: its reserved set is enforced by
# `OpenaiCompatibleOptions`, which no other type passes. The refusal
# lives at the common `ProviderConfig` boundary, and these two are how
# that is pinned rather than assumed.
LEGACY_PROVIDER_ENTRIES = [
    pytest.param("openai_compatible", id="a-type-with-an-options-model"),
    pytest.param("mock", id="a-type-with-no-options-model"),
]


@pytest.mark.parametrize("type_name", LEGACY_PROVIDER_ENTRIES)
def test_a_provider_write_refuses_the_replaced_key_without_quoting_it(
    store, capsys: pytest.CaptureFixture[str], type_name: str
) -> None:
    """THE trap the census exposed, driven through the write path an
    operator actually reaches. `ProviderConfig` is `extra="allow"`, so
    without this refusal a stale `egress` would flow into `model_extra`,
    become a provider option and reach the engine as a stray keyword or
    vanish into a builder that ignores what it does not know, leaving an
    operator believing a declaration nothing enforces.

    The value is credential-shaped and the assertion is the whole
    operator-facing surface: both streams, the sentence, and every link
    of the cause and context chain, none of which may carry the value or
    a traceback. Pydantic's own `ValidationError` renders the input it
    rejected, so this is a claim about what the repository's rendering
    does with it rather than about what pydantic holds.
    """
    capsys.readouterr()

    with pytest.raises(ConfigError) as excinfo:
        store.set_provider(
            "llm", "brain", {"type": type_name, "egress": CREDENTIAL_SHAPED_LEGACY}
        )

    said = str(excinfo.value)
    assert '"egress"' in said
    assert '"reach"' in said
    assert "not quoted back" in said
    _nothing_leaked(excinfo.value, capsys.readouterr())


def test_an_mcp_write_refuses_the_replaced_key_without_quoting_it(
    store, capsys: pytest.CaptureFixture[str]
) -> None:
    """The same claim at the other entry kind, where the key is refused
    by `extra="forbid"` rather than by a validator: the SECTION is
    named, the key the caller wrote is not, and neither is what it
    held."""
    capsys.readouterr()

    with pytest.raises(ConfigError) as excinfo:
        store.set_mcp_server(
            "tools",
            {
                "transport": "stdio",
                "command": "uvx",
                "egress": CREDENTIAL_SHAPED_LEGACY,
            },
        )

    said = str(excinfo.value)
    assert "an unrecognized key is not permitted" in said
    assert "egress" not in said
    _nothing_leaked(excinfo.value, capsys.readouterr())


def _nothing_leaked(error: BaseException, streams) -> None:
    """What a refusal about a withdrawn key may not have done: printed
    anything, carried the value out, or brought a traceback with it.

    The chain and not only the sentence, because an operator's terminal
    renders whatever a re-raise left attached, and the value that fails
    here fails inside pydantic, which keeps its input on the exception
    it raises.
    """
    surfaces = (streams.out, streams.err, _whole_chain(error))
    for surface in surfaces:
        assert CREDENTIAL_SHAPED_LEGACY not in surface
        assert "sk-test" not in surface
        assert "Traceback" not in surface
        assert 'File "' not in surface


def test_a_provider_entry_refuses_the_replaced_key_at_the_model() -> None:
    """And the model on its own, because the write path above is not the
    only caller: a stored row read back and a file fragment reach the
    same validator, and this is the one place the refusal is stated
    without a store around it."""
    with pytest.raises(ValueError) as excinfo:
        ProviderConfig.model_validate({"type": "mock", "egress": False})

    assert '"reach"' in str(excinfo.value)


def test_an_mcp_entry_refuses_the_replaced_key_at_the_model() -> None:
    with pytest.raises(ValueError):
        McpServerConfig.model_validate(
            {"transport": "stdio", "command": "uvx", "egress": False}
        )


def test_the_options_of_a_clean_entry_are_untouched() -> None:
    """And the other half: the refusal is a rule about one withdrawn
    key, not a new reserved word. Everything else still passes through
    to the provider, `reach` included as a declared field rather than as
    an option."""
    entry = ProviderConfig.model_validate(
        {"type": "openai_compatible", "reach": "network", "model": "m", "temperature": 0.2}
    )

    assert entry.reach is Reach.NETWORK
    assert entry.options == {"model": "m", "temperature": 0.2}


# --- no leak through the new enum fields -------------------------------

# A value no enum member can be, shaped like a credential, planted in
# each of the three new fields. Every one of them fails inside pydantic,
# whose error data retains the input, so the sentence that reaches an
# operator is what these cases are about.
CREDENTIAL_SHAPED_VALUE = "sk-test-90b4ff21-never-a-real-credential"


def test_the_boundary_field_leaks_nothing_through_the_real_file_load(
    tmp_path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`server.data_boundary` is file-only, so the file load is the whole
    of its input surface. Both streams, the sentence and the whole
    exception chain are asserted clean."""
    path = tmp_path / "vinga.yaml"
    path.write_text(f"server:\n  data_boundary: {CREDENTIAL_SHAPED_VALUE}\n")
    capsys.readouterr()

    with pytest.raises(ConfigError) as excinfo:
        load_file_config(path)

    streams = capsys.readouterr()
    assert CREDENTIAL_SHAPED_VALUE not in streams.out
    assert CREDENTIAL_SHAPED_VALUE not in streams.err
    assert CREDENTIAL_SHAPED_VALUE not in _whole_chain(excinfo.value)


@pytest.fixture
def store():
    engine = open_database(DatabaseConfig())
    try:
        yield ConfigStore(engine, MultiFernet([Fernet(generate_key())]))
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("write", "row"),
    [
        pytest.param(
            lambda store, value: store.set_provider(
                "llm", "brain", {"type": "openai_compatible", "reach": value}
            ),
            lambda value: insert(schema.providers).values(
                stage="llm",
                name="brain",
                body=f'{{"type": "openai_compatible", "reach": "{value}"}}',
                secrets={},
            ),
            id="provider",
        ),
        pytest.param(
            lambda store, value: store.set_mcp_server(
                "tools", {"transport": "stdio", "command": "uvx", "reach": value}
            ),
            lambda value: insert(schema.mcp_servers).values(
                name="tools",
                body=(
                    '{"transport": "stdio", "command": "uvx", '
                    f'"reach": "{value}"}}'
                ),
                secrets={},
            ),
            id="mcp-server",
        ),
    ],
)
def test_a_reach_field_leaks_nothing_through_the_write_or_the_stored_read(
    store, capsys: pytest.CaptureFixture[str], write, row
) -> None:
    """The two surfaces a `reach` can arrive on: an operator writing a
    fragment, and a row an older or broken build left behind that the
    load has to survive reading.

    Both fail inside pydantic, whose `ValidationError` carries the input
    it rejected, so what is asserted is the whole chain the renderer
    walks rather than only the top sentence.
    """
    capsys.readouterr()

    with pytest.raises(ConfigError) as written:
        write(store, CREDENTIAL_SHAPED_VALUE)

    planted(store, row(CREDENTIAL_SHAPED_VALUE))
    with pytest.raises(ConfigError) as read_back:
        store.load()

    streams = capsys.readouterr()
    assert CREDENTIAL_SHAPED_VALUE not in streams.out
    assert CREDENTIAL_SHAPED_VALUE not in streams.err
    assert CREDENTIAL_SHAPED_VALUE not in _whole_chain(written.value)
    assert CREDENTIAL_SHAPED_VALUE not in _whole_chain(read_back.value)


def _whole_chain(error: BaseException) -> str:
    """Every sentence reachable from a refusal, cause and context
    included: a value that leaked one link down is a value a traceback
    renderer prints."""
    said = []
    seen: set[int] = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        said.append(str(error))
        said.extend(str(argument) for argument in error.args)
        error = error.__cause__ or error.__context__  # type: ignore[assignment]
    return "\n".join(said)


# --- the composition root ----------------------------------------------


def test_the_server_section_reaches_every_builder(monkeypatch: pytest.MonkeyPatch) -> None:
    """The plumbing, which the tables above cannot see: a caller left
    passing a boolean, or passing the default, would keep every cell
    green and quietly disarm the boundary for three whole features.

    Driven through the real composition. The first version of this case
    stubbed the three builders and then CALLED THE STUBS itself, which
    is a test of its own arguments: deleting the boundary from all three
    calls in `app._build_composition` left it green, which is PR #499's
    second finding. So the app is built and its lifespan entered, and
    what is asserted is what the composition handed the builders while
    it ran.

    The stubs answer None, which is what each of these builders answers
    for an absent section anyway, so nothing downstream of them changes
    shape. The boundary is `network` rather than `host` because the mock
    providers reach the host: the fourth call site has to get through
    for the composition to reach the three that are the subject here,
    and it has its own case below.
    """
    import vinga_server.app as app
    from tests.support.apps import entered_app
    from tests.support.configs import config_with_agent

    handed: dict[str, object] = {}

    def spy(name: str):
        def built(*args: object, boundary: object = "unset", **kwargs: object) -> None:
            handed[name] = boundary
            return None

        return built

    for name in ("build_telemetry", "build_capture_upload", "build_transcript_export"):
        monkeypatch.setattr(app, name, spy(name))

    config = config_with_agent(server={"data_boundary": "network"})
    assert config.server.data_boundary is Reach.NETWORK

    with entered_app(config):
        pass

    assert handed == {
        "build_telemetry": Reach.NETWORK,
        "build_capture_upload": Reach.NETWORK,
        "build_transcript_export": Reach.NETWORK,
    }


def test_the_provider_build_reads_the_boundary_off_the_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """And the fourth call site, driven end to end rather than spied on:
    the world builder reads `config.server.data_boundary` itself, so an
    entry too far for it refuses through the real path."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    config = config_with_llm(
        {
            "type": "anthropic",
            "model": "claude-sonnet-5",
            "api_key_env": "ANTHROPIC_API_KEY",
        },
        Reach.NETWORK,
    )

    with pytest.raises(ProviderError) as excinfo:
        built_world(config)

    assert "data boundary is network" in str(excinfo.value)


# --- the one-home property ---------------------------------------------


def test_the_build_refusal_is_the_boundary_modules_own_sentence() -> None:
    """One home for the rule, checked rather than asserted: the words a
    boot prints are the words `boundary.py` composes, so a provider rule
    of its own would show up here as two sentences."""
    entry = provider_config(type="anthropic", model="claude-sonnet-5")

    with pytest.raises(BoundaryRefusal) as direct:
        check_provider("providers.llm.brain", entry, AnthropicLlm.__new__(AnthropicLlm), Reach.HOST)

    assert "providers.llm.brain" in str(direct.value)
    assert "data boundary is host" in str(direct.value)
