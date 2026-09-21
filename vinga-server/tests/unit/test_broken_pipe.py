"""What is left behind when a reader stops reading.

`broken_pipe.py` makes two promises and only one of them can be seen
from inside a test process. The status is a value, and every command
that answers it asserts it where it answers. The other one is that
after `reader_stopped_reading` returns, nothing the interpreter does on
its way out can raise about the pipe again, and that is a claim about a
moment no test is running in: the streams are flushed after the last
frame has gone, where an exception has nowhere to be caught and Python
prints `Exception ignored in: <_io.TextIOWrapper name='<stdout>'>` and
exits 120 instead of returning what the program returned.

So this file drives a real process, and it is deliberately the smallest
one that reaches the moment: a hundred bytes written to a pipe whose
reader is already gone, a flush that fails, the function under test,
and an exit. Nothing here imports the CLI, because the CLI is not what
is being asked about.

**The premise the redirect rests on is that the buffer survives the
failed flush.** It does. A stream whose flush raised still holds the
bytes it could not write, so the interpreter's own flush meets the same
closed pipe with the same bytes, and the only thing that can stop it is
a descriptor pointing somewhere else. That was measured rather than
recalled, and the measurement is in
`docs/plans/2026-09-21-broken-pipe-at-shutdown.md`: the hypothesis that
CPython discards the buffered data is false, which is why deleting the
redirect looked safe and was not.

The payload is 100 bytes against a stream buffer of 8,192, two orders
of magnitude of headroom, because the construction only holds while the
write is small enough to be buffered. A write larger than the buffer
goes straight to the descriptor and raises inside `write`, before any
of this is reached, and the test would fail loudly with a traceback and
exit 1 rather than quietly passing for another reason.
"""

import os
import subprocess
import sys
from pathlib import Path

from vinga_server.broken_pipe import BROKEN_PIPE_STATUS

# What the child does, and every line of it carries weight.
#
# The write succeeds, because 100 bytes fit in the stream's buffer and
# nothing has yet tried to move them. The flush is what meets the closed
# pipe. The `except` arm is the one both entry points have, reached here
# without either of them, so what this file reports on is
# `reader_stopped_reading` and not a command's boundary.
#
# The last line is a guard rather than decoration: a `SystemExit` with a
# sentence exits 1 and prints it, so a construction that handed the
# child a readable pipe fails saying so instead of passing.
WRITER = """
import sys

from vinga_server.broken_pipe import reader_stopped_reading

try:
    sys.stdout.write("x" * 100)
    sys.stdout.flush()
except BrokenPipeError:
    raise SystemExit(reader_stopped_reading())
raise SystemExit("nothing was reading and the flush succeeded anyway")
"""


def test_a_retained_buffer_cannot_raise_at_interpreter_shutdown(
    tmp_path: Path,
) -> None:
    """The child exits with the shell's own status for a reader who has
    read enough, and says nothing on the way out.

    The reader is closed before the child exists rather than partway
    through its output, which is what makes this deterministic: there is
    no scheduling question about how much a reader drained first, and
    the child's first flush is certain to fail.

    Without the `os.dup2` in `reader_stopped_reading` this reports 120
    with `Exception ignored` on stderr, which is the exact symptom the
    function exists to prevent, arriving at the one point in a process
    where no arm of any `try` is left to answer it.
    """
    # A pipe with nobody on the reading end, before anything is written
    # to it. The child's stdout IS this descriptor: `subprocess.PIPE`
    # would make the parent the reader and put back the race this
    # construction removes.
    read_fd, write_fd = os.pipe()
    os.close(read_fd)
    child = subprocess.Popen(
        [sys.executable, "-c", WRITER],
        cwd=tmp_path,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        stdout=write_fd,
        stderr=subprocess.PIPE,
        text=True,
    )
    os.close(write_fd)
    errors = child.communicate()[1]
    status = child.returncode

    assert "Traceback" not in errors
    # And not the quieter spelling, which is the one this is really
    # about: a stream the interpreter cannot empty complains without a
    # traceback and takes the exit status with it.
    assert "Exception ignored" not in errors, (
        "the retained buffer reached the interpreter's own flush; "
        "suspect the redirect in reader_stopped_reading"
    )
    assert errors == ""
    assert status == BROKEN_PIPE_STATUS
