### Added

- The LLM guide's section on the built-in agent's lookup
  (`docs/run/llm.md`) carries three more open-weight models through
  the same 32-question gate, measured on Ollama's cloud:
  `gemma4:31b` (62% and 56% correct, 2 and 3 invented claims),
  `gpt-oss:20b` (53% and 50%, 5 and 9) and `nemotron-3-nano:30b` (53%
  and 41%, 10 and 9), with the settings each was sent. For someone
  choosing a local model for bigger hardware, the correctness and
  invented-claim figures are the ones that carry over; the seconds are
  a hosted service's and do not. The gate harness reads an endpoint
  key from `VINGA_LOCAL_LLM_API_KEY` and its request options from
  `VINGA_LOCAL_LLM_PASSTHROUGH`, each only when set, and answers a call
  to a tool it did not offer in the runtime's own words rather than as
  if the tool had run.
