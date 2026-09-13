### Added

- **The `openai` ASR type says which language it heard** (#500, M2). A
  transcription whose response reports a language fills
  `AsrResult.language`, so the code reaches the `heard` event, the
  conversation record, the `/api` read surface and the
  `vinga.asr.language` span attribute, every one of which has carried
  the field for the local engine all along. Which models report one is
  theirs to decide: `gpt-transcribe` answers a code whenever it makes
  out a language, the `gpt-4o` models answer none ever, and `whisper-1`
  answers only in a format this server does not ask for, so a
  deployment on the default model sees no change until the default
  moves. A clip a reporting model makes no language out of, which
  silence and laughter both were, comes back with an empty list and
  leaves the field absent for that turn. The field is filled only where the request named no language:
  told one, the model hands that code straight back rather than saying
  what it heard, so an entry with `language` set, or a session whose
  language another engine locked, leaves it empty as before and a
  configured value never arrives dressed as a measurement. Read what
  does arrive as a rate to watch rather than a verdict on one turn,
  since it says what the model decided rather than what was said. A
  reported code the `heard` event's own language type would refuse is
  declined by the provider instead, so a malformed answer from an
  endpoint costs one empty field rather than a turn that had already
  been transcribed.
