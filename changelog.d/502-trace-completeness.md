### Added

- **An exported trace says four things it could not say before**
  (#502, M2). A board's name is on every span, so a trace can be
  grouped by the room a conversation happened in and not only by a
  MAC: the bounded copy `session_open` already carried, stamped from
  the session's retained identity onto the live spans and from the
  retained trace record onto the three written after the session
  closed, and absent rather than null for a board nobody has named.
  A tool call is a span of its own inside the turn that asked for it,
  carrying `gen_ai.operation.name` as the OpenTelemetry GenAI
  conventions spell it, which is what makes an MCP call visible at all
  on a backend that ingests no span events. The prompt's provenance by
  block rides every turn span the agent that assembled it speaks,
  flattened one attribute per block with the total beside them, sizes
  only and never a byte of the prompt; the first agent's, which is
  assembled before the session opens and used to reach no trace at
  all, is held and claimed by the open. And the spans that record what
  became of a recording's upload or a transcript export carry their
  facts under `vinga.` names instead of bare field names that belonged
  to nothing.
