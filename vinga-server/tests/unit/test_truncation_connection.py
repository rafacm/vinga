"""The truncation reuses one connection, and survives losing it.

`clear_store` used to open a connection, truncate, and close it again,
once for every test in this lane. Holding it instead is worth 7.4
seconds of the full lane (#489), and it introduces a failure the
disposable version could not have: a connection that outlives the test
that broke it.

These tests are about that trade. They go through `clear_store`, which
is the name a caller reaches, and identify the backend it is using
from outside, by asking `pg_stat_activity` for the application name the
truncation connects under. Nothing here reaches for the connection
object, because a test that did would be pinning the mechanism rather
than the behaviour.
"""

import threading

import psycopg
import pytest

from tests.conftest import (
    DB_HOST,
    DB_PASSWORD,
    DB_PORT,
    DB_USER,
    LANE_DATABASE,
    TRUNCATION_APPLICATION,
    clear_store,
)

# A row to leave behind, in a table with nothing but two required
# columns, so that "the truncation ran" is checked by its effect rather
# than by its return.
SEED = ('"domain"."domain_settings"', "key", "value")

# The settings table stores its value as JSON, so the seed has to be a
# JSON document rather than a bare word.
SEED_VALUE = '"present"'



@pytest.fixture
def observer():
    """A connection of this test's own, for watching and interfering.

    Separate from anything the lane uses, so that terminating the
    truncation's backend below cannot take this one with it.
    """
    connection = psycopg.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD,
        dbname=LANE_DATABASE, autocommit=True,
    )
    try:
        yield connection
    finally:
        connection.close()


def _truncation_backends(observer) -> list[int]:
    """Every backend on this database that is the lane's truncation."""
    return [
        row[0]
        for row in observer.execute(
            "select pid from pg_stat_activity "
            "where datname = %s and application_name = %s",
            (LANE_DATABASE, TRUNCATION_APPLICATION),
        ).fetchall()
    ]


def _seed(observer) -> None:
    table, key, value = SEED
    observer.execute(
        f"insert into {table} ({key}, {value}) values (%s, %s) "
        f"on conflict ({key}) do update set {value} = excluded.{value}",
        ("vinga-test-seed", SEED_VALUE),
    )


def _seeded_rows(observer) -> int:
    table, key, _ = SEED
    return observer.execute(
        f"select count(*) from {table} where {key} = %s", ("vinga-test-seed",)
    ).fetchone()[0]


def test_two_cleanups_run_on_one_backend(observer) -> None:
    """The point of the change: the second truncation does not connect.

    This is the case that fails against a `clear_store` which opens and
    closes per call, because the two backends would differ.
    """
    clear_store()
    first = _truncation_backends(observer)
    assert len(first) == 1, (
        f"expected exactly one held truncation backend, found {len(first)}"
    )

    clear_store()
    second = _truncation_backends(observer)
    assert second == first, (
        "the truncation opened a second backend rather than reusing the one "
        "it already had"
    )


def test_a_terminated_backend_is_replaced_once_and_the_work_still_happens(
    observer,
) -> None:
    """Losing the held connection costs one reconnect, not a cascade.

    Both halves matter. A retry that reconnected and returned without
    truncating would satisfy a test that only checked for an exception,
    so the seeded row is what says the work completed.
    """
    clear_store()
    [held] = _truncation_backends(observer)

    _seed(observer)
    assert _seeded_rows(observer) == 1, "the seed did not land"

    observer.execute("select pg_terminate_backend(%s)", (held,))

    clear_store()

    after = _truncation_backends(observer)
    assert len(after) == 1, (
        f"expected one backend after the replacement, found {len(after)}"
    )
    assert after != [held], "the terminated backend was somehow still in use"
    assert _seeded_rows(observer) == 0, (
        "the truncation reconnected but did not clear the store, so the "
        "retry returned without doing the work"
    )


def test_a_held_lock_still_fails_the_test_rather_than_reconnecting(
    observer,
) -> None:
    """The one error that must not be retried.

    `LockNotAvailable` is an `OperationalError`, so an arm that caught
    the broken-connection case too broadly would swallow it. Retrying
    would also sit through a wait this lane refuses to make, and would
    hide the defect the sentence names.
    """
    clear_store()
    [before] = _truncation_backends(observer)

    table, _, _ = SEED
    observer.execute("begin")
    observer.execute(f"lock table {table} in access exclusive mode")
    try:
        with pytest.raises(AssertionError, match="holding a lock on the store"):
            clear_store()
    finally:
        observer.execute("rollback")

    assert _truncation_backends(observer) == [before], (
        "a held lock replaced the truncation connection, so the lane "
        "reconnected on an error that is a defect in the test rather than a "
        "problem with the connection"
    )


