"""vinga, the built-in agent, as the configuration model serves it (#612).

The served whole (`Config`) carries the built-in as one more agent
whenever `builtin_status` says it is served; the stored half
(`DomainConfig`) never does. What is held here is the closed set of
three answers and each one's decision, the entry the built-in is served
as (its persona, its pinned grants, its overrides), and the reference
rule that lets a binding or the default name it whether or not it is
served.
"""

from typing import Any

import pytest

from tests.support.configs import base_config
from vinga_server import knowledge
from vinga_server.config.models import (
    BUILTIN_AGENT,
    PROVIDER_STAGES,
    AgentConfig,
    BuiltinAgentConfig,
    BuiltinStatus,
    Config,
    DomainConfig,
    builtin_status,
    check_references,
)

MOCKS: dict[str, Any] = {stage: {"mock": {"type": "mock"}} for stage in PROVIDER_STAGES}

EVERY_STAGE = dict.fromkeys(PROVIDER_STAGES, "mock")


def served(**sections: Any) -> Config:
    """A world whose defaults resolve every stage, so the built-in is
    served unless a section says otherwise."""
    return Config(**({"providers": MOCKS, "agent_defaults": EVERY_STAGE} | sections))


# The closed set, decided in one function


def test_a_world_whose_every_stage_resolves_serves_the_built_in() -> None:
    config = served()

    assert config.builtin_state.status is BuiltinStatus.SERVED
    assert config.builtin_state.stages == ()
    assert BUILTIN_AGENT in config.agents
    assert config.is_builtin(BUILTIN_AGENT)


def test_the_overrides_alone_can_provide_every_stage() -> None:
    config = Config(providers=MOCKS, builtin_agent=EVERY_STAGE)

    assert config.builtin_state.status is BuiltinStatus.SERVED


def test_a_stage_that_resolves_nowhere_leaves_it_unprovided_naming_the_stages() -> None:
    """Some stages from the defaults, one from the override, two from
    neither: the two are named, in pipeline order, and the boot is not
    refused."""
    config = Config(
        providers=MOCKS, agent_defaults={"llm": "mock"}, builtin_agent={"tts": "mock"}
    )

    assert config.builtin_state.status is BuiltinStatus.UNPROVIDED
    assert config.builtin_state.stages == ("asr", "vad")
    assert BUILTIN_AGENT not in config.agents
    assert not config.is_builtin(BUILTIN_AGENT)


def test_an_empty_deployment_boots_with_the_built_in_unprovided() -> None:
    config = Config()

    assert config.builtin_state.status is BuiltinStatus.UNPROVIDED
    assert config.builtin_state.stages == PROVIDER_STAGES


def test_a_stored_agent_named_vinga_displaces_the_built_in() -> None:
    config = served(agents={BUILTIN_AGENT: {"prompt": "I am the old vinga."}})

    assert config.builtin_state.status is BuiltinStatus.DISPLACED
    assert not config.is_builtin(BUILTIN_AGENT)
    assert config.prompt_for_agent(BUILTIN_AGENT) == "I am the old vinga."


def test_a_blank_legacy_vinga_stays_the_operator_s_agent_with_its_inherited_grants() -> None:
    """Plan review finding 3: a blank `agents.vinga` stored before the
    upgrade is an operator's agent. It is served under its own empty
    persona, inherits the default grants like any agent that names
    none, and the built-in is displaced rather than taking it over."""
    config = served(
        mcp_servers={"home": {"transport": "stdio", "command": "home-mcp"}},
        agent_defaults=EVERY_STAGE | {"mcp": ["home"]},
        agents={BUILTIN_AGENT: {}},
    )

    assert config.builtin_state.status is BuiltinStatus.DISPLACED
    assert config.prompt_for_agent(BUILTIN_AGENT) == ""
    assert [grant.server for grant in config.mcp_for_agent(BUILTIN_AGENT)] == ["home"]


def test_the_status_is_asked_of_the_stored_half() -> None:
    """`builtin_status` judges what an operator wrote; the stored half
    never carries the built-in, so the same function answers about a
    `DomainConfig` with no `Config` in sight."""
    domain = DomainConfig(providers=MOCKS, agent_defaults=EVERY_STAGE)

    assert builtin_status(domain).status is BuiltinStatus.SERVED
    assert BUILTIN_AGENT not in domain.agents


# The entry the built-in is served as


