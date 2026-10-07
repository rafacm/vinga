"""`builtin_agent_not_served`: an installed world says when it does
not serve vinga, the built-in agent, and why (#612, D6).

Once per installed world, at the first generation and at every later
one an apply installs, and never for a world that serves it. What it
carries is the closed set `builtin_status` decides and, for a world
wanting a provider, the stages it wants: no name an operator wrote
reaches it, which the sentinels below are planted to catch.
"""

import logging
from typing import Any

import pytest

from tests.support.configs import world
from tests.support.events import both_formats, events, fields_of
from vinga_server.config import Config
from vinga_server.config.models import BUILTIN_AGENT, PROVIDER_STAGES
from vinga_server.config.secrets import SecretStore
from vinga_server.generation import Generation

EVENT = "builtin_agent_not_served"

# Operator-chosen names, shaped like credentials, so a field or a
# sentence that carried what was written would be caught.
AGENT = "sk-agent-5c1e9a7f-never-a-real-credential"
PROVIDER = "sk-provider-2b8d4e60-never-a-real-credential"


def served() -> Config:
    stages = {stage: {PROVIDER: {"type": "mock"}} for stage in PROVIDER_STAGES}
    return Config(
        providers=stages,
        agent_defaults=dict.fromkeys(PROVIDER_STAGES, PROVIDER),
        agents={AGENT: {"prompt": "A"}},
    )


def displaced() -> Config:
    return Config(
        providers={stage: {PROVIDER: {"type": "mock"}} for stage in PROVIDER_STAGES},
        agent_defaults=dict.fromkeys(PROVIDER_STAGES, PROVIDER),
        agents={AGENT: {"prompt": "A"}, BUILTIN_AGENT: {"prompt": "the old vinga"}},
    )


def unprovided() -> Config:
    return Config(
        providers={"llm": {PROVIDER: {"type": "mock"}}, "tts": {PROVIDER: {"type": "mock"}}},
        agent_defaults={"llm": PROVIDER},
        builtin_agent={"tts": PROVIDER},
        agents={AGENT: {"prompt": "A"}},
    )


def said(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    return [fields_of(record) for record in events(caplog, EVENT)]


def test_a_first_world_that_serves_the_built_in_says_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO):
        world(served())

    assert said(caplog) == []


def test_a_displaced_world_says_so_with_its_token_alone(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO):
        world(displaced())

    (record,) = events(caplog, EVENT)
    assert record.levelno == logging.WARNING
    assert said(caplog) == [{"event": EVENT, "reason": "displaced"}]
    assert "vinga-server config agent rename vinga <new>" in record.getMessage()


def test_an_unprovided_world_names_the_stages_it_wants(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO):
        world(unprovided())

    assert said(caplog) == [{"event": EVENT, "reason": "unprovided", "stages": ["asr", "vad"]}]


@pytest.mark.parametrize("composed", [displaced, unprovided], ids=["displaced", "unprovided"])
def test_no_name_an_operator_wrote_reaches_the_event(
    caplog: pytest.LogCaptureFixture, composed: Any
) -> None:
    with caplog.at_level(logging.INFO):
        world(composed())

    rendered = both_formats(caplog)
    assert events(caplog, EVENT)
    assert AGENT not in rendered
    assert PROVIDER not in rendered


def test_every_installed_world_says_it_again_and_a_served_one_does_not(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """At the boot and at each apply, which is when the answer can
    change: unprovided, then served, then displaced."""
    with caplog.at_level(logging.INFO):
        generations = world(unprovided())
        for config in (served(), displaced()):
            with generations.applying() as install:
                install(Generation(config, SecretStore()))

    assert [one["reason"] for one in said(caplog)] == ["unprovided", "displaced"]
