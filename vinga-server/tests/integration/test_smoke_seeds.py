"""The smoke lane's seeding scripts, run against a scratch database.

CI runs these from inside the image, before each container starts, which
is the only place they matter and the one place a test lane cannot
reach. What it can do is run the same scripts against a database of its
own and read back what they wrote, which is what these tests are: each
image check is only a check if the configuration it boots on is the one
it claims, and a local engine creeping into the slim one would make it
pass for the wrong reason.

Running them also pins that they work at all: a fragment the models
refuse, or a write in an order the reference checks refuse, fails here
rather than in the image job.

They live in the integration lane because each script now starts a
server of its own to write through, polls it, and stops it: that
lifecycle is a large part of what is under test, so the scripts are run
exactly as CI runs them, unmodified, with no fixture serving them.

The environment they are handed is the harness's, and one thing in it is
load-bearing beyond any single script: the children these scripts spawn
write no bytecode because `script_environment` says so. The last test
here is about that assignment rather than about a script, and the first
one runs its script with the ambient flag stripped so that the
assignment is what is holding.
"""

import contextlib
import os
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests.conftest import throwaway_database
from tests.integration.conftest import BYTECODE_OFF, script_environment
from tests.smoke.conftest import DEVICE_MAC as SMOKE_MAC
from vinga_server.config.models import DatabaseConfig
from vinga_server.config.store import ConfigStore, DomainConfig
from vinga_server.db import open_database

SMOKE = Path(__file__).resolve().parents[1] / "smoke"

# The two engines the slim image leaves out. `silero` is deliberately
# not one of them: it is a core dependency, in both variants, running on
# every frame whichever ASR is configured.
LOCAL_ENGINES = {"faster_whisper", "piper"}


def _free_port() -> int:
    """A port nothing is listening on, so a test run does not collide
    with a development server on the default one. The script reads it
    from VINGA_SERVER__PORT, and so does the CLI inside it, since both
    resolve server.port through the same settings machinery."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _domain(database: str) -> DomainConfig:
    engine = open_database(DatabaseConfig(name=database))
    try:
        return ConfigStore(engine).load().domain
    finally:
        engine.dispose()


def seeded(script: str, tmp_path: Path, environment: dict[str, str] | None = None) -> DomainConfig:
    """What one seeding script writes, read back through the repository.

    The script is run verbatim, as CI runs it: it starts its own server,
    waits for it, writes through the API, and stops it again.
    """
    # A database of this run's own, which is what the throwaway
    # directory used to be: a seeding script starts a server, and a
    # server that booted on a store somebody else had already written
    # is a different scenario from the empty first start these are
    # about. A test that seeds twice gets two.
    with throwaway_database() as database:
        inherited = script_environment(
            without=["VINGA_CONFIG"],
            VINGA_SERVER__PORT=str(_free_port()),
            VINGA_DB_NAME=database,
            **(environment or {}),
        )
        subprocess.run(["sh", str(SMOKE / script)], check=True, env=inherited, timeout=180)

        return _domain(database)


@pytest.fixture
def no_ambient_bytecode_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run this test's script with PYTHONDONTWRITEBYTECODE not already in
    the environment, so the harness's own assignment is what stops the
    subprocesses writing caches.

    CI exports the variable for the whole job
    (`.github/workflows/vinga-server.yml`), which is right for
    everything that is not pytest and would make the lane's guard
    vacuous there: a harness that stopped setting the flag would still
    hand every child an environment carrying it, and the finalizer would
    find nothing to catch. Stripping it before the script runs is what
    makes the guard bite on a runner as well as on a laptop.

    Deleting it from this process is enough, because
    `script_environment` builds the child's environment by copying
    `os.environ`. It does not make this process write bytecode:
    `tests/conftest.py` sets `sys.dont_write_bytecode` rather than
    relying on the variable.

    One test is enough. The point is not to run the scripts in an
    unusual environment, it is to have somewhere the assignment is
    load-bearing, and seeding is seven CLI calls plus a server start, so
    the caches would be plentiful and immediate.
    """
    monkeypatch.delenv(BYTECODE_OFF, raising=False)


