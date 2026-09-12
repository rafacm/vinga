### Added

- **All three conversation stages now report what they cost**
  (#502, M3). A transcription span carries
  `gen_ai.usage.input_milliseconds`, how much audio the ear was
  actually sent, and a synthesis span carries
  `gen_ai.usage.input_characters`, the length of the sentence the voice
  was handed, beside the token counts a generation already reported.
  Both are input, read from the model's side the way the OpenTelemetry
  GenAI conventions read the token halves, and both state their unit in
  the name because those conventions have a word only for tokens. The
  transcription number is what was submitted rather than how long the
  user spoke, which is not the same thing on a real endpoint: a clip
  under the endpoint's minimum is never sent and reports zero, and a
  clip a prompt-echo retry hears twice reports twice its length. How
  long the user spoke stays where it was. The character count is a new
  declared field on `sentence_synthesized`, measured where the sentence
  already is and carried as a size, never a word of it; a stage that
  could not measure reports no usage rather than a zero. Each priced
  stage also carries its number in the backend's own usage spelling, so
  a model definition can put a price on it. Turning usage into money is
  a backend model definition, which this server never writes: a new
  section of the server README gives the four models with a published
  list price, the unit and rate each one is entered as, the request that
  enters it, why four other models deliberately get none, what a
  well-known vendor model needs (nothing, the backend already knows it),
  and what a backend with no definitions shows, which is usage present
  and cost zero.
