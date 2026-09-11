"""Which agents a device is bound to, read while the server runs.

The domain configuration is a snapshot a reload can replace, and this is
the one thing that is not read out of it at all. Binding a device is the
act an operator performs with the device in front of them, and the
device asks again seconds later: the OTA check that issues its token and
the websocket connect that starts its conversation both have to see a
binding written a moment ago, or onboarding a board would mean asking
the server to reload for every board. That is what this reads from the
database on every lookup; everything else about a world is asked for
(#191).

So the live view is exactly the two inputs of `Config.agents_for_device`:
the `devices` rows and `default_agent` in `domain_settings`. It resolves
by the same rule, the bound list else the default agent else nothing,
and it stops there.

It answers one more question off the same rows, added by #449 and kept
here rather than given a view of its own: what the device behind a MAC
is called and where it stands. The reply path asks it on every round,
because a device that was moved between two replies has moved for the
second of them, and a second live view of one table would be a second
engine, a second fallback and a second thing to dispose. It is
deliberately a separate read from the binding's: the binding decides
whether a board is served at all and its statement is pinned byte for
byte, while this one is asked by a conversation already in flight, and
nothing ever needs both answers at once.

What it deliberately does NOT do is decide which of those names this
server can serve. That decision belongs to whoever is about to act on
it, against the one generation they are acting in: a session captures a
world after this lookup's await and classifies against exactly that
object, so a reload landing in between lands wholly before or wholly
after the conversation being built rather than in the middle of it, and
the OTA paths classify against the world current when they answer. A
classification made here would be a second read of a second generation
at a different moment, which is the race the pinned handoff exists to
close. `BoundNames.against` is the one implementation of it, so the two
callers cannot come to disagree about a rule they both apply.

A name this server is not serving is not nothing: handing such a device
a token would invite a websocket the session layer has to refuse, with
nothing said about why. What is said instead is the reload that will
install it, and the callers log that distinctly.

Three properties this component exists to keep:

- **It never blocks the event loop and never migrates.** Its engine is
  created at app build, after boot has migrated, and reads through
  repeatable-read, read-only transactions that take no advisory lock
  (see `db.read_engine`); every lookup from async code goes through
  `resolve`, which awaits it on a worker thread.
- **A failed read is loud, not fatal, and says nothing of the failure
  but its kind.** The OTA endpoint is every device's boot dependency, so
  a `/data` hiccup must not refuse the fleet's check-ins. A lookup that
  cannot read the database logs a fixed warning and resolves from the
  generation this server is serving, so staleness is in the log rather
  than in nobody's knowledge. What the exception says is not in that line: a database
  error carries the statement, its bound parameters and whatever the
  driver quoted, and this path is reachable by anything the stored
  configuration holds. Only the exception's class name is recorded, in
  a field of its own.
- **A live session is not touched.** Resolution happens at token
  issuance and at connect. Deleting a binding stops the next one of
  each; it does not reach into a conversation already happening.
"""

import asyncio
from collections.abc import Collection
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import Engine

from vinga_server.config.models import default_device_name, normalize_mac
from vinga_server.config.store import (
    LiveAttachment,
    LiveBinding,
    LiveDevice,
    read_live_attachment,
    read_live_binding,
    read_live_device_by_id,
)
from vinga_server.db import read_engine
from vinga_server.events import ServerEvents
from vinga_server.events.catalog import BindingsUnreadable
from vinga_server.events.values import ClassName, DeviceId

if TYPE_CHECKING:
    # Deferred, and the one import here that is. `generation` reaches
    # the provider layer, and the onboarding module imports `DeviceAgents`
    # from here on a path the configuration CLI and the rendering of the
    # committed API document both take: a runtime import would put the
    # MCP SDK and every provider extra behind `vinga-server config
    # reference` (#143's weight pin). Nothing here needs the class
    # itself, only a holder to ask, so the name is a type and the
    # annotations that use it are strings.
    from vinga_server.config import Config
    from vinga_server.generation import Generations