def test_the_smoke_conversation_runs_on_mock_providers(
    no_ambient_bytecode_flag: None, tmp_path: Path
) -> None:
    """No model downloads, no keys, no network: what the lane proves is
    that the image serves a conversation, not which engine speaks."""
    domain = seeded("seed.sh", tmp_path)
    for stage in ("llm", "asr", "tts", "vad"):
        for name, entry in getattr(domain.providers, stage).items():
            assert entry.type == "mock", f"{stage}.{name} is not a mock provider"
    # The smoke board bound by its MAC rather than reached through a
    # default agent, which admits no unbound device since #612.
    assert domain.devices[SMOKE_MAC].agents == ["assistant"]
    assert domain.default_agent is None


def test_the_slim_boot_config_names_no_local_engine(tmp_path: Path) -> None:
    """The slim image's boot check is only a check if its config would
    actually fail on an image without the extras. A local engine
    creeping in here would make it pass for the wrong reason."""
    domain = seeded("seed-slim.sh", tmp_path)
    for stage in ("asr", "tts", "llm"):
        for name, entry in getattr(domain.providers, stage).items():
            assert entry.type not in LOCAL_ENGINES, f"{stage}.{name} is a local engine"
    # silero is the deliberate exception: a core dependency, in both
    # variants, running on every frame whichever ASR is configured.
    assert domain.providers.vad["silero"].type == "silero"


def test_the_local_engine_config_really_names_one(tmp_path: Path) -> None:
    """And the negative check is only a check if its config would boot
    on the default image and fail on slim."""
    domain = seeded("seed-local-engines.sh", tmp_path)
    assert domain.providers.asr["whisper"].type == "faster_whisper"


@pytest.mark.parametrize(
    "script", ["seed.sh", "seed-slim.sh", "seed-local-engines.sh"]
)
def test_a_seed_ignores_an_ambient_api_url(
    served_api, tmp_path: Path, script: str
) -> None:
    """An VINGA_API_URL left over in a shell, or set in a CI job for
    another deployment, would otherwise take the writes and the bearer
    token with them while the server the script started stayed empty.
    The decoy here is a real server on a real database, so "it was
    ignored" is checked by looking at what the decoy holds rather than by
    the script merely not failing."""
    with throwaway_database() as decoy:
        with served_api(DatabaseConfig(name=decoy)) as decoy_url:
            domain = seeded(script, tmp_path, {"VINGA_API_URL": decoy_url})

        assert domain.devices[SMOKE_MAC].agents == ["assistant"]
        assert _domain(decoy).agents == {}
        assert _domain(decoy).devices == {}


# What stands in for `vinga-server` on the interrupted seeding's PATH:
# the real one, called with the same arguments, except that the call
# making the seeding's second write first says so and waits to be
# released. The call that starts the server goes straight through, and
# `exec` keeps the process the script started the one it later stops,
# so the script under test runs unmodified and so does everything it
# calls.
#
# The wait is bounded, so a test that died while holding it leaves a
# script that finishes rather than one that waits for ever.
HOLDING_STANDIN = """#!/bin/sh
if [ "${{1-}}" = config ]; then
    echo call >> {calls}
    if [ "$(wc -l < {calls})" -eq {hold_at} ]; then
        : > {held}
        i=0
        while [ ! -e {released} ] && [ "$i" -lt 600 ]; do
            sleep 0.1
            i=$((i + 1))
        done
    fi
fi
exec {real} "$@"
"""


# One step of a launch: set SIGINT to the named disposition, then exec
# the rest of the command line. A freshly exec'd interpreter rather than
# a `preexec_fn`, because a pre-exec hook runs Python in a forked copy
# of a process that may have other threads, and can deadlock inside
# `Popen` on a lock one of them held, before any timeout here applies.
# Here nothing runs between this process's fork and exec, and the step
# itself is a single-threaded program that execs at once.
_EXEC_WITH_SIGINT = (
    "import os, signal, sys; "
    "signal.signal(signal.SIGINT, getattr(signal, sys.argv[1])); "
    "os.execvp(sys.argv[2], sys.argv[2:])"
)


