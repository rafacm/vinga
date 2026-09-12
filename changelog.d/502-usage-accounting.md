### Added

- **All three conversation stages now report what they cost**
  (#502, M3). A transcription span carries
  `gen_ai.usage.input_seconds`, the length of the utterance the ear was
  handed, and a synthesis span carries
  `gen_ai.usage.input_characters`, the length of the sentence the voice
  was handed, beside the token counts a generation already reported.
  Both are input, read from the model's side the way the OpenTelemetry
  GenAI conventions read the token halves, and both state their unit in
  the name because those conventions have a word only for tokens. The
  character count is a new declared field on `sentence_synthesized`,
  measured where the sentence already is and carried as a size, never a
  word of it; a stage that measured nothing reports no usage rather
  than a zero. Turning that usage into money is a backend model
  definition, which this server never writes: a new section of the
  server README gives the four models with a published list price, the
  unit and rate each one is entered as, the request that enters it, why
  four other models deliberately get none, and what a backend with no
  definitions shows, which is usage present and cost zero.
