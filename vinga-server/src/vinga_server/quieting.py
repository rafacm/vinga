"""A third-party logger namespace, taken off this server's handlers for
as long as anything holds a claim on it (#66, #67).

Two surfaces in this repository drive a library whose own logging
carries an operator's credentials. The OTLP exporter's SDK logs the
endpoint it could not reach, and a URL with userinfo in it is a
credential in a retained log (`telemetry.py`). The capture uploader's
SDK and the HTTP stack under it log the request line of a PRESIGNED
upload URL, which is a credential in a query string
(`capture_upload.py`). Both answer it the same way and for the same
reason, so the mechanism lives here once rather than twice: two
structures that must agree are one structure with a bug pending.

What varies between them is the namespaces, which is the argument.
Everything else, the reference counting and the one-snapshot rule, is
the part that must not be written twice, because getting it wrong is
not a tidiness bug: it leaves a server either permanently silent or
loudly printing somebody's endpoint.
"""

import logging
import threading
from dataclasses import dataclass


@dataclass
class Lease:
    """One holder's claim on a namespace's silence.

    Handed out by `Quieting` below and given back exactly once, from
    whichever thread ends up owning the release. It holds no logging
    state of its own: what the namespace looked like is the process's
    fact, not this holder's, which is the whole of what this type exists
    to stop being confused about.
    """

    quieting: "Quieting"
    released: bool = False

    def release(self) -> None:
        self.quieting.give_back(self)


class Quieting:
    """One or more namespaces, quieted for as long as ANY holder has a
    lease on them.

    Process-wide and reference counted, because the logging
    configuration is process-wide and holders overlap. Each one used to
    snapshot and restore the namespace for itself, which is correct for
    one at a time and wrong the moment two exist, and two exist
    routinely: a wedged exporter's release outlives the bounded wait, so
    a redeploy that builds the next one while the last is still
    finishing had two live claims on one global.

    What that cost is worth spelling out, because it is not a tidiness
    argument. Holder A wedges and its wait times out. B is built and
    quietens an already-quiet namespace, so B's snapshot records
    SILENCE. A's abandoned release finally finishes and restores the
    ORIGINAL configuration, un-silencing the library while B is still
    working, so B's next failure logs its credentialed endpoint into the
    retained log. Then B's own release restores A's snapshot, which was
    the quiet one, and the namespace is silenced for the rest of the
    process with nothing holding it.

    So the snapshot is taken once, at the first acquisition, and put
    back once, after the last release, under one lock. A release for a
    lease already given back is a no-op, which is what lets a build's
    failure path and a release worker both call it without either having
    to know whether the other did.
    """

    def __init__(self, *namespaces: str) -> None:
        self.namespaces = namespaces
        self._lock = threading.Lock()
        self._held = 0
        # The process's own logging state, one entry per namespace, or
        # None when nothing holds a lease. It is deliberately not on the
        # lease: a second snapshot taken while the namespace is already
        # quiet is a recording of this module's own doing, and restoring
        # it is what leaves a server permanently silent.
        self._was: tuple[tuple[int, bool], ...] | None = None

    def take(self) -> Lease:
        """Take the whole of these namespaces off this server's
        handlers, and answer the claim to give back.

        Before the library is constructed, which is the ordering that
        matters: construction itself can log, and what it logs about is
        the endpoint it was given.

        Two mechanisms, because one of them alone has a hole.
        Propagation off at a namespace root means no record from any
        logger under it reaches a handler of ours, whichever module
        logged it. The level above CRITICAL means a child that has not
        set its own level does not build the record at all. An operator
        who wants the library's diagnostics can attach a handler to the
        namespace itself, which is a deliberate act rather than the
        default.
        """
        with self._lock:
            if self._held == 0:
                was = []
                for name in self.namespaces:
                    namespace = logging.getLogger(name)
                    was.append((namespace.level, namespace.propagate))
                    namespace.setLevel(logging.CRITICAL + 1)
                    namespace.propagate = False
                self._was = tuple(was)
            self._held += 1
            return Lease(quieting=self)

    def give_back(self, lease: Lease) -> None:
        """Drop one claim, and put the namespaces back if it was the
        last.

        The whole of it under the lock, the idempotence check included,
        so a lease released from a build's failure path and from a
        release worker at the same moment is counted once.
        """
        with self._lock:
            if lease.released:
                return
            lease.released = True
            self._held -= 1
            if self._held > 0 or self._was is None:
                return
            was = self._was
            self._was = None
            for name, (level, propagate) in zip(self.namespaces, was, strict=True):
                namespace = logging.getLogger(name)
                namespace.setLevel(level)
                namespace.propagate = propagate

    def held(self) -> int:
        """How many holders are keeping these namespaces quiet right
        now.

        Public because "is anything still holding this" is otherwise a
        question only a leak answers, and because the overlapping-
        lifespan case is one a test has to be able to describe.
        """
        with self._lock:
            return self._held