def _with_sigint(disposition: str, argv: list[str]) -> list[str]:
    """`argv`, started with SIGINT at `disposition` ("SIG_DFL" or
    "SIG_IGN").

    A non-interactive shell cannot trap a signal that was ignored when
    it started. A runner started as an asynchronous list
    (`uv run pytest ... &` from a script) starts with SIGINT ignored, as
    POSIX requires, and every child inherits that across `exec`. The
    script's `trap on_interrupt INT` is then silently a no-op, the
    signal is dropped, and the seeding finishes with status zero, which
    is the `assert 0 != 0` this case used to fail with. SIG_DFL is the
    disposition a terminal's foreground job has, which is the interrupt
    the script's handler is for.

    The process id survives every `exec`, so the process `Popen` started
    is the shell by the time a signal is sent to it.
    """
    return [sys.executable, "-c", _EXEC_WITH_SIGINT, disposition, *argv]


def test_an_interrupted_seeding_fails_and_leaves_no_server_behind(
    tmp_path: Path,
) -> None:
    """A seeding step that was interrupted must not look like one that
    finished, must not carry on writing, and must not leave the server
    it started running: CI would then hold a port and a data volume open
    for the container that comes next.

    The interrupt is sent while the script is provably mid-way, held at
    its second write by a stand-in on PATH, rather than when the server
    first answers: the test sees the server ready before the script
    does, so a signal sent then lands while the script is still starting
    it, and the writes this case is about never begin.
    """
    real = shutil.which("vinga-server")
    assert real is not None
    calls, held, released = (tmp_path / name for name in ("calls", "held", "released"))
    binaries = tmp_path / "bin"
    binaries.mkdir()
    standin = binaries / "vinga-server"
    standin.write_text(
        HOLDING_STANDIN.format(
            calls=shlex.quote(str(calls)),
            held=shlex.quote(str(held)),
            released=shlex.quote(str(released)),
            real=shlex.quote(real),
            hold_at=2,
        ),
        encoding="utf-8",
    )
    standin.chmod(0o755)

    port = _free_port()
    stack = contextlib.ExitStack()
    database = stack.enter_context(throwaway_database())
    environment = script_environment(
        without=["VINGA_CONFIG"],
        VINGA_SERVER__PORT=str(port),
        VINGA_DB_NAME=database,
        PATH=f"{binaries}{os.pathsep}{os.environ['PATH']}",
    )

    seeding = subprocess.Popen(
        # Launched the way the failure this case once had was: with
        # SIGINT ignored, as a runner started in the background has it,
        # whatever this run inherited. Every run then reproduces that
        # condition, a foreground CI run included, and the reset step
        # inside it is what the case depends on rather than an accident
        # of how pytest was started.
        _with_sigint("SIG_IGN", _with_sigint("SIG_DFL", ["sh", str(SMOKE / "seed.sh")])),
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        # Its own process group, so the signal reaches the script the way
        # a shell would send it and not this test runner as well.
        start_new_session=True,
    )
    try:
        # As long as the seeding itself may take to start its server.
        _wait_for(held.exists, "the seeding never reached its second write", timeout=180)
        # Sent while the script waits on the held write. The shell runs
        # its trap once that command returns, so the signal is already
        # pending when the write is let go, whatever the scheduler does.
        seeding.send_signal(signal.SIGINT)
        released.touch()
        _, errors = seeding.communicate(timeout=60)
        written = _domain(database)

        assert seeding.returncode != 0
        assert "interrupted" in errors
        # The write it was in finished, and none after it began: the
        # seeding stopped where it was interrupted rather than running on.
        assert calls.read_text(encoding="utf-8").count("call") == 2
        stages = {s for s in ("llm", "asr", "tts", "vad") if getattr(written.providers, s)}
        assert stages == {"llm", "asr"}
        assert written.default_agent is None
        # And the server it started is gone with it.
        _wait_for(lambda: not _listening(port), "the seeding server outlived the script")
    except BaseException as failure:
        # The whole group, so a server the script left behind goes too,
        # and gone before the database it was on is dropped below.
        if not _end_group(seeding):  # pragma: no cover, only if SIGKILL fails
            failure.add_note(f"the seeding's process group outlived SIGKILL by {GROUP_GONE_S} s")
        raise
    finally:
        released.touch()
        if seeding.poll() is None:  # pragma: no cover, only on a failure
            seeding.communicate(timeout=30)
        # The database this script's server was on, taken away only once
        # nothing is connected to it.
        stack.close()


