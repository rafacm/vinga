"""The tool half of the configuration: MCP servers, the agent lists that
reference them."""


import pytest
from pydantic import ValidationError

from tests.support.configs import config_with
from vinga_server.config import Config, McpServerConfig, resolve_env_values
from vinga_server.config.models import AgentConfig, mcp_entry_fragment
from vinga_server.tools import names

STDIO = {"transport": "stdio", "command": "mcp-proxy", "args": ["http://ha/sse"]}
HTTP = {"transport": "streamable_http", "url": "http://localhost:8000/mcp"}


def test_both_transports_parse() -> None:
    config = config_with(mcp_servers={"ha": STDIO, "weather": HTTP})
    assert config.mcp_servers["ha"].command == "mcp-proxy"
    assert config.mcp_servers["ha"].args == ["http://ha/sse"]
    assert config.mcp_servers["weather"].url == "http://localhost:8000/mcp"
    # The default timeout is what keeps spoken silence bounded.
    assert config.mcp_servers["weather"].tool_timeout_s == 15.0


@pytest.mark.parametrize(
    ("entry", "fragment"),
    [
        ({"transport": "stdio"}, '"command"'),
        ({"transport": "streamable_http"}, '"url"'),
        (STDIO | {"url": "http://x/mcp"}, "url"),
        (STDIO | {"headers": {"X-Trace": "1"}}, "headers"),
        (HTTP | {"command": "mcp-proxy"}, "command"),
        (HTTP | {"env": {"HOME": "/root"}}, "env"),
    ],
)
def test_a_field_belonging_to_the_other_transport_is_an_error(
    entry: dict, fragment: str
) -> None:
    # A silently ignored header is the difference between "my headers are
    # ignored" and "my headers are wrong", which is a debugging afternoon.
    with pytest.raises(ValidationError, match=fragment):
        config_with(mcp_servers={"x": entry})


# Guidance whose shape is the assertion: leading indentation, an inner
# blank line and a trailing newline, all of which a stripping type would
# quietly take away.
VERBATIM = "  Ask before unlocking the door.\n\n    The lights are safe.\n"


def test_an_entry_carries_the_operators_guidance_verbatim() -> None:
    config = config_with(mcp_servers={"ha": STDIO | {"instructions": VERBATIM}})

    assert config.mcp_servers["ha"].instructions == VERBATIM


def test_an_entry_without_guidance_has_none() -> None:
    assert config_with(mcp_servers={"ha": STDIO}).mcp_servers["ha"].instructions is None


@pytest.mark.parametrize("written", ["", "   ", "\n\n"])
def test_blank_guidance_is_refused_by_the_rule_and_not_by_its_value(written: str) -> None:
    """Non-blank is checked on a stripped copy; what is stored is the
    original. The refusal names the rule, since a rejected fragment is
    one nobody has validated yet."""
    with pytest.raises(ValidationError, match="only whitespace") as caught:
        config_with(mcp_servers={"ha": STDIO | {"instructions": written}})

    assert "leave the key out" in str(caught.value)


def test_the_server_guidance_opt_ins_are_off_by_default() -> None:
    """Both channels a server can ship guidance in are closed until the
    operator opens them, which is the whole of the trust decision."""
    entry = config_with(mcp_servers={"ha": STDIO}).mcp_servers["ha"]

    assert entry.use_server_instructions is False
    assert entry.inject_prompts is None


def test_the_server_guidance_opt_ins_parse_as_written() -> None:
    config = config_with(
        mcp_servers={
            "ha": STDIO
            | {"use_server_instructions": True, "inject_prompts": ["house_style", "safety"]}
        }
    )

    entry = config.mcp_servers["ha"]
    assert entry.use_server_instructions is True
    assert entry.inject_prompts == ["house_style", "safety"]


def test_a_prompt_named_twice_is_refused_by_position_and_not_by_value() -> None:
    """A configured prompt name is a server-chosen string the operator
    copied, so it may hold anything at all; the refusal says where the
    repetition is and never what is repeated."""
    secret = "sk-test-9f2b-never-a-real-credential"
    with pytest.raises(ValidationError) as caught:
        config_with(
            mcp_servers={"ha": STDIO | {"inject_prompts": [secret, "other", secret]}}
        )

    problem = str(caught.value)
    assert "inject_prompts names one prompt at more than one position (1, 3)" in problem
    assert secret not in problem


@pytest.mark.parametrize("written", ["", "   ", "\n"])
def test_a_blank_prompt_name_is_refused(written: str) -> None:
    with pytest.raises(ValidationError):
        config_with(mcp_servers={"ha": STDIO | {"inject_prompts": [written]}})


