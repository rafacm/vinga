"""A real OpenAI SDK client for the speech providers' tests, over a
mock transport.

Not `llm_sdk`, which holds fake shapes for the two streamed LLM
dialects: this is the vendor's own `AsyncOpenAI`, unfaked, with only
its transport and its retry policy chosen by the test. The ASR and TTS
suites each need that client, and what makes it one helper rather than
two copies is that both choices have to agree: a suite that let the
SDK retry would count requests the provider never sent.
"""

import httpx
from openai import AsyncOpenAI


def mock_client(handler: object) -> AsyncOpenAI:
    """An SDK client that answers from the handler, so nothing leaves the
    test."""
    return AsyncOpenAI(
        api_key="test-key",
        # As the provider constructs its own: without this the SDK's
        # default of two retries would triple a deliberately failing
        # request, with its backoff, and hide how many the provider
        # itself sends.
        max_retries=0,
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
        ),
    )