events = ServerEvents(__name__)


@dataclass(frozen=True)
class BoundNames:
    """What a device's binding says, before anything has decided which
    of it this server can act on.

    The raw answer, and raw on purpose. The names come out of the
    database (or out of the generation this server is serving, when the
    database could not be read), and the question of which of them are
    servable has a different answer in every instant and is therefore
    the caller's to ask, against the one world it is acting in. See this
    module's docstring for why that is not a convenience.
    """

    names: tuple[str, ...]
    # Whether this answer is the database's or the served world's.
    #
    # False only when a live read failed and the configuration answered
    # in its place, which is a fallback that keeps a fleet's check-ins
    # served and cannot be trusted about what it does not say. The
    # difference matters to exactly one caller: an empty resolution is
    # what the activation ceremony reads as "no operator has bound this
    # device", and from a fallback it means "this server could not
    # find out". That caller is `onboarding.unbound.activation_for`,
    # which is where the whole question of what an unbound device gets
    # is decided (issue #143); the activation poll re-reads this view
    # and deliberately ignores this flag. Issuing a token off a stale
    # answer only ever repeats what the configuration already said;
    # minting a code off one would offer a stranger a claim ticket for
    # somebody's bound board.
    #
    # A configuration with no database behind it is authoritative: the
    # world being served is then the whole truth there is, which is what
    # a test lane and an embedded server have.
    authoritative: bool = True

    def against(self, servable: Collection[str]) -> "DeviceAgents":
        """This binding, split by what one world can serve.

        `servable` is the agents of exactly one generation, and which
        generation that is is the caller's decision: the session's is
        the world it is about to build a conversation from, and the OTA
        paths' is the world current as they answer. One implementation
        of the split, here rather than at the two call sites, because
        the difference between the two lists is what both of them say
        out loud to an operator.
        """
        return DeviceAgents(
            tuple(name for name in self.names if name in servable),
            tuple(name for name in self.names if name not in servable),
            self.authoritative,
        )


@dataclass(frozen=True)
class DeviceAgents:
    """What a device resolves to in one world: the agents it may talk
    to, and the ones its binding named that this world does not serve.

    Two fields rather than one list, because the two states they tell
    apart need different sentences said to the operator: a device with
    nothing bound is missing configuration, and a device bound to an
    agent this server is not serving is waiting for the reload that
    installs it.
    """

    agents: tuple[str, ...]
    unloaded: tuple[str, ...] = ()
    authoritative: bool = True

    def __bool__(self) -> bool:
        return bool(self.agents)


@dataclass(frozen=True)
class Attachment:
    """What one connect resolved about a device: the agents its binding
    names, and the record its conversation attaches to.

    Two fields because they answer two questions a connect asks at one
    instant, and one value because asking them apart is the race this
    type exists to close: a binding resolved from one snapshot and a
    record read from the next can describe two different devices.

    `record` is None where the board has no record to attach to, which
    is a MAC with no row that a default agent stands behind, and where
    the world being served has never named the device. A conversation
    that attached to nothing says nothing about its device, for its
    whole life: what an operator binds or names while it is talking
    reaches the next conversation rather than this one, which is the
    rule a live session already keeps about its agents.
    """

    names: BoundNames
    record: LiveDevice | None


