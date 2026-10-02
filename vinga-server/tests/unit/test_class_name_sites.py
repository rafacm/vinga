"""Every caught exception's class is named through one helper (#565).

A class can be given any name at all: `type(name, (Exception,), {})`
accepts any string, a line break and a forged log line after it
included. The typed event path has refused such a name since #217,
through `ClassName`; the sites that put a class into a retained log
line, a CLI sentence or an exception's message used to spell
`type(exc).__name__` and print whatever it held. They ask
`class_names.failure_name` now, which answers a lawful name exactly
as Python spells it and a fixed phrase for anything else.

Three representative sites are driven end to end here, one per kind of
surface: a log line (`device/placement.py`), an exception message
(`providers/kit.py`) and a CLI sentence (`device_endpoint.py`). Each is
pinned for a lawful name first, byte for byte, because the sweep that
moved them must not have changed what an operator reads on any
ordinary day, and then driven with the forged name.
"""

import logging

import pytest

from vinga_server.class_names import UNNAMED_FAILURE
from vinga_server.device.placement import DevicePlacements
from vinga_server.device_endpoint import close_failed
from vinga_server.providers.kit import call_failure
from vinga_server.tools import builtin

# A class named like a credential with a forged log line after it. The
# message is credential-shaped as well, so a site that printed the
# exception rather than its class would show up too.
FORGED = type("ghp_Secret\nFORGED line", (RuntimeError,), {})
PLANTED = "sk-test-565-never-a-real-credential"


def _either(forged: bool) -> BaseException:
    return FORGED(PLANTED) if forged else RuntimeError(PLANTED)


def _named(forged: bool) -> str:
    return UNNAMED_FAILURE if forged else "RuntimeError"


def _clean(said: str) -> None:
    assert "\n" not in said
    assert "ghp_Secret" not in said
    assert "FORGED" not in said
    assert PLANTED not in said


# --- a retained log line ----------------------------------------------


class _RefusingStore:
    """A configuration store whose relocation raises what it was given."""

    def __init__(self, failure: BaseException) -> None:
        self._failure = failure

    def relocate_device_by_id(self, device: str, location: str) -> object:
        raise self._failure


@pytest.mark.parametrize("forged", [False, True], ids=["lawful", "forged"])
async def test_a_failed_relocation_logs_a_validated_class_name(
    forged: bool, caplog: pytest.LogCaptureFixture
) -> None:
    placements = DevicePlacements(_RefusingStore(_either(forged)))  # type: ignore[arg-type]

    with caplog.at_level(logging.WARNING), pytest.raises(ValueError) as caught:
        await placements.relocate("aa:bb:cc:dd:ee:ff", "the kitchen")

    assert str(caught.value) == builtin.PLACEMENT_FAILED
    [record] = [r for r in caplog.records if r.name == "vinga_server.device.placement"]
    assert record.msg == "a device relocation failed: %s"
    assert record.args == (_named(forged),)
    _clean(record.getMessage())


# --- an exception's message, rendered later ---------------------------


@pytest.mark.parametrize("forged", [False, True], ids=["lawful", "forged"])
def test_a_provider_call_failure_names_a_validated_class(forged: bool) -> None:
    failure = call_failure("llm openai", _either(forged))

    assert str(failure) == f"llm openai: the request failed with {_named(forged)}"
    _clean(str(failure))


# --- a CLI sentence ---------------------------------------------------


class _UnclosableClient:
    """An HTTP client whose close raises what it was given."""

    def __init__(self, failure: BaseException) -> None:
        self._failure = failure

    def close(self) -> None:
        raise self._failure


@pytest.mark.parametrize("forged", [False, True], ids=["lawful", "forged"])
def test_a_connection_that_would_not_close_names_a_validated_class(forged: bool) -> None:
    said = close_failed(_UnclosableClient(_either(forged)), "http://vinga.example:8000")  # type: ignore[arg-type]

    assert said == (
        f"http://vinga.example:8000 answered, but the connection to it could not be closed "
        f"({_named(forged)}), so no verdict is printed: a probe that did not "
        f"finish cleanly is not one to call an endpoint healthy from. What the "
        f"library said is not repeated here."
    )
    assert said is not None
    _clean(said)