def test_the_built_in_is_answered_with_the_build_s_persona() -> None:
    config = served()

    assert config.prompt_for_agent(BUILTIN_AGENT) == knowledge.persona()


def test_the_built_in_takes_no_grants_from_the_defaults() -> None:
    """The `mcp` pin: unset would inherit `agent_defaults.mcp`, and the
    built-in is appended to devices whose own agent opted out."""
    config = served(
        mcp_servers={"home": {"transport": "stdio", "command": "home-mcp"}},
        agent_defaults=EVERY_STAGE | {"mcp": ["home"]},
        agents={"kids": {"prompt": "KIDS", "mcp": []}},
    )

    assert config.mcp_for_agent(BUILTIN_AGENT) == []
    # And so nothing references the entry: the one agent besides the
    # built-in opted out of it.
    assert config.referenced_mcp_servers() == set()


def test_the_built_in_carries_what_its_override_names() -> None:
    config = served(
        providers=MOCKS | {"tts": {"mock": {"type": "mock"}, "swedish": {"type": "mock"}}},
        prompt_fragments={"swedish": {"text": "Always reply in Swedish."}},
        builtin_agent={"tts": "swedish", "prompt_includes": ["swedish"]},
    )

    assert config.provider_for_agent(BUILTIN_AGENT, "tts") == (
        "swedish",
        f"agents.{BUILTIN_AGENT}.tts",
    )
    assert [one.text for one in config.fragments_for_agent(BUILTIN_AGENT)] == [
        "Always reply in Swedish."
    ]


def test_the_synthesis_leaves_the_caller_s_mapping_alone() -> None:
    agents: dict[str, Any] = {"sam": {"prompt": "SAM"}}

    served(agents=agents)

    assert list(agents) == ["sam"]


def test_the_overrides_are_an_agent_layer_without_a_prompt_or_grants() -> None:
    """The synthesis builds an `AgentConfig` from what is written here,
    so the two field sets have to agree: everything an agent names but
    its prompt and its grants."""
    assert set(BuiltinAgentConfig.model_fields) == set(AgentConfig.model_fields) - {
        "prompt",
        "mcp",
    }


@pytest.mark.parametrize("field", ["prompt", "mcp"])
def test_a_prompt_or_a_grant_cannot_be_written_on_the_overrides(field: str) -> None:
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        BuiltinAgentConfig.model_validate({field: "anything"})


# The reference rule


def test_the_default_and_a_binding_may_name_the_built_in_whether_or_not_it_is_served() -> None:
    config = Config(default_agent=BUILTIN_AGENT, devices={"aa:bb:cc:dd:ee:01": [BUILTIN_AGENT]})

    assert config.builtin_state.status is BuiltinStatus.UNPROVIDED
    assert check_references(config) == []


def test_the_names_a_refusal_lists_include_the_built_in() -> None:
    domain = DomainConfig(default_agent="nobody", agents={"sam": AgentConfig()})

    (problem,) = check_references(domain)

    assert problem.endswith(f"(defined: sam, {BUILTIN_AGENT})")


def test_an_override_naming_no_provider_is_refused_under_its_own_key() -> None:
    """Whether or not the built-in is served: this world leaves three
    stages unprovided, and the misspelled one is still refused."""
    domain = DomainConfig(providers=MOCKS, builtin_agent={"llm": "claud"})

    problems = check_references(domain)

    assert problems == [
        "builtin_agent.llm: names no llm provider that exists, and the name is not "
        "quoted back (defined: mock)"
    ]


def test_an_override_naming_no_fragment_is_refused_under_its_own_key() -> None:
    domain = DomainConfig(builtin_agent={"prompt_includes": ["swedish"]})

    (problem,) = check_references(domain)

    assert problem.startswith("builtin_agent.prompt_includes: entry 1 names no prompt")


def test_a_misspelled_override_is_reported_once_at_boot() -> None:
    with pytest.raises(ValueError) as refused:
        Config(providers=MOCKS, agent_defaults=EVERY_STAGE, builtin_agent={"tts": "nope"})

    assert str(refused.value).count("names no tts provider") == 1


def test_the_lane_s_shared_configurations_do_not_serve_the_built_in() -> None:
    """Why most suites meet no built-in agent: the two shared worlds
    leave a stage unprovided, so their served agents are the ones they
    name."""
    assert base_config().builtin_state.stages == ("tts",)
