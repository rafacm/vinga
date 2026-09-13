### Changed

- **The `openai` ASR type transcribes with `gpt-transcribe` by default**
  (#500, M3), where it used `gpt-4o-mini-transcribe`. A deployment that
  never set `model` therefore changes transcription model, which is
  worth knowing before the change rather than after: the new default is
  the one that reports which language it heard, so the `heard` event and
  the conversation record can carry a language they never carried on the
  old default. Only can, because the report is filled on a turn where
  the request named no single language: an entry with `language` set,
  which the shipped example fragment has, or a session whose language
  another engine locked, leaves the field empty exactly as before. An
  entry that wants the report leaves `language` unset. The model is also
  billed differently: OpenAI publishes it at $0.0045 per minute of
  audio, where the model it replaces is priced per audio token, so what
  a transcription costs is now readable from the milliseconds the `asr`
  span already reports. Set `model: gpt-4o-mini-transcribe` on the entry
  to keep exactly what you had.
- **An entry pointing `base_url` at a self-hosted or compatible endpoint
  should name its own `model`** (#500, M3), and should do it now if it
  never has. `gpt-transcribe` is an OpenAI model name, and an endpoint
  that serves other names will not have it. That failure does not arrive
  at startup: building a provider constructs a client and speaks to
  nothing, so the entry applies cleanly, boots cleanly, and fails on the
  first transcription of a real conversation. An entry that already
  names a model is unaffected, as is one pointing at OpenAI itself.
