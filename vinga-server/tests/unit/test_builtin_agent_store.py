"""The built-in agent's place in the store (#612): its overrides as a
singleton of their own, and the name nothing new may take.

`builtin_agent` mirrors `agent_defaults`: written whole, read back as
the empty entry when nobody wrote it, carried by the configuration
document through export, import and apply. A stored `agents.vinga` is
an operator's agent from before the built-in existed, so keeping or
editing one passes and only creating one (by a write, a document or a
rename) is refused, decided against what is stored.
"""

from collections.abc import Iterator
from typing import Any

import pytest
from cryptography.fernet import Fernet, MultiFernet
from sqlalchemy import insert, select

from tests.support.stores import body, planted, stored_rows
from vinga_server.config import ConfigError, views
from vinga_server.config.models import (
    BUILTIN_AGENT,
    PROVIDER_STAGES,
    AgentConfig,
    BuiltinAgentConfig,
    BuiltinStatus,
    DatabaseConfig,
    builtin_status,
)
from vinga_server.config.secrets import generate_key
from vinga_server.config.store import BUILTIN_NAME_RESERVED, ConfigStore
from vinga_server.db import open_database, schema

# What a refused request sent, planted so a refusal that quoted it would
# be caught: shaped like a credential, which is what a paste carries.
SENT = "sk-test-4f8b2c9e-never-a-real-credential"


@pytest.fixture
def store() -> Iterator[ConfigStore]:
    engine = open_database(DatabaseConfig())
    try:
        yield ConfigStore(engine, MultiFernet([Fernet(generate_key())]))
    finally:
        engine.dispose()


def providers(store: ConfigStore) -> None:
    for stage in PROVIDER_STAGES:
        store.set_provider(stage, "mock", {"type": "mock"})


def legacy_vinga(store: ConfigStore, entry: AgentConfig | None = None) -> None:
    """An `agents.vinga` row as a build from before the built-in wrote
    it: a lawful row, so its body is the model's own dump, planted
    underneath the repository because no current write can create it."""
    planted(
        store,
        insert(schema.agents).values(
            name=BUILTIN_AGENT, body=body(entry if entry is not None else AgentConfig())
        ),
    )


# The overrides, as a singleton


def test_unwritten_overrides_read_as_the_empty_entry(store: ConfigStore) -> None:
    assert store.read_builtin_agent().entry == BuiltinAgentConfig()
    assert store.load().domain.builtin_agent == BuiltinAgentConfig()


def test_the_overrides_are_written_whole_and_read_back(store: ConfigStore) -> None:
    providers(store)
    store.set_prompt_fragment("swedish", {"text": "Always reply in Swedish."})

    store.set_builtin_agent({"tts": "mock", "prompt_includes": ["swedish"]})
    store.set_builtin_agent({"llm": "mock"})

    read = store.read_builtin_agent().entry
    assert read == BuiltinAgentConfig(llm="mock")
    (row,) = stored_rows(store, select(schema.builtin_agent))
    assert row["id"] == schema.SINGLETON_ID


def test_an_override_naming_no_provider_is_refused_under_its_own_key(
    store: ConfigStore,
) -> None:
    with pytest.raises(ConfigError) as refused:
        store.set_builtin_agent({"llm": SENT})

    assert "\n  - builtin_agent.llm: names no llm provider" in str(refused.value)
    assert SENT not in str(refused.value)
    assert stored_rows(store, select(schema.builtin_agent)) == []


@pytest.mark.parametrize("field", ["prompt", "mcp"])
def test_the_overrides_take_no_prompt_and_no_grants(store: ConfigStore, field: str) -> None:
    with pytest.raises(ConfigError):
        store.set_builtin_agent({field: SENT})

    assert stored_rows(store, select(schema.builtin_agent)) == []


