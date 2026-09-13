### Changed

- **The `openai` ASR type declares what it accepts** (#500, M1). Its six
  options (`model`, `base_url`, `language`, `prompt`, `temperature`,
  `timeout_s`) are a pydantic model like the three types converted
  before it, so the type is documented in the same four places:
  `vinga-server config schema provider asr openai`, a table per type in
  `docs/reference/domain-config.md`, the `AsrOpenaiOptions` component of
  the OpenAPI document, and the `provider set` help. An option the type
  does not have is refused when the entry is written rather than at the
  next build, and the default model has one home, the `model` field,
  instead of a constant in the provider beside it.
- **`openai` ASR entries are validated more strictly than they were,
  and one refusal stops naming what it refused** (#500, M1). What the
  type accepts is unchanged in kind, held by a table-driven parity test
  taken call by call off the reader it replaces: a bool is still not a
  number, `"30"` is still not a timeout, and every blank spelling the
  reader passed on (`model: ""`, `language: ""`, `language: null`,
  `prompt: ""`, `prompt: null`, `temperature: null`) is still accepted
  and still means what it meant. Two things change. A stored entry the
  model refuses is now refused on read as well as on write, so a row
  written before this declaration meets a deployment as a boot refusal
  naming the entry and the field; the rows that reach it are `model:
  null` and `base_url: null`, which never built either, but whose
  refusal used to arrive only when some agent's provider was
  constructed. The way out is the recovery procedure in
  `docs/reference/cli.md`: boot on an empty database and apply a kept
  export, or take the row out with ordinary database tooling. And an
  unknown option is no longer quoted back by name, which is what a type
  with a declared set of fields answers: a key this repository did not
  declare is a key an operator invented, and as good a place to paste a
  credential as a value. A `base_url` that is not a URL and a
  `temperature` outside OpenAI's range are unaffected, and their
  wording is unchanged: both are questions about the endpoint rather
  than about a value, so both still run at build, where that is
  decided.