# How long a killed process group may take to disappear. Measured at
# about 10 ms on a four-core machine; the bound is for a loaded one.
GROUP_GONE_S = 10.0


def _end_group(process: subprocess.Popen, timeout: float = GROUP_GONE_S) -> bool:
    """Kill every process in `process`'s group and wait, bounded, until
    none is left. True when the group is gone.

    The group is the one `start_new_session` made, led by `process`, and
    it outlives its leader for as long as any member does: a server the
    script started and did not stop is still in it after the shell has
    exited and been reaped, which is the case killing the shell alone
    missed. SIGKILL is not synchronous, so the members are still there
    when `killpg` returns, and waiting for nothing would let the caller
    drop a database a dying server is still connected to.
    """
    group = process.pid
    with contextlib.suppress(ProcessLookupError):
        os.killpg(group, signal.SIGKILL)
    # The leader is this process's own child, and an unreaped one would
    # keep the group in existence as a zombie.
    if process.poll() is None:
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.communicate(timeout=timeout)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.killpg(group, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.05)
    return False


def test_ending_a_group_outlasts_its_leader() -> None:
    """The failure path's cleanup, on the shape it exists for: a leader
    that has exited and been reaped, and a descendant that has not.

    Checked straight after the call rather than eventually, because a
    killed group is still there when `killpg` returns, so a cleanup
    that signalled without waiting would fail here.
    """
    leader = subprocess.Popen(
        ["sh", "-c", "sleep 300 & exit 0"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    leader.wait(timeout=30)
    try:
        # The shape holds: the leader is gone and the group is not.
        os.killpg(leader.pid, 0)

        assert _end_group(leader)
        with pytest.raises(ProcessLookupError):
            os.killpg(leader.pid, 0)
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(leader.pid, signal.SIGKILL)


def _listening(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(1)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def _wait_for(ready, complaint: str, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if ready():
            return
        time.sleep(0.1)
    raise AssertionError(complaint)


def test_a_seeding_script_reports_a_server_that_will_not_start(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    """The failure the polling loop exists for. Without the API token the
    server refuses to boot, which is what a deployment that skipped the
    upgrade note meets, and a seeding script that hung on it would say
    nothing at all."""
    environment = script_environment(
        without=["VINGA_CONFIG", "VINGA_API_SECRET"],
        VINGA_SERVER__PORT=str(_free_port()),
    )

    finished = subprocess.run(
        ["sh", str(SMOKE / "seed.sh")],
        env=environment,
        capture_output=True,
        text=True,
        timeout=180,
    )

    assert finished.returncode != 0
    assert "exited before it was ready" in finished.stderr
    # And the server's own log is what says why, which is the whole point
    # of keeping it.
    assert "VINGA_API_SECRET" in finished.stderr


def test_a_script_environment_writes_no_bytecode_whatever_it_is_asked_for(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The assignment on its own, with no script and no subprocess.

    Every way the flag could come out of the helper wrong, in one place
    and in a second rather than in a minute: absent from this process,
    set to something falsy here, or overridden by a caller that names
    the variable itself. Overrides are applied before the assignment
    precisely so the last of those cannot happen, and `without` is
    checked too, since a caller stripping the variable is asking for the
    environment it names rather than for bytecode.

    What CPython reads is whether the value is a non-empty string, so
    "0" would stop the writes and an empty one would not stop anything:
    the empty case is the real hole of the three, and the other two are
    here because the reader cannot be expected to know which is which.
    The helper answers "1" to all of them, which is the one spelling
    every reader of this environment already understands.
    """
    monkeypatch.delenv(BYTECODE_OFF, raising=False)
    assert script_environment()[BYTECODE_OFF] == "1"
    assert script_environment(**{BYTECODE_OFF: "0"})[BYTECODE_OFF] == "1"
    assert script_environment(**{BYTECODE_OFF: ""})[BYTECODE_OFF] == "1"
    assert script_environment(without=[BYTECODE_OFF])[BYTECODE_OFF] == "1"

    monkeypatch.setenv(BYTECODE_OFF, "0")
    assert script_environment()[BYTECODE_OFF] == "1"