def test_the_stored_half_never_carries_the_built_in(store: ConfigStore) -> None:
    """However served the built-in is, what the store loads is what an
    operator wrote, so an export can never carry it as an agent."""
    providers(store)
    store.set_agent_defaults(dict.fromkeys(PROVIDER_STAGES, "mock"))

    domain = store.load().domain

    assert builtin_status(domain).status is BuiltinStatus.SERVED
    assert domain.agents == {}


def test_a_binding_and_the_default_may_name_the_built_in_before_it_is_served(
    store: ConfigStore,
) -> None:
    store.bind_device("aa:bb:cc:dd:ee:01", [BUILTIN_AGENT])
    store.set_default_agent(BUILTIN_AGENT)

    domain = store.load().domain
    assert domain.default_agent == BUILTIN_AGENT
    assert builtin_status(domain).status is BuiltinStatus.UNPROVIDED


# The name nothing new may take


def test_an_agent_cannot_be_created_under_the_built_in_s_name(store: ConfigStore) -> None:
    providers(store)

    with pytest.raises(ConfigError) as refused:
        store.set_agent(f" {BUILTIN_AGENT} ", {"prompt": SENT})

    assert str(refused.value) == BUILTIN_NAME_RESERVED
    assert stored_rows(store, select(schema.agents)) == []


def test_a_document_creating_it_is_refused_whole(store: ConfigStore) -> None:
    providers(store)

    with pytest.raises(ConfigError) as refused:
        store.apply(
            {
                "agents": {"sam": {"prompt": "SAM"}, BUILTIN_AGENT: {"prompt": SENT}},
            }
        )

    assert BUILTIN_NAME_RESERVED in str(refused.value)
    assert SENT not in str(refused.value)
    assert stored_rows(store, select(schema.agents)) == []


def test_an_agent_cannot_be_renamed_to_it(store: ConfigStore) -> None:
    store.set_agent("sam", {"prompt": "SAM"})

    with pytest.raises(ConfigError) as refused:
        store.rename_agent("sam", BUILTIN_AGENT)

    assert str(refused.value) == BUILTIN_NAME_RESERVED
    assert [row["name"] for row in stored_rows(store, select(schema.agents))] == ["sam"]


def test_an_operator_s_legacy_vinga_may_still_be_edited(store: ConfigStore) -> None:
    legacy_vinga(store, AgentConfig(prompt="OLD"))

    store.set_agent(BUILTIN_AGENT, {"prompt": "STILL MINE"})

    assert store.read_agent(BUILTIN_AGENT).entry.prompt == "STILL MINE"


def test_the_remedy_renames_the_legacy_vinga_away(store: ConfigStore) -> None:
    legacy_vinga(store, AgentConfig(prompt="OLD"))
    store.bind_device("aa:bb:cc:dd:ee:01", [BUILTIN_AGENT])

    renamed = store.rename_agent(BUILTIN_AGENT, "old-vinga")

    domain = store.load().domain
    assert renamed.devices == ("aa:bb:cc:dd:ee:01",)
    assert list(domain.agents) == ["old-vinga"]
    assert builtin_status(domain).status is not BuiltinStatus.DISPLACED


def test_a_displaced_deployment_s_export_applies_back_unchanged(
    store: ConfigStore,
) -> None:
    """Plan review finding 4: the export of a deployment whose legacy
    vinga displaces the built-in carries that agent, and applied back
    onto the store it came from it writes nothing at all, since apply's
    per-entry staging sees a row that exists rather than a creation."""
    providers(store)
    store.set_agent_defaults(dict.fromkeys(PROVIDER_STAGES, "mock"))
    store.set_builtin_agent({"tts": "mock"})
    legacy_vinga(store, AgentConfig(prompt="OLD"))
    store.bind_device("aa:bb:cc:dd:ee:01", [BUILTIN_AGENT])
    exported: dict[str, Any] = views.config(store.load())["config"]

    applied = store.apply(exported)

    assert exported["agents"] == {BUILTIN_AGENT: {"prompt": "OLD"}}
    assert exported["builtin_agent"] == {"tts": "mock"}
    assert [entry for entry in applied if entry.wrote] == []
