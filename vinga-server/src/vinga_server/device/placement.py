"""Where a conversation may say its device is standing.

The one write a room can make to a device record, and the whole of what
this module is: `device/bindings.py` reads those rows on the path a
board is served and answered on, and this writes one column of one of
them on the path a person says "you have been moved to the office"
(#449).

Three things it is here to do, none of which the tool layer or the
repository can do on its own:

- **It writes through the repository the CLI writes through**, so the
  rules about what a stored device location may be (not blank once
  folded, not a URL carrying a credential) are stated once, in the
  place every other device write already meets them. Nothing here
  touches a table.
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

from vinga_server.config.loader import (
    ConfigError,
    DatabaseBusyError,
    StorageError,
    UnknownEntityError,
)
from vinga_server.config.store import ConfigStore
from vinga_server.tools import builtin

logger = logging.getLogger(__name__)


class DevicePlacements:
    """The device records of this server, as a conversation may move
    them.

    One per app, built by the composition root over the engine that root
    owns. It holds nothing per conversation: which record a call means
    arrives with the call, because the conversation is what knows.
    """

    def __init__(self, store: ConfigStore) -> None:
        self._store = store

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


__all__ = ["DevicePlacements"]