def test_a_prompt_name_keeps_the_whitespace_it_was_written_with() -> None:
    """The name is an identifier the server chose, not a word this
    server may tidy: a stripped copy of `  spaced  ` addresses a
    different prompt, or none at all, and the fetch would silently ask
    for the wrong thing."""
    written = "  spaced out  "
    config = config_with(mcp_servers={"ha": STDIO | {"inject_prompts": [written]}})

    assert config.mcp_servers["ha"].inject_prompts == [written]


@pytest.mark.parametrize(
    "name", [*names.RESERVED_ENTRY_NAMES, "home.assistant"]
)
def test_a_reserved_or_unusable_entry_name_fails_the_boot(name: str) -> None:
    """The section and the rule, and never the name: a name that fails
    the charset is exactly the string that must not be echoed, which is
    the shape the prompt-fragment name rule already had.

    Walked off the reserved set rather than listed here, so a builtin
    that joins it is refused at the boot without anyone remembering to
    add it: the set is what the rule is written from."""
    with pytest.raises(ValidationError) as caught:
        config_with(mcp_servers={name: STDIO})

    assert "must match [A-Za-z0-9_-]+" in str(caught.value)
    assert f"mcp_servers.{name}" not in str(caught.value)


@pytest.mark.parametrize(
    "entry",
    [
        STDIO | {"env": {"API_ACCESS_TOKEN": "sk-literal"}},
        HTTP | {"headers": {"Authorization": "Bearer sk-literal"}},
    ],
)
def test_a_secret_bearing_value_referencing_nothing_is_refused(entry: dict) -> None:
    """The rule is that a secret-bearing key references a variable
    somewhere in its value, so a value that references none is refused
    and the sentence says what is now allowed."""
    with pytest.raises(ValidationError) as caught:
        config_with(mcp_servers={"x": entry})

    problem = str(caught.value)
    assert "references no environment variable" in problem
    assert "Bearer $MY_SERVER_SECRET" in problem
    # What the refusal itself says about the value is asserted where an
    # operator meets it, which is the CLI and the API rather than
    # pydantic's own wrapper: the wrapper echoes the input it was handed
    # whatever the message says. `test_mcp_composed_reference.py` holds
    # that half.


@pytest.mark.parametrize(
    "entry",
    [
        STDIO | {"env": {"API_ACCESS_TOKEN": "$HOME_ASSISTANT_TOKEN"}},
        STDIO | {"env": {"API_ACCESS_TOKEN": "--token=$HOME_ASSISTANT_TOKEN"}},
        HTTP | {"headers": {"Authorization": "$WEATHER_TOKEN"}},
        HTTP | {"headers": {"Authorization": "Bearer $WEATHER_TOKEN"}},
    ],
)
def test_a_secret_bearing_value_may_compose_a_reference(entry: dict) -> None:
    """Whole or composed, and in both groups by one rule.

    The header a vendor asks for is a word and a credential, and a rule
    that took only the whole value would put the word inside the secret,
    where a token that already carries the prefix sends
    `Bearer Bearer ...` and reads back as a bad key. An `env` value has
    the same problem the moment a server wants `--token=$TOKEN`, which
    is why one rule serves both (#504).
    """
    config_with(mcp_servers={"x": entry})


def test_a_non_secret_key_may_hold_a_literal() -> None:
    entry = McpServerConfig.model_validate(STDIO | {"env": {"TZ": "Europe/Stockholm"}})
    assert entry.env == {"TZ": "Europe/Stockholm"}


def test_env_references_resolve_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VINGA_TEST_HA_TOKEN", "secret-value")
    resolved = resolve_env_values(
        "mcp_servers.ha.env",
        {"API_ACCESS_TOKEN": "$VINGA_TEST_HA_TOKEN", "TZ": "Europe/Stockholm"},
    )
    assert resolved.values == {"API_ACCESS_TOKEN": "secret-value", "TZ": "Europe/Stockholm"}


