# The device session owns its conversations

**Status:** Accepted (recorded 2026-09-23, deciding
[#484](https://github.com/rafacm/vinga/issues/484)). Supersedes the
active-agent attribution clause of
[2026-08-10-normalize-the-hardware-edge.md](2026-08-10-normalize-the-hardware-edge.md),
and nothing else in it.

## Context

The hardware-edge record put the active-agent attribution on
`SessionEvents`, the observability object both sides of the device
boundary are handed, for one reason: both sides attribute events to
whoever is talking, so both have to see the same activation at the same
moment, and the events object was the one thing both sides held. When
conversations became threads (#190) the thread each agent talks on went
beside it for the same reason, so the events object carried `agent`,
`conversation` and `device` as settable attributes.

Two things were true of that placement by 2026-09-23, measured at
`0fcc5c26`. Nothing inside `events/` read the pair: every emitter
already built its payload at its own emit site, `Identifier(...)` and
`ConversationId(...)`, so the attributes were state kept on an object
that only says things. And the rest of a session's conversation state
lived somewhere else, as three maps on `PipelineRuntime` kept in step
by the order of the statements that wrote them: the current thread per
agent, a history per thread, and the store's handle for each thread's
last write, with the three transitions (a handover, a new conversation,
a resume) each coded as a sequence of writes across the maps and the
two event attributes. The filler runner selected its clips by the
agent it read off the events object, so the pair there was domain
state, not an emission stamp.

Two issues needed that settled. #482's reply core wants to be extracted
from the runtime, and the reply path is what reads and writes that
state; without an owner it would take a temporary protocol over four
runtime fields. And #92 selects a runtime per device and per agent, so
a handover may cross runtimes, and a second runtime would have had to
learn the event subsystem's attributes to take part in a conversation.

## Decision

One object owns the live side of a device session's conversations:
`SessionConversations`, in `vinga_server/session_conversations.py`. A
device session is one connection episode from one board; powering the
board off ends it, and the next connect starts a new conversation with
the device's default agent, a past one coming back only through the
conversation tools, from the store. The object's lifetime is exactly
the connection's.

- **It holds** each agent's current thread, every thread's in-memory
  history, the store's handle for each thread's last write, and the
  active pair as one frozen value. **Its transitions are its methods**
  (`activate`, `start_new`, `reactivate`), each one synchronous call,
  and `mint` is the one place a conversation id is made.
- **The edge constructs it**, on the line that normalizes the MAC, and
  hands it to the runtime factory beside the events object. The edge
  rather than the runtime because the conversations belong to the
  device session and must outlive whichever runtime serves the active
  agent; the connection is the only object with that lifetime. The
  factory takes it as a required argument, and no runtime constructs
  one of its own.
- **It is the device's one authority** from normalization on. The
  events object takes a write-once snapshot of the MAC for the identity
  it stamps (`SessionEvents.identify`), refuses a second one, and holds
  no pair at all.
- **Both sides read the pair there**, at the emit site: the runtime for
  every record it stamps, the edge for `speaking_started` and the
  capture manifest, the filler runner for its clip lookups and its
  records.

The rationale the hardware-edge record gave for its placement, that
both sides must see one activation at one moment, is kept rather than
dropped. It is kept by one object both sides are handed, which is what
the events object was being used as, and the pair is now one value that
a move replaces whole, so no reader can see an incoming agent beside
the outgoing agent's thread.

## Consequences

- Nothing a person running vinga can observe changed: no event, field,
  log line, stored row or spoken sentence. The milestone that made the
  move pinned every pair an emission carries across every transition,
  and the two readers that take the pair after an await, before moving
  anything.
- The factory seam changed shape: `RuntimeFactory` takes the device
  session's conversations third, after the events object. A second
  runtime (#92) learns the owner's interface rather than the event
  subsystem's, and the test stub runtime is the proof that a runtime
  that is not a pipeline can.
- `SessionEvents` is shallower in the right direction: it says things
  and holds none of the domain state it used to.
- A thread resumed in the same device session is still rebuilt from
  the store rather than from the in-memory copy, so it has two copies
  kept in step only by the bounded pre-resume wait. The owner makes
  that visible in one place and deliberately does not change it; the
  store's copy is budgeted and hydrated, and preferring the other is a
  behavior change for an issue of its own.
- The close path purges each agent's current thread, as it always did,
  and the method that answers it says so in its name
  (`current_threads`). Whether a purge should reach threads a move
  replaced is a behavior question this record does not settle.
- There is still no user concept. On a device shared between speakers
  the current-thread map's key would widen to the speaker and the agent
  and `activate` would take the speaker; the owner would stay one per
  device session.
