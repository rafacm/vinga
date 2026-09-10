"""What a server does with the exporter it built, at both ends.

The exporter is the one resource in the composition that owns a
background thread and a piece of process-global state (the server tap
set), so its lifecycle is where the failures live rather than in the
span map:

- **A second lifespan must work.** The provider is this object's, never
  OTel's process-global one, so a process that ran an application, let
  it go and ran another gets a fresh working exporter both times. An
  implementation that installed a global would have exported nothing the
  second time, or exported it twice.
- **A partial startup must release what it built.** The exporter is
  built ahead of every resource a boot can open, so a refusal after it
  is exactly the case that would strand a thread and a tap.
- **The teardown has one order.** Stop accepting emissions, detach the
  server tap, then shut down. A detach after the shutdown would deliver
  into a closed provider; a shutdown before the detach would flush and
  then take more.

The span map itself is `test_telemetry.py`'s, and the saturated
collector is `tests/integration/test_telemetry_hardening.py`'s.
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient

import vinga_server.app as app_module
from tests.support.apps import entered_app
from tests.support.configs import config_with_agent
from tests.support.telemetry import (
    Clock,
    close_session,
    exporting,
    finished,
    open_session,
    session_events,
)
from vinga_server.app import StartupFailed, create_app
from vinga_server.config import Config
from vinga_server.config.loader import DatabaseBusyError
from vinga_server.config.models import DatabaseConfig
from vinga_server.events import server_taps
from vinga_server.telemetry import Telemetry

pytestmark = pytest.mark.asyncio(loop_scope="function")


def tracing_config() -> Config:
    """A server with telemetry on and everything else at its default."""
    return config_with_agent(
        server={"telemetry": {"enabled": True}, "database": DatabaseConfig().model_dump()}
    )


@pytest.fixture
def in_memory(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Every exporter a build in this test made, with the transport
    replaced by the SDK's in-memory one.

    The transport and nothing else: the build path under test is the
    real one, refusals included, and what is swapped out is the socket
    at the far end of it. A lane that stubbed `build_telemetry` would be
    a lane about its own stub.
    """
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    class Watched(InMemorySpanExporter):  # type: ignore[misc]
        """The in-memory exporter, plus a note of having been shut down.

        Which is the half a released exporter is otherwise silent
        about: an exit stack that skipped the shutdown would leave the
        SDK's thread running, and the spans it kept would look exactly
        the same either way.
        """

        def __init__(self) -> None:
            super().__init__()
            self.closed = 0

        def shutdown(self) -> None:
            self.closed += 1
            super().shutdown()

    made: list[Any] = []
    real = app_module.build_telemetry

    def building(config: Any, **rest: Any) -> Telemetry | None:
        memory = Watched()
        built = real(config, exporter=memory, batch_size=1, schedule_delay_ms=1, **rest)
        if built is not None:
            made.append(memory)
        return built

    monkeypatch.setattr(app_module, "build_telemetry", building)
    return made


async def test_two_sequential_lifespans_each_get_a_working_exporter(
    in_memory: list[Any],
) -> None:
    """The owned-provider claim, proven by running the whole thing
    twice.

    Each application's own exporter receives its own session's spans and
    nothing of the other's. A process-global provider would have shown
    up here as the second application exporting into the first's
    exporter, or into nothing at all.
    """
    config = tracing_config()
    for _ in range(2):
        with entered_app(config) as (app, _):
            telemetry = app.state.composition.telemetry
            assert telemetry is not None
            events = session_events(Clock(), telemetry)
            open_session(events)
            close_session(events)
            telemetry.flush()

    assert len(in_memory) == 2, "the second lifespan built no exporter of its own"
    for memory in in_memory:
        assert [span.name for span in memory.get_finished_spans()] == ["session"]
        assert memory.closed == 1, "a lifespan that ended left its exporter running"


async def test_a_build_that_fails_after_the_exporter_releases_it(
    in_memory: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The partial-startup case for the resource this milestone adds.

    The exporter is built first of everything, so every later refusal is
    this case; the configuration store's open is used as the refusing
    step for the reason the bindings case uses it, which is that a
    second writer holding the lock is a refusal a real deployment meets.

    Both halves of "released" are asserted, because the tap is the one
    that would survive the process: a provider left running is a thread,
    and a tap left attached is a dead application still receiving every
    server event the next one emits.
    """
    before = server_taps()

    def refuse(database: Any) -> Any:
        raise DatabaseBusyError("another process holds the write lock")

    monkeypatch.setattr(app_module, "open_store", refuse)

    app = create_app(tracing_config())
    with pytest.raises(StartupFailed):
        with TestClient(app):
            pass

    assert len(in_memory) == 1, "no exporter was built, so this proves nothing"
    assert in_memory[0].closed == 1, "a refused boot left the exporter's thread running"
    assert server_taps() == before, "a refused boot left its server tap attached"


async def test_the_exporter_stops_taking_before_it_is_detached() -> None:
    """The teardown's order, read off the object rather than off the
    exit stack.

    What `stop_accepting` is for is the window between a lifespan
    starting to tear down and the last session finishing: an emission
    arriving there would open a span nothing is going to close. So it is
    asked directly, which is the one thing that says the flag does
    something.
    """
    telemetry, memory = exporting()
    events = session_events(Clock(), telemetry)

    telemetry.stop_accepting()
    open_session(events)
    close_session(events)

    assert finished(telemetry, memory) == [], (
        "a session emitting into a tearing-down exporter opened a span"
    )
    await telemetry.shutdown()


async def test_a_server_without_the_section_holds_no_exporter() -> None:
    """And the default, through the composition: nothing built, nothing
    on the field, and no tap of its own on the server hub."""
    before = server_taps()
    with entered_app(config_with_agent()) as (app, _):
        assert app.state.composition.telemetry is None
        # The live hub is the one tap a server always attaches; what
        # must not be there is a second one.
        assert len(server_taps()) == len(before) + 1
