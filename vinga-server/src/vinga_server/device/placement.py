"""What a conversation may ask and write about its own device record.

Two things, and both are about the record a conversation attached to
rather than about the board at the address it dialled.
`device/bindings.py` reads those rows on the path a board is served and
answered on; this writes one column of one of them on the path a person
says "you have been moved to the office", and it answers where that
record's memory is filed while the conversation writes to it (#449).

Three things it is here to do, none of which the tool layer or the
repository can do on its own:

- **It writes through the repository the CLI writes through**, so the
  rules about what a stored device location may be (not blank once
  folded, not a URL carrying a credential) are stated once, in the
  place every other device write already meets them. Every string a
  room says reaches that repository, including the ones it will refuse:
  a second opinion here about what counts as blank would be a rule with
  two homes, and the one furthest from the model that owns it is the
  one that drifts. Nothing here touches a table.
- **It addresses the record by its id.** A conversation attached to a
  record at its connect, and the MAC that record stands at can be
  deleted and bound again, or moved to another record, while the
  conversation is still talking. That is the same rule the per-round
  read keeps, one direction later.
- **It translates.** The repository's refusals are written for an
  operator at a command line: they name a command to run, a document to
  edit or a field to correct. Whoever is in the room can do none of
  those, so a refusal is answered in the tool layer's own closed
  vocabulary rather than forwarded, and no value a write rejected and
  nothing a driver said travels out with it.

The second of those needs one thing the first does not, and it is the
reason it is here rather than in the tool layer: a board swap moves a
record's MAC and everything filed under it in one transaction under the
domain writer lock, so a conversation writing device memory has to
resolve the address and write while holding that same lock. Inside the
block the memory chain's own lock is taken, which is key 3 after this
key 1, the ascending order `db.advisory_key` states.

The engine is not this module's. It belongs to the process, is opened
and disposed by the application's lifespan, and is the same one the
configuration API writes through: one writer, one advisory lock, one
pool. What is held here is a `ConfigStore` over it, which is a view
holding nothing to release.

The write is synchronous, like every other database call in this
server, and the caller is the event loop every live conversation shares.
So it goes to a worker thread exactly as the record read and the memory
lookup on the same reply do: a person is waiting through this call, and
running it inline would put the domain writer lock in front of every
other conversation the process is holding.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import AbstractContextManager, asynccontextmanager
from dataclasses import dataclass

from vinga_server.config.loader import (
    ConfigError,
    DatabaseBusyError,
    DeviceLocationBlankError,
    StorageError,
    UnknownEntityError,
)
from vinga_server.config.store import ConfigStore
from vinga_server.tools import builtin

logger = logging.getLogger(__name__)


class DevicePlacements:
    """The device records of this server, as a conversation may move
    them and as its memory is filed under them.

    One per app, built by the composition root over the engine that root
    owns. It holds nothing per conversation: which record a call means
    arrives with the call, because the conversation is what knows.
    """

    def __init__(self, store: ConfigStore) -> None:
        self._store = store

    @asynccontextmanager
    async def address(self, device: str) -> AsyncIterator[str | None]:
        """Where the record with this id stands, held there while the
        caller writes what that device remembers.

        The lock is the point. `ConfigStore.device_address` resolves
        inside the transaction that holds the domain writer lock and
        keeps holding it until this block leaves, and a board swap takes
        that lock before it reads, so a `remember` racing a replacement
        either lands first and is carried along by it or resolves
        afterwards and lands at the address it left. Without that, the
        two orders that lose a fact are one statement apart.

        None for a record that is no longer there, which is what a
        conversation whose device an operator deleted meets. It is not a
        refusal because the caller has somewhere true to fall back to,
        and this module has nothing better to tell it.

        Opened and closed in worker threads, because the driver is
        blocking and the caller is the event loop every live
        conversation shares. The transaction is entered in one thread
        and left in another, which is safe for the reason it is safe
        anywhere here: the two never touch it at once, and the awaits
        between them are the happens-before. What is NOT safe is running
        the open inline, since it can wait out the lock timeout.

        Every refusal is one of `tools.builtin`'s sentences, chosen
        inside the arm that caught it and raised outside, the rule
        `relocate` states and for the same reason: what the repository's
        exception carries is a connection string or a stored value.
        """
        opened = await asyncio.to_thread(self._opened, device)
        try:
            yield opened.standing
        finally:
            await asyncio.to_thread(opened.close)

    def _opened(self, device: str) -> "_Address":
        """The resolution, on a worker thread: the transaction entered,
        the answer read, and the exit kept for later.

        The context manager is driven by hand rather than with a `with`,
        which is the one place this file does that and needs its reason:
        what has to outlive this function is the LOCK, and a `with`
        would release it at the return.
        """
        refusal: str | None = None
        held = self._store.device_address(device)
        try:
            return _Address(held, held.__enter__())
        except DatabaseBusyError:
            refusal = builtin.DEVICE_MEMORY_BUSY
        except (StorageError, ConfigError):
            refusal = builtin.DEVICE_MEMORY_UNREACHABLE
        except Exception as exc:
            logger.warning("a device memory lookup failed: %s", type(exc).__name__)
            refusal = builtin.DEVICE_MEMORY_UNREACHABLE
        raise ValueError(refusal)

    async def relocate(self, device: str, location: str) -> str:
        """Write where the record with this id stands, answering with
        the location as the row now holds it.

        The answer is the stored value rather than the submitted one,
        the rule every device write here follows: a write normalizes
        what it was sent, and a confirmation quoting the request would
        tell the model something slightly different from what the next
        round will read back to it.

        Every refusal is one of `tools.builtin`'s sentences, raised as a
        `ValueError` the tool loop turns into an error result the model
        phrases. The sentence is chosen inside the arm that caught the
        refusal and raised outside it, so nothing of the repository's
        exception rides out on a chain: that exception holds the value
        the write rejected, which for this field is a sentence somebody
        said out loud into a microphone.
        """
        refusal: str | None = None
        try:
            written = await asyncio.to_thread(self._store.relocate_device_by_id, device, location)
        except UnknownEntityError:
            # The record is gone, which is what a conversation whose
            # device an operator deleted meets, and what a board a
            # default agent merely covers would meet if the tool had not
            # already refused it for having no record to attach to.
            refusal = builtin.NO_DEVICE_RECORD
        except DeviceLocationBlankError:
            # A place that holds nothing once folded. The rule is the
            # model's and the fold is the one every reader of it asks,
            # so what crosses here is which refusal happened rather than
            # a second opinion about the value; what a room needs back
            # is what the call was missing, since the repository's own
            # sentence names a command to run and a document key.
            refusal = builtin.LOCATION_NEEDS_A_PLACE
        except DatabaseBusyError:
            refusal = builtin.PLACEMENT_BUSY
        except StorageError:
            # A database that could not be read or written. In front of
            # the arm below rather than after it, because both are
            # `ConfigError`s and only the order tells them apart: a
            # storage failure answered as a value problem would tell a
            # room that the place it named was not a place, which is
            # wrong about the world and unactionable besides.
            refusal = builtin.PLACEMENT_FAILED
        except ConfigError:
            # What the repository refused about the value itself: a
            # place that folds to nothing, or one that is a URL carrying
            # a credential. One answer for both, because they share a
            # remedy and the repository refuses them with one type.
            refusal = builtin.LOCATION_NOT_A_PLACE
        # Deliberately everything else as well. A tool result is
        # interpolated from the exception that ended the call, so an
        # arbitrary failure here would put whatever it holds in front of
        # a model and into a stored turn. What is logged is the class
        # and nothing it carries, the rule the bindings view keeps about
        # the same database.
        except Exception as exc:
            logger.warning("a device relocation failed: %s", type(exc).__name__)
            refusal = builtin.PLACEMENT_FAILED
        if refusal is not None:
            raise ValueError(refusal)
        assert written.location is not None, "a relocation stores a location"
        return written.location


@dataclass(frozen=True)
class _Address:
    """One resolution in flight: the transaction holding the lock, and
    the answer it read.

    A value rather than two locals because the two halves cross a thread
    boundary together and are released together: `close` is the whole of
    what the caller owes for having asked.
    """

    held: AbstractContextManager[str | None]
    standing: str | None

    def close(self) -> None:
        self.held.__exit__(None, None, None)


__all__ = ["DevicePlacements"]
