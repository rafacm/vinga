### Added

- The LLM guide's section on the built-in agent's lookup
  (`docs/run/llm.md`) carries three more open-weight models through
  the same 32-question gate, measured on Ollama's cloud:
  `gemma4:31b` (62% and 56% correct, 4 and 6 invented claims),
  `gpt-oss:20b` (53% and 50%, 9 and 10) and `nemotron-3-nano:30b` (53%
  and 41%, 11 and 11), with the settings each was sent. These are
  hosted results that suggest which models are worth evaluating on
  bigger hardware of your own; answer quality on a local runner was
  not measured, and the seconds are the service's. The gate harness reads an endpoint
  key from `VINGA_LOCAL_LLM_API_KEY` and its request options from
  `VINGA_LOCAL_LLM_PASSTHROUGH`, each only when set, and answers a call
  to a tool it did not offer in the runtime's own words rather than as
  if the tool had run.