def test_a_lock_met_after_a_reconnect_still_reads_as_a_lock(observer) -> None:
    """The retry gets the same error mapping as the first attempt.

    The two attempts are separate calls, so the second could easily
    have been written outside the arm that names a held lock, and then
    a test that killed the connection and left a writer holding a lock
    would meet a raw driver exception instead of the lane's sentence.
    This is the case that distinguishes the two shapes.
    """
    clear_store()
    [held] = _truncation_backends(observer)

    table, _, _ = SEED
    observer.execute("select pg_terminate_backend(%s)", (held,))

    locker = psycopg.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD,
        dbname=LANE_DATABASE, autocommit=False,
    )
    try:
        locker.execute(f"lock table {table} in access exclusive mode")
        with pytest.raises(AssertionError, match="holding a lock on the store"):
            clear_store()
    finally:
        locker.rollback()
        locker.close()


def test_the_retry_happens_once_and_a_second_failure_escapes(observer) -> None:
    """One retry, never a loop.

    Every other case here injects a single broken attempt, so an
    unbounded retry would satisfy all of them: the loop would simply
    never go round twice. This one makes **both** attempts break, with
    a `BEFORE TRUNCATE` trigger that terminates whichever backend is
    running the truncation, so a bounded implementation gives up and
    says so while an unbounded one reconnects forever.

    That is also why the call is driven on a thread with a deadline.
    An implementation that looped would otherwise hang this suite
    rather than fail it, and a hang is a far worse thing to hand a
    reader than an assertion.
    """
    table, _, _ = SEED
    observer.execute(
        "create or replace function vinga_test_kill() returns trigger "
        "language plpgsql as $$ begin "
        "perform pg_terminate_backend(pg_backend_pid()); return null; end $$"
    )
    observer.execute(
        f"create trigger vinga_test_kill_t before truncate on {table} "
        f"for each statement execute function vinga_test_kill()"
    )
    try:
        outcome: list[object] = []

        def drive() -> None:
            try:
                clear_store()
                outcome.append(None)
            except BaseException as caught:  # noqa: BLE001 - reported below
                outcome.append(caught)

        runner = threading.Thread(target=drive, daemon=True)
        runner.start()
        runner.join(timeout=30)

        assert not runner.is_alive(), (
            "clear_store did not finish within 30s while every attempt broke "
            "its connection, so the single retry has become an unbounded "
            "reconnect loop"
        )
        [result] = outcome
        assert isinstance(result, AssertionError), (
            f"expected the second failure to escape as the lane's own "
            f"refusal, got {type(result).__name__}"
        )
        assert "second failure" in str(result), (
            "the escape did not use the sentence that says this was a second "
            "failure rather than a dropped connection, so the two cases "
            "cannot be told apart by a reader"
        )
    finally:
        observer.execute(f"drop trigger if exists vinga_test_kill_t on {table}")
        observer.execute("drop function if exists vinga_test_kill()")


def test_no_failure_carries_the_driver_s_own_words(observer) -> None:
    """The no-leak rule, at this surface.

    Every sentence this path raises is fixed text built in the handler.
    A driver exception from here can quote the DSN it was opening,
    password included, and the statement ones quote whatever a test
    left in the database, so none of them may be reachable from what
    travels: not in the message, and not through `__cause__` or
    `__context__` either.
    """
    clear_store()
    [held] = _truncation_backends(observer)

    table, _, _ = SEED
    observer.execute("select pg_terminate_backend(%s)", (held,))

    locker = psycopg.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD,
        dbname=LANE_DATABASE, autocommit=False,
    )
    try:
        locker.execute(f"lock table {table} in access exclusive mode")
        with pytest.raises(AssertionError) as caught:
            clear_store()
    finally:
        locker.rollback()
        locker.close()

    assert caught.value.__cause__ is None, (
        "the refusal carries the driver's exception as its cause, so a "
        "traceback renderer will print the driver's words"
    )
    assert caught.value.__context__ is None, (
        "the refusal was raised inside the handler, so the driver's "
        "exception is still reachable through __context__"
    )
    rendered = str(caught.value)
    assert DB_PASSWORD not in rendered
    assert "psycopg" not in rendered.lower()
