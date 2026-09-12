### Added

- **Every exported span carries the session id under the grouping name
  a backend reads** (#67, M1). A trace exporter's session id is only
  useful to a backend that knows which attribute holds it, and
  `vinga.session.id` is not a name any of them reads: pointed at a
  self-hosted Langfuse, a three-turn conversation with a handover
  arrived as four unrelated traces whose session was empty. Every span
  now spells the same id under the conventions' generic `session.id` as
  well, which groups the session's turn traces where a backend supports
  it and is inert metadata where it does not. Nothing else changed: the
  `gen_ai` correspondence already renders as token counts on
  generations with no help, and the agent is deliberately never sent as
  a user, because a user is the person speaking and vinga does not know
  who that is. The live walkthrough that settled each of those, and the
  media-attachment answers read off the same instance, are recorded in
  `docs/plans/2026-09-12-langfuse-backend-implementation.md`.
