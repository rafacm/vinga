# Direction

**Date:** 2026-10-06

Decided direction that no issue or decision record owned when it was
written down, kept as a dated record. Each entry is one decision as it
was recorded: its words, where and when they were written, and the open
issue it waits on where one does. Nothing on this page describes what
runs. What runs today is on [the concepts page](../concepts.md) and the
pages the [Run and Use doors](../README.md) link, and direction an open
issue owns lives in that issue, not here.

Entries are never deleted or reworded. When an issue or a record takes
one, a dated line naming it is appended under the entry, the way a
later changelog entry relates to an earlier one, and the entry stays as
it was. The page belongs to the dated execution records in
[the authority taxonomy](../README.md#authority): it reports what was
decided and when, never what is true now.

The seven entries below came off `docs/concepts.md` and
`docs/glossary.md` on 2026-10-06, when
[#609](https://github.com/rafacm/vinga/issues/609) made those pages
describe only what runs. The quoted text is the page's own as it stood
at `3073d08b`, with its links reduced to their words. "Recorded" gives
the date the page itself put on the claim where it put one, and
otherwise the date of the commit that added the passage.

## Changing a device's default agent by voice

> Changing a device's default by voice ("make Nadia the default agent
> on this device") is **decided direction** and belongs to the meta
> capabilities below.

- **Recorded:** `docs/concepts.md`, Binding, added 2026-08-12, and
  filed under the Meta capabilities section, which the page marked
  "recorded on this page, 2026-08-21; no owning issue or decision
  record yet".
- **Waits on:** users, [#606](https://github.com/rafacm/vinga/issues/606).
  [#612](https://github.com/rafacm/vinga/issues/612), vinga as the
  built-in default agent, names configuration by voice as #606's, and
  #606's body does not take it up, so it has no owner.

## Meta turns belong to the session, not a thread

> And a turn that is only a meta request ("increase the volume to 9")
> is session work rather than dialogue with an agent, so it belongs to
> the session and to no thread; the honest edge is that a mixed turn
> ("set the volume to 9, and what were we saying?") belongs to the
> thread. That recording rule is **decided direction** (recorded on
> this page, 2026-08-21; no owning issue or decision record yet).

The glossary's Meta capability entry stated the same rule in the
present tense: "turns that are only meta requests (device control, a
cost question, the switch itself) are recorded as session events, not
conversation entries."

- **Recorded:** `docs/concepts.md`, Conversation and session,
  2026-08-21 by the page's own mark; the glossary's sentence carried no
  mark.
- **Waits on:** no open issue.

## Carrying context deliberately across a switch

> Carrying context deliberately (phrasing that asks for continuation,
> "ask Nadia about this", with the agent asking rather than guessing
> when the phrasing is ambiguous) is the part that remains **decided
> direction**.

The glossary's Handover entry: "Carrying context across deliberately,
on phrasing that asks for it, remains decided direction (issue #190)."

- **Recorded:** `docs/concepts.md`, Conversation and session, added
  2026-08-11 with no date of its own. The glossary attributed it to
  [#190](https://github.com/rafacm/vinga/issues/190), which built the
  clean-switch default this would refine and closed without it.
- **Waits on:** no open issue.

## Per-conversation cost, counted in tokens

> "How much has this conversation cost so far" wants cost to be a
> property of the thread. [...] What is still **decided direction** is
> the rest of the sentence (recorded on this page, 2026-08-21): issue
> #190 explicitly leaves budgets and per-conversation accounting out of
> its scope, and the cost direction is recorded there: usage is counted
> in tokens, and currency is at most an optional price map over it.
> [...] The accounting itself still awaits users.

The glossary's Meta capability entry: "the cost question is planned
rather than built."

- **Recorded:** `docs/concepts.md`, the Cost bullet of Conversation and
  session and the Meta capabilities section, 2026-08-21 by the page's
  own mark. The tokens-then-price-map shape was recorded in #190's
  scope, and #190 has closed. The usage the number would be read from
  exists ([#439](https://github.com/rafacm/vinga/issues/439),
  [#440](https://github.com/rafacm/vinga/issues/440)); the per-thread
  question and its currency do not.
- **Waits on:** no open issue; the text says it awaits users (#606).

## Cross-agent conversation search

> A cross-agent search may arrive later as a separate, explicitly
> user-level capability.

The same section added that "issue #190 left budgets, per-conversation
accounting and cross-agent threads out of its scope".

- **Recorded:** `docs/concepts.md`, Meta capabilities, added
  2026-08-11, under the section's mark of 2026-08-21.
- **Waits on:** users (#606), whose body does not take it up.

## Budget enforcement

> Users, and with them budgets and voiceprint identification for shared
> devices, come in a later stage: when they arrive, conversations,
> memory and the shared profile all gain a user in their key, and
> voiceprint recognition decides which user is speaking on a shared
> device. That is **decided direction** (recorded on this page,
> 2026-08-21; no owning issue or decision record yet, though the usage
> aggregation budgets will read landed with #439 and is served over the
> API and the command line by #440, whose rows are keyed by day and
> device and whose shape takes a user in the key without moving).

Users, the user-bearing keys and the shared profile are #606's, and
voiceprint identification is
[#608](https://github.com/rafacm/vinga/issues/608)'s research. Budget
enforcement is the part left: #606 lists it out of its scope.

- **Recorded:** `docs/concepts.md`, Before users arrive, 2026-08-21 by
  the page's own mark.
- **Waits on:** users (#606), which lists budget enforcement out of
  its scope.

## Users do not bring a session of their own

> Users do not bring a session of their own, and that is **decided
> direction** too (recorded on this page, 2026-09-23). Three things
> stay three: the **device session**, the connection episode this page
> calls a session, which stays on the device side of the model and is
> written with its qualifier wherever a login or a user could be read
> into the bare word; the **conversation**, owned by a user and an
> agent together once users exist, which is the unit a person finds,
> resumes, recaps and deletes; and **who is speaking**, which on a
> shared device can change inside one device session (a child, then a
> parent) and is therefore a property of a stretch of that session
> rather than a session in its own right. A "user session" would have
> to mean one of the last two, and naming either of them a session
> would reintroduce the confusion the conversation/session split exists
> to remove.

The glossary's Session entry: "vinga has no user session and will not
gain one when users arrive, since who is speaking is a property of a
stretch of a device session rather than a session of its own." The
writing convention, **device session** wherever the bare word could be
read as a user's or a login's, describes how the pages are written
today and stays on both pages.

- **Recorded:** `docs/concepts.md`, Before users arrive, 2026-09-23 by
  the page's own mark.
- **Waits on:** users (#606), whose body does not cover it.