def test_an_unset_env_reference_names_where_it_was_written(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("VINGA_TEST_MISSING", raising=False)
    with pytest.raises(ValueError, match=r"mcp_servers\.ha\.env\.TOKEN.*VINGA_TEST_MISSING"):
        resolve_env_values("mcp_servers.ha.env", {"TOKEN": "$VINGA_TEST_MISSING"})


def test_a_reference_resolves_where_it_stands_inside_a_larger_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The substitution, and the atoms beside it.

    The resolved value is what the request carries and the secret is
    what a far side can hand back on its own, so both cross the seam:
    recovering the second from the first anywhere else would mean
    reading the environment twice or diffing strings.
    """
    monkeypatch.setenv("VINGA_TEST_HA_TOKEN", "secret-value")

    resolved = resolve_env_values(
        "mcp_servers.ha.headers", {"Authorization": "Bearer $VINGA_TEST_HA_TOKEN"}
    )

    assert resolved.values == {"Authorization": "Bearer secret-value"}
    assert resolved.secrets == frozenset({"secret-value"})


def test_every_reference_in_one_value_resolves(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VINGA_TEST_ONE", "first-value")
    monkeypatch.setenv("VINGA_TEST_TWO", "second-value")

    resolved = resolve_env_values(
        "mcp_servers.ha.env", {"API_TOKEN": "$VINGA_TEST_ONE:$VINGA_TEST_TWO@$VINGA_TEST_ONE"}
    )

    assert resolved.values == {"API_TOKEN": "first-value:second-value@first-value"}
    assert resolved.secrets == frozenset({"first-value", "second-value"})


def test_a_value_with_no_reference_passes_through_byte_for_byte() -> None:
    """Including its own whitespace: only a value that is nothing but a
    reference is trimmed, and that trimming is about the reference
    rather than about the value."""
    written = {"TZ": "  Europe/Stockholm  ", "GREETING": "hello\nworld"}

    resolved = resolve_env_values("mcp_servers.ha.env", dict(written))

    assert resolved.values == written
    assert resolved.secrets == frozenset()


@pytest.mark.parametrize(
    "written", ["$VINGA_TEST_HA_TOKEN", "  $VINGA_TEST_HA_TOKEN  ", "$VINGA_TEST_HA_TOKEN\n"]
)
def test_a_whole_reference_keeps_its_trimming(
    written: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The compatibility story of #504, stated as behavior.

    A value that is nothing but a reference, whatever whitespace is
    around it, resolves to the bare secret exactly as it did before the
    scanner existed. Only a value that is NOT a whole reference is
    substituted as written, so a padded reference cannot quietly become
    a composed value with whitespace in it.
    """
    monkeypatch.setenv("VINGA_TEST_HA_TOKEN", "secret-value")

    resolved = resolve_env_values("mcp_servers.ha.env", {"TOKEN": written})

    assert resolved.values == {"TOKEN": "secret-value"}


def granted(config: Config, agent: str) -> list[tuple[str, list[str] | None]]:
    """What an agent may reach, as pairs of server and allow list, which
    is what a grant is."""
    return [(grant.server, grant.tools) for grant in config.mcp_for_agent(agent)]


def test_agents_inherit_the_default_mcp_list() -> None:
    config = config_with(
        mcp_servers={"ha": STDIO, "weather": HTTP},
        agent_defaults=dict.fromkeys(("llm", "asr", "tts", "vad"), "mock")
        | {"mcp": ["weather"]},
        agents={"assistant": {"prompt": "A"}, "home": {"prompt": "H", "mcp": ["ha", "weather"]}},
    )
    # A plain name is the whole server, which is a grant with no allow
    # list, so nothing downstream has to know it was written short.
    assert granted(config, "assistant") == [("weather", None)]
    # A list replaces rather than extends, like the stage fields.
    assert granted(config, "home") == [("ha", None), ("weather", None)]
    assert config.referenced_mcp_servers() == {"ha", "weather"}


def test_an_empty_list_opts_an_agent_out() -> None:
    config = config_with(
        mcp_servers={"ha": STDIO},
        agent_defaults=dict.fromkeys(("llm", "asr", "tts", "vad"), "mock") | {"mcp": ["ha"]},
        agents={"assistant": {"prompt": "A"}, "quiet": {"prompt": "Q", "mcp": []}},
    )
    assert granted(config, "assistant") == [("ha", None)]
    assert granted(config, "quiet") == []


def test_an_object_entry_grants_the_tools_it_names() -> None:
    config = config_with(
        mcp_servers={"ha": STDIO},
        agents={
            "assistant": {"prompt": "A"},
            "kids": {
                "prompt": "K",
                "mcp": [{"server": "ha", "tools": ["turn_on_light", "turn_off_light"]}],
            },
        },
    )
    assert granted(config, "kids") == [("ha", ["turn_on_light", "turn_off_light"])]
    # An allow list narrows the tool list, never whether the connection
    # is made: the server is referenced as much as a whole-server grant
    # references it.
    assert config.referenced_mcp_servers() == {"ha"}


def test_an_object_entry_without_tools_is_the_whole_server() -> None:
    config = config_with(
        mcp_servers={"ha": STDIO},
        agents={"assistant": {"prompt": "A", "mcp": [{"server": "ha"}]}},
    )
    assert granted(config, "assistant") == [("ha", None)]


def test_both_entry_forms_live_in_one_list() -> None:
    config = config_with(
        mcp_servers={"ha": STDIO, "weather": HTTP},
        agents={
            "assistant": {
                "prompt": "A",
                "mcp": ["weather", {"server": "ha", "tools": ["turn_on_light"]}],
            }
        },
    )
    assert granted(config, "assistant") == [("weather", None), ("ha", ["turn_on_light"])]


def test_an_empty_tools_list_is_refused_and_says_how_to_opt_out() -> None:
    # "Granted, nothing allowed" is a confusing spelling of not granting,
    # and the refusal names the plain one.
    with pytest.raises(ValidationError, match=r"mcp: \[\]"):
        config_with(
            mcp_servers={"ha": STDIO},
            agents={"assistant": {"prompt": "A", "mcp": [{"server": "ha", "tools": []}]}},
        )


def test_a_tool_named_twice_in_one_grant_is_refused() -> None:
    # By position, never by name: the sentence leaves this boundary as a
    # printed line and an HTTP body, and the name is the caller's bytes.
    with pytest.raises(
        ValidationError, match=r"tools names one tool at more than one position \(1, 2\)"
    ):
        config_with(
            mcp_servers={"ha": STDIO},
            agents={
                "assistant": {
                    "prompt": "A",
                    "mcp": [{"server": "ha", "tools": ["turn_on_light", "turn_on_light"]}],
                }
            },
        )


def test_a_blank_tool_name_is_refused() -> None:
    with pytest.raises(ValidationError, match="tools.0"):
        config_with(
            mcp_servers={"ha": STDIO},
            agents={"assistant": {"prompt": "A", "mcp": [{"server": "ha", "tools": ["  "]}]}},
        )


@pytest.mark.parametrize(
    "entries",
    [
        ["ha", "ha"],
        ["ha", {"server": "ha", "tools": ["turn_on_light"]}],
        [{"server": "ha", "tools": ["a"]}, {"server": "ha", "tools": ["b"]}],
    ],
)
def test_a_server_named_twice_in_one_list_is_refused(entries: list) -> None:
    # Two entries for one server are two answers to a question that has
    # one: which of its tools this layer reaches.
    with pytest.raises(
        ValidationError, match=r"mcp names one server at more than one position \(1, 2\)"
    ):
        config_with(
            mcp_servers={"ha": STDIO},
            agents={"assistant": {"prompt": "A", "mcp": entries}},
        )


def test_agent_defaults_takes_the_object_form_and_an_agent_replaces_it() -> None:
    config = config_with(
        mcp_servers={"ha": STDIO, "weather": HTTP},
        agent_defaults=dict.fromkeys(("llm", "asr", "tts", "vad"), "mock")
        | {"mcp": [{"server": "ha", "tools": ["turn_on_light"]}]},
        agents={
            "assistant": {"prompt": "A"},
            "house": {"prompt": "H", "mcp": [{"server": "ha", "tools": ["unlock_door"]}]},
        },
    )
    assert granted(config, "assistant") == [("ha", ["turn_on_light"])]
    # Replace rather than merge, exactly as the string form does, so an
    # agent's own list is all of its grants.
    assert granted(config, "house") == [("ha", ["unlock_door"])]


def test_an_unreferenced_server_is_not_connected() -> None:
    config = config_with(mcp_servers={"ha": STDIO})
    assert config.referenced_mcp_servers() == set()


@pytest.mark.parametrize("entry", ["nope", {"server": "nope", "tools": ["a"]}])
@pytest.mark.parametrize(
    ("layer", "location"),
    [
        ("agent_defaults", "agent_defaults.mcp"),
        ("agents", "agents.assistant.mcp"),
    ],
)
def test_an_unknown_server_reference_names_the_layer_that_holds_it(
    layer: str, location: str, entry: object
) -> None:
    # Both entry forms go through the one reference check: an allow list
    # on a server that does not exist is the same broken reference as a
    # bare name that does not.
    stages = dict.fromkeys(("llm", "asr", "tts", "vad"), "mock")
    overrides: dict[str, object] = (
        {"agent_defaults": stages | {"mcp": [entry]}}
        if layer == "agent_defaults"
        else {"agents": {"assistant": {"prompt": "A", "mcp": [entry]}}}
    )
    with pytest.raises(ValidationError, match=location) as excinfo:
        config_with(**overrides)
    assert "names no MCP server that exists" in str(excinfo.value)


def test_each_entry_form_serializes_as_itself() -> None:
    """What a row holds and what a read shows. A string stays a string,
    so every fragment written before the object form existed is written
    back byte-identically; an object stays `{server, tools}` and grows
    no key it was not given."""
    entry = AgentConfig.model_validate(
        {
            "prompt": "A",
            "mcp": ["weather", {"server": "ha", "tools": ["turn_on_light"]}, {"server": "x"}],
        }
    )
    assert entry.mcp is not None
    assert [mcp_entry_fragment(item) for item in entry.mcp] == [
        "weather",
        {"server": "ha", "tools": ["turn_on_light"]},
        {"server": "x"},
    ]