class DeviceBindings:
    """The live view of the `devices` rows and `default_agent`.

    One per app, built by the composition root and disposed with it.
    Every lookup is its own read transaction: there is no cache, because
    the call rate is a device's boot check-in and its connect, and
    because a cache would need an invalidation path from every writer of
    the rows, which anything holding the file open can be. If a fleet
    ever makes this measurable, this class is the only place that has to
    change.
    """

    def __init__(self, generations: "Generations", engine: Engine | None) -> None:
        # The world this server is serving, asked rather than kept, and
        # asked for one thing only: what the two rows say when the
        # database cannot be read. A reload replaces the world while
        # this view goes on answering, so a configuration captured here
        # would become a fallback to a world that has been retired.
        self._generations = generations
        self._engine = engine

    @classmethod
    def open(cls, generations: "Generations") -> "DeviceBindings":
        """The view a server serves with: the holder whose generation is
        the fallback, and a read engine on the database boot read it
        from.

        No arm for a database that is not there. There used to be one,
        for a file a lookup could find missing; by the time bindings
        open, boot has either migrated this database or refused to
        start, so "not there" is not a state this can meet. A composed
        server that has no store at all builds `snapshot_only` instead,
        which is a decision made where the composition is rather than a
        probe made here.

        A read that fails once the server is running is a different
        thing entirely, and is still loud and not fatal: see
        `_read_binding`.
        """
        return cls(generations, read_engine(generations.current().config.server.database))

    @classmethod
    def snapshot_only(cls, generations: "Generations") -> "DeviceBindings":
        """The view with no database behind it, which resolves exactly
        what `Config.agents_for_device` resolves. What a caller handed no
        live view uses, so that resolution has one implementation rather
        than a live one and a fallback one that could come to disagree."""
        return cls(generations, None)

    @property
    def snapshot_authoritative(self) -> bool:
        """Whether there is no database behind this view, so what this
        server was handed is the whole truth there is.

        Decided once, at the open, and asked here rather than decided a
        second time somewhere else: which mode a server is in is a fact
        about how it was composed, and two places working it out is two
        places that can come to disagree. What reads it is the
        configuration API, whose comparison and whose apply both span a
        store and a running world and have nothing to span in this mode,
        and whose device writes can then say only that the write is
        stored.

        Named for what it asserts rather than for what is missing: the
        snapshot is authoritative here, which is why the answers this
        server gives about bindings are still exactly right. It is the
        answers about a STORE that have nowhere to come from.
        """
        return self._engine is None

    def dispose(self) -> None:
        """Close the connection pool. Called from the app's lifespan, so
        a server on its way out leaves no file handle behind."""
        if self._engine is not None:
            self._engine.dispose()

    async def resolve(self, mac: str) -> BoundNames:
        """`names_for`, awaited off the event loop.

        The device paths are async and the read is synchronous, so this
        is the only way they may call it: a lookup that ran inline would
        put a file open, and whatever the filesystem is doing at that
        moment, in front of every other conversation the process is
        holding.

        This await is also the moment the handoff is pinned around: a
        caller captures the generation it is going to act in AFTER this
        returns, so a reload landing during the lookup is a reload the
        caller either wholly precedes or wholly follows.
        """
        return await asyncio.to_thread(self.names_for, mac)

    def names_for(self, mac: str) -> BoundNames:
        """What this device is bound to, from the database when it can
        be read and from the world being served when it cannot.

        Names and nothing else: which of them can be served is a
        question about one generation, and the caller asks it.
        """
        normalized = normalize_mac(mac)
        stored, authoritative = self._stored(normalized)
        return self._bound(normalized, stored, authoritative)

    def _bound(
        self, mac: str, stored: LiveBinding | None, authoritative: bool
    ) -> BoundNames:
        """The binding rule, applied to whichever of the two sources
        answered.

        Here rather than inline because two methods reach it now:
        `names_for`, which reads two rows, and `attachment_for`, which
        reads those two and the record in one snapshot. The rule is the
        bound list else the default agent else nothing, and two copies
        of it would be a device answered one way by the check-in and
        another by the connect.
        """
        if stored is None:
            config = self._generations.current().config
            # The record's binding and not the record: what this answers
            # is which agents a board reaches, and the rest of what #449
            # put on a device record is `attachment_for`'s business.
            record = config.devices.get(mac)
            bound = () if record is None else tuple(record.agents)
            default = config.default_agent
        else:
            bound, default = stored.agents, stored.default_agent
        names = tuple(bound) if bound else ((default,) if default is not None else ())
        return BoundNames(names, authoritative)

    async def attach(self, mac: str) -> Attachment:
        """`attachment_for`, awaited off the event loop.

        What a connect asks instead of `resolve`, and the only reason it
        is a different question: a conversation needs the record it will
        speak through for the rest of its life, and that record has to
        come from the same instant the binding did.
        """
        return await asyncio.to_thread(self.attachment_for, mac)

    def attachment_for(self, mac: str) -> Attachment:
        """Which agents this board may reach and which record its
        conversation attaches to, from one snapshot.

        One read rather than two, because a record read a moment after
        a binding can belong to a different device: a MAC deleted and
        bound again in between is a new record at the same address, and
        a conversation built from the first answer and attached to the
        second would be told another board's name and place.

        The same fallback `names_for` keeps, applied to both halves
        together for the same reason: a world that answers the binding
        answers the record beside it.
        """
        normalized = normalize_mac(mac)
        stored, answered = self._attached(normalized)
        if answered and stored is not None:
            return Attachment(
                self._bound(normalized, stored.binding, True), stored.device
            )
        return Attachment(
            self._bound(normalized, None, self._engine is None),
            _snapshot_record(self._generations.current().config, normalized),
        )

    async def resolve_record(self, attached: LiveDevice) -> LiveDevice | None:
        """`record_now`, awaited off the event loop.

        What the reply path calls, and it calls it on every round: a
        device that was moved between two replies has moved for the
        second of them. The rule `resolve` states holds here with one
        more reason behind it: this read happens while a person is
        waiting for an answer, so running it inline would put a query in
        front of every other conversation this process is holding, once
        per round rather than once per connect.
        """
        return await asyncio.to_thread(self.record_now, attached)

    def record_now(self, attached: LiveDevice) -> LiveDevice | None:
        """The record a conversation attached to, as it stands now.

        Addressed by the identity rather than by the MAC, which is the
        whole of what the stable id is for: a MAC says where a board is
        standing, and an operator can delete a device and bind the same
        board again, or (from M4) move a MAC to another record, under a
        conversation that is already talking. Re-reading by MAC would
        hand that conversation whichever record now answers to the
        address; re-reading by id hands it the record it has been
        speaking through, or nothing.

        None means that record is gone, and a reply says no more about
        its device than one that never had a record. The alternative is
        going on saying something that stopped being true.

        The same fallback `names_for` keeps, and for the same reason
        rather than for symmetry: a `/data` hiccup mid-conversation must
        not make an agent stop knowing what it is speaking through. What
        the served world answers is what boot read, so it is right until
        somebody writes, and a write it has not heard about is staleness
        in one round's prompt rather than a device that forgot its own
        name.
        """
        stored, answered = self._stored_record(attached)
        if answered:
            return stored
        return _snapshot_reread(self._generations.current().config, attached)

    def _stored_record(self, attached: LiveDevice) -> tuple[LiveDevice | None, bool]:
        """The attached record as the database holds it now, and whether
        the database is what answered.

        The second half is the same distinction `_stored` draws and is
        read the other way round here, because the two callers want
        different things from it: a binding falls back whenever it has
        no row, since a default agent stands behind every unbound
        device; a record falls back only when nothing was read, since a
        database that answered "that record is gone" has answered.
        """
        if self._engine is None or attached.id is None:
            return None, False
        problem: Exception | None = None
        try:
            return read_live_device_by_id(self._engine, attached.id), True
        # Deliberately everything, the reason `_stored` gives: what is
        # being protected is a conversation in flight, and no failure of
        # this read is worth ending one over.
        except Exception as exc:
            problem = exc
        self._warn(attached.mac, problem)
        return None, False

    def _attached(self, mac: str) -> tuple[LiveAttachment | None, bool]:
        """Both halves as the database holds them, and whether the
        database is what answered. `_stored`'s shape, with the record
        beside the binding, and its `except Exception` for the same
        reason: a conversation is being built, and a device that cannot
        be read is served from the world this server booted with rather
        than turned away.
        """
        if self._engine is None:
            return None, False
        problem: Exception | None = None
        try:
            return read_live_attachment(self._engine, mac), True
        except Exception as exc:
            problem = exc
        self._warn(mac, problem)
        return None, False

    def _stored(self, mac: str) -> tuple[LiveBinding | None, bool]:
        """This device's binding and the default agent as the database
        holds them, and whether the answer came from the database at
        all.

        The reading itself belongs to the repository, which is where
        what a stored row means is decided; this is the caller that says
        what to do when it cannot be read, which is to answer from the
        world being served rather than to refuse a device.

        The second half of the answer separates the two ways of having
        no row to return. No database behind this view at all is an
        ordinary state and its answer is authoritative, the world being
        served being the whole truth there is; a read that failed is
        not, and a caller that reads "nothing is bound" as a fact has to
        be able to tell the two apart.
        """
        if self._engine is None:
            return None, True
        problem: Exception | None = None
        try:
            return read_live_binding(self._engine, mac), True
        # Deliberately everything. This is the fleet's boot dependency,
        # and the point of the fallback is that whatever went wrong with
        # the file or with what is in it, the device still gets the
        # answer boot would have given it. A row that cannot be
        # understood is included on purpose: reading it as "bound to
        # nothing" would refuse a device over a fact nobody established.
        # What must not be silent is that it happened.
        except Exception as exc:
            problem = exc
        self._warn(mac, problem)
        return None, False

    def _warn(self, mac: str, exc: Exception) -> None:
        """The fallback, said out loud and in fixed words.

        Nothing of the exception is rendered but its class name. A
        database error is not a sentence somebody wrote for a log: a
        DBAPI error carries the statement that failed and the parameters
        bound to it, a driver message can quote the file path or the
        value it choked on, and this warning is written on a path
        anything in the stored configuration can reach. The class name
        is a code identifier, which is the most that can be said here
        that a stored value could not have written, and it goes in a
        structured field rather than into the sentence so the sentence
        is the same string every time.
        """
        events.emit(
            lambda: BindingsUnreadable(
                device=DeviceId(mac), failure=ClassName.of(exc)
            )
        )


