# The local baseline is enumerated

**Status:** Accepted (recorded 2026-09-12, deciding issue
[#485](https://github.com/rafacm/vinga/issues/485))

## Context

The fully-local promise in
[`../architecture/product-promises.md`](../architecture/product-promises.md)
opened with "Every core conversational capability is reachable with
local providers". The 2026-09-12 external architecture review flagged
the phrase as open-ended: nothing said how a capability becomes
"core", so every new feature was implicitly core until argued
otherwise, and the promise's own counterexample named "barge-in
quality" as a core capability, which quietly extended the obligation
from function to quality.

Three pressures made the bound worth deciding now rather than at the
first collision:

- **The parity obligation had no limit.** As capabilities accrue, an
  unbounded "every core capability" becomes a feature-parity program
  against whatever the best runtime does. A native speech-to-speech
  runtime has barge-in behavior inherent to its design; quality
  parity against it on the staged local pipeline is not a bounded
  engineering task.
- **The quality clause failed the promise page's own standard.** A
  promise is falsifiable from outside: someone with a board and no
  source access can check it. They can check that interruption
  works; they cannot check "quality" without a specification nobody
  has written.
- **Sibling runtimes make it concrete.**
  [#92](https://github.com/rafacm/vinga/issues/92) proposes runtimes
  selectable per device and per agent, and the promise already
  expected an inherently-cloud sibling as "fine and expected". The
  design needs to know what the local path owes before the first
  sibling arrives, not during its review.

The drift fear the open wording protected against is real and stays
protected: the failure mode was never someone deleting the local
path, it was features quietly no longer landing on it. A bound is
acceptable only if it keeps that drift visible.

## Decision

The promise names a closed, observable baseline instead of an open
class. A server whose declared data boundary is local and that
starts can hold a complete conversation with local providers,
meaning all of:

- a conversation from wake through a spoken reply;
- end-of-turn detection;
- an interruption during playback that is heard and stops the reply,
  promptly enough to converse;
- agent memory;
- tool use.

Around the list, five rules:

1. **Membership is by recorded decision, flagged at development
   time.** Every committed plan and every feature doc answers the
   local-baseline question in one line: *not applicable* (no
   conversational capability changes), *outside* (a capability the
   baseline does not grow to include, with the reason), or *joins*
   (with this record or a successor cited, and the promise page
   updated in the same change). The line is required by the
   `implement-issue` plan shape and by the feature-doc convention,
   so the decision cannot be skipped silently while costing one
   line where it does not apply.
2. **Quality and latency may differ.** The baseline promises each
   listed capability works locally, not that every implementation
   of it is equal. Barge-in carries the one qualitative bound in
   the list ("promptly enough to converse") deliberately: with no
   promptness language the function clause could be satisfied by an
   interruption that lands seconds late, and with a stated budget
   the promise page would become a performance contract, which
   nothing else on it is. A field test can fail the coarse phrasing;
   a benchmark cannot litigate it.
3. **Runtime-specific capabilities above the baseline are allowed.**
   This was the promise's own example; it is now a stated bound
   rather than an illustration.
4. **Two limits are part of the promise.** The enforcement mechanism
   admits declarations, not behavior: it is not a network sandbox
   and proves nothing about a remote endpoint. And stage-by-stage
   provider mixing is a property of staged runtimes; a native
   speech-to-speech runtime may own several stages together.
5. **The boundary bounds defaults, not capabilities.** The promise
   constrains how session data may leave (declared destinations,
   refusal at build, everything off by default) and what a locally
   bounded server can never do; it does not forbid features whose
   purpose is sending content out. A deliberately enabled content
   export (a capture attached to a trace, transcripts to an
   evaluation backend) is lawful when it rides a content surface,
   declares its destination like any provider, defaults off, and
   refuses under a local boundary. Such a feature is the mechanism
   demonstrating its worth, not an exception carved out of it. Which
   channel content may ride and at what fidelity is the
   content-and-telemetry record's subject, not this one's.

## Consequences

- The promise section is rewritten to carry the list, the membership
  rule, and the limits, citing this record. The counterexample keeps
  the drift story and loses the "barge-in quality" phrase that made
  quality parity an implied obligation.
- The `implement-issue` plan shape and the feature-doc convention in
  `AGENTS.md` gain the required local-baseline line.
- [#92](https://github.com/rafacm/vinga/issues/92) can admit a
  sibling runtime that exceeds the baseline without a promise
  question, and cannot quietly shrink the baseline, because
  shrinking is a change to the list and the list is a promise.
- The promise names the enforcement mechanism by concept (a declared
  data boundary) with the configuration spelling as a citation, so
  [#493](https://github.com/rafacm/vinga/issues/493), which renames
  the spelling and adds a network tier, updates a citation rather
  than a promise.
- The telemetry content exports (the capture attachment of
  [#67](https://github.com/rafacm/vinga/issues/67), the transcript
  export of [#495](https://github.com/rafacm/vinga/issues/495)) are
  the first features held to rule 5, and the disclosure-ladder
  naming of the `server.telemetry` section is that rule made legible
  in configuration.
- Drift stays visible by construction: the local path cannot fall
  below the list without a falsifiable promise breaking, and the
  list cannot grow or shrink by implication because every change to
  it is a recorded decision this page's successor cites.
