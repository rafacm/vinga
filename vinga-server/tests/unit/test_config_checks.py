"""The reference check, run against a snapshot on its own.

Writes and the boot both run it. There used to be a second phase, the
completeness rule, which only the boot ran: a default agent required
when agents existed and no device was bound. #612 removed it, since a
default agent reaches no device, and the case it used to refuse is
pinned below as one that passes.
"""

from dataclasses import dataclass, field

from vinga_server.config import Config
from vinga_server.config.models import (
    AgentConfig,
    AgentDefaults,
    DeviceRecord,
    McpServerConfig,
    PromptFragmentConfig,
    ProviderConfig,
    ProvidersConfig,
    check_references,
)


@dataclass
class Snapshot:
    """A domain snapshot that is not a Config, which is the point: the
    checks run against the attributes, not against the class."""

    providers: ProvidersConfig = field(default_factory=ProvidersConfig)
    mcp_servers: dict[str, McpServerConfig] = field(default_factory=dict)
    prompt_fragments: dict[str, PromptFragmentConfig] = field(default_factory=dict)
    agent_defaults: AgentDefaults = field(default_factory=AgentDefaults)
    agents: dict[str, AgentConfig] = field(default_factory=dict)
    devices: dict[str, DeviceRecord] = field(default_factory=dict)
    default_agent: str | None = None


def _bound(**devices: list[str]) -> dict[str, DeviceRecord]:
    """The devices section as the snapshot holds it now: a record per
    MAC rather than the bare list #449 turned into shorthand."""
    return {mac: DeviceRecord(agents=agents) for mac, agents in devices.items()}


def _providers(**llm: str) -> ProvidersConfig:
    return ProvidersConfig(llm={name: ProviderConfig(type=type_) for name, type_ in llm.items()})


def test_a_resolved_snapshot_has_no_problems() -> None:
    snapshot = Snapshot(
        providers=_providers(claude="anthropic"),
        agents={"sam": AgentConfig(llm="claude")},
        default_agent="sam",
    )

    assert check_references(snapshot) == []


def test_an_unknown_provider_reference_is_a_reference_problem() -> None:
    snapshot = Snapshot(
        providers=_providers(claude="anthropic"),
        agents={"sam": AgentConfig(llm="ghost")},
        default_agent="sam",
    )

    problems = check_references(snapshot)

    assert problems == [
        "agents.sam.llm: names no llm provider that exists, and the name is not quoted "
        "back (defined: claude)"
    ]


def test_an_unknown_mcp_reference_is_a_reference_problem() -> None:
    snapshot = Snapshot(agents={"sam": AgentConfig(mcp=["home"])}, devices=_bound(aa=["sam"]))

    problems = check_references(snapshot)

    assert problems == [
        "agents.sam.mcp: entry 1 names no MCP server that exists, and the name is not "
        "quoted back; no mcp_servers entries are defined"
    ]


def test_an_unknown_binding_and_default_are_reference_problems() -> None:
    snapshot = Snapshot(
        devices={"aa:bb:cc:dd:ee:ff": DeviceRecord(agents=["ghost"])},
        default_agent="nobody",
    )

    problems = check_references(snapshot)

    assert (
        "default_agent: names no agent that exists, and the name is not quoted back; "
        "no agents are defined"
    ) in problems
    assert (
        "devices.aa:bb:cc:dd:ee:ff: entry 1 names no agent that exists, and the name is "
        "not quoted back; no agents are defined"
    ) in problems


def test_agents_no_device_reaches_are_a_deployment_awaiting_a_claim() -> None:
    """What the completeness rule used to refuse at boot: agents, no
    default agent, no device bound. A default agent reaches no device
    since #612, so requiring one bought nothing, and the configuration
    composes."""
    config = Config(agents={"sam": AgentConfig()})

    assert config.agents_for_device("aa:bb:cc:dd:ee:ff") == []
    assert check_references(Snapshot(agents={"sam": AgentConfig()})) == []


def test_an_empty_snapshot_passes_the_check() -> None:
    """Where every deployment starts, and where the natural creation
    order begins."""
    assert check_references(Snapshot()) == []