def _snapshot_record(config: "Config", mac: str) -> LiveDevice | None:
    """One device's record as the world being served holds it.

    A record with no name is no record here. The configuration model
    leaves every field but the agents optional, because absence in a
    document means "the repository decides", and a device bound by the
    bare agent-list shorthand has never been named by anybody: what the
    database would have answered for it is the default name its row was
    created with, and inventing one here would be this view answering a
    question no writer has.

    `id` travels as it was found, which is None for a configuration
    composed in Python rather than read from a store: such a world has
    no identities, and the re-read below addresses what it has.

    `named` is decided by the same comparison the stored read makes, so
    a fallback cannot say a board is named when the database would have
    said it is still carrying the default.
    """
    record = config.devices.get(mac)
    if record is None or record.name is None:
        return None
    return LiveDevice(
        id=record.id,
        mac=mac,
        name=record.name,
        location=record.location,
        named=record.name != default_device_name(mac),
    )


def _snapshot_reread(config: "Config", attached: LiveDevice) -> LiveDevice | None:
    """The attached record as the world being served holds it now.

    A snapshot is keyed by MAC and cannot be addressed any other way, so
    this looks the address up and then checks the identity: a world
    whose record at that MAC carries a different id is a world where
    this record is gone, and answering with the one standing there now
    would be the substitution the id-addressed read exists to prevent.

    A world with no identities at all (a configuration composed in
    Python) has nothing to check, and its MAC is the only address there
    is. Nothing can be deleted and re-created under such a server
    without a reload, which is the same event that would replace the
    world this reads.
    """
    record = _snapshot_record(config, attached.mac)
    if record is None:
        return None
    if attached.id is not None and record.id != attached.id:
        return None
    return record


__all__ = ["Attachment", "BoundNames", "DeviceAgents", "DeviceBindings"]
