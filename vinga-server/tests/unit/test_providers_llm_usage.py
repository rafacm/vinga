"""What each LLM dialect says a generation cost, read into one `Usage`.

The two APIs disagree about what their input count means. OpenAI's
`prompt_tokens` already includes the prefix it served from its prompt
cache, and reports that prefix separately as
`prompt_tokens_details.cached_tokens`; Anthropic's `input_tokens`
excludes both the tokens read from its cache and the tokens written to
it. `Usage` takes OpenAI's reading (#536): `prompt_tokens` is the whole
input the model read, and `cached_prompt_tokens` the part of it served
from cache, a subset and never a sibling. Every downstream reader,
the `llm_round` event, the span's price, the turn's stored totals,
relies on that subset, so the adapters are where a vendor's shape stops.

`None` for the cached count means the endpoint did not say, which is a
different fact from `0`, the endpoint saying nothing was cached.
"""

from typing import Any

import pytest

from tests.support.llm_sdk import (
    FakeBlock,
    FakeChoice,
    FakeChunk,
    FakeChunkUsage,
    FakeCompletions,
    FakeDelta,
    FakeMessage,
    FakeMessages,
    FakePromptDetails,
    FakeStream,
    FakeUsage,
)
from vinga_server.providers import Turn, Usage
from vinga_server.providers.anthropic_llm import AnthropicLlm
from vinga_server.providers.openai_llm import OpenAiCompatibleLlm


async def usage_of(llm: Any) -> Usage | None:
    """The one `Usage` a stream yielded, or None where it yielded none."""
    said = [
        event async for event in llm.stream("", [Turn("user", "hi")]) if isinstance(event, Usage)
    ]
    assert len(said) <= 1
    return said[0] if said else None


# --- the OpenAI-compatible dialect ------------------------------------


def compatible(usage: FakeChunkUsage | None) -> OpenAiCompatibleLlm:
    """An endpoint streaming one sentence, then the usage chunk (with no
    choices, as the API sends it) when there is one."""
    chunks = [FakeChunk([FakeChoice(FakeDelta(content="Said."))])]
    if usage is not None:
        chunks.append(FakeChunk([], usage=usage))
    completions = FakeCompletions(chunks)
    return OpenAiCompatibleLlm(
        base_url="http://localhost:11434/v1",
        model="qwen3:8b",
        max_tokens=64,
        api_key=None,
        client=type(  # type: ignore[arg-type]
            "Client", (), {"chat": type("Chat", (), {"completions": completions})()}
        )(),
    )


async def test_a_compatible_endpoint_reports_its_cached_prefix() -> None:
    llm = compatible(FakeChunkUsage(2000, 10, FakePromptDetails(cached_tokens=1536)))

    assert await usage_of(llm) == Usage(
        prompt_tokens=2000, completion_tokens=10, cached_prompt_tokens=1536
    )


async def test_nothing_cached_is_a_zero_rather_than_an_absence() -> None:
    llm = compatible(FakeChunkUsage(2000, 10, FakePromptDetails(cached_tokens=0)))

    usage = await usage_of(llm)
    assert usage is not None
    assert usage.cached_prompt_tokens == 0


@pytest.mark.parametrize(
    "details",
    [
        pytest.param(None, id="no-details"),
        pytest.param(FakePromptDetails(cached_tokens=None), id="details-without-a-count"),
        pytest.param(object(), id="details-without-the-attribute"),
    ],
)
async def test_a_count_the_endpoint_did_not_send_is_absent_rather_than_zero(
    details: Any,
) -> None:
    """Many compatible servers send no `prompt_tokens_details` at all,
    and some send one whose `cached_tokens` is null. Neither says that
    nothing was cached, so neither may read as `0`."""
    llm = compatible(FakeChunkUsage(2000, 10, details))

    assert await usage_of(llm) == Usage(prompt_tokens=2000, completion_tokens=10)


@pytest.mark.parametrize(
    ("prompt", "cached"),
    [
        pytest.param(1000, 1500, id="over-the-total"),
        pytest.param(2000, -1, id="negative"),
        pytest.param(2000, True, id="a-bool"),
        pytest.param(2000, 1500.0, id="not-an-integer"),
        pytest.param(2000, "1500", id="a-string"),
        pytest.param(None, 1500, id="no-total-to-be-a-subset-of"),
    ],
)
async def test_a_cached_count_that_is_not_a_subset_is_not_believed(
    prompt: Any, cached: Any
) -> None:
    """The subset is load-bearing: the tracing backend subtracts the
    cached count from the input count before pricing, so a count above
    the total it is part of would export a negative uncached input and a
    wrong price, and the event's `Count` would refuse a negative or a
    non-integer outright. A malformed value from a compatible server
    stops here, as an absence; the input count beside it is untouched."""
    llm = compatible(FakeChunkUsage(prompt, 10, FakePromptDetails(cached_tokens=cached)))

    usage = await usage_of(llm)
    assert usage is not None
    assert usage.cached_prompt_tokens is None
    assert usage.prompt_tokens == prompt


async def test_a_cached_count_equal_to_the_whole_prompt_is_a_subset() -> None:
    """The boundary of the guard: all of it cached is still part of it."""
    llm = compatible(FakeChunkUsage(1024, 10, FakePromptDetails(cached_tokens=1024)))

    usage = await usage_of(llm)
    assert usage is not None
    assert usage.cached_prompt_tokens == 1024


async def test_an_endpoint_that_sends_no_usage_yields_none_still() -> None:
    assert await usage_of(compatible(None)) is None


# --- the Anthropic dialect --------------------------------------------


def anthropic(usage: FakeUsage) -> AnthropicLlm:
    messages = FakeMessages(FakeStream(["Said."], FakeMessage([FakeBlock(type="text")], usage)))
    return AnthropicLlm(
        model="claude-sonnet-5",
        max_tokens=64,
        api_key="sk-test",
        client=type("Client", (), {"messages": messages})(),  # type: ignore[arg-type]
    )


async def test_anthropic_cache_counts_fold_into_the_input_it_read() -> None:
    """This API's `input_tokens` is only the input after the last cache
    breakpoint. The tokens read from the cache and the tokens written to
    it are input the model read too, so the normalized total is all
    three, and the read count is the cached share of that total."""
    llm = anthropic(
        FakeUsage(
            input_tokens=10,
            output_tokens=7,
            cache_read_input_tokens=1800,
            cache_creation_input_tokens=200,
        )
    )

    assert await usage_of(llm) == Usage(
        prompt_tokens=2010, completion_tokens=7, cached_prompt_tokens=1800
    )


async def test_anthropic_without_cache_counts_reports_its_input_unchanged() -> None:
    """What every request this adapter sends today reports, since it sets
    no cache breakpoint: the fold changes nothing and the cached count is
    absent, not zero."""
    llm = anthropic(FakeUsage(input_tokens=11, output_tokens=7))

    assert await usage_of(llm) == Usage(prompt_tokens=11, completion_tokens=7)


async def test_anthropic_reports_a_zero_cache_read_as_zero() -> None:
    llm = anthropic(
        FakeUsage(
            input_tokens=11,
            output_tokens=7,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        )
    )

    assert await usage_of(llm) == Usage(
        prompt_tokens=11, completion_tokens=7, cached_prompt_tokens=0
    )


@pytest.mark.parametrize("unbelievable", [-5, True, 12.0])
async def test_anthropic_neither_folds_nor_reports_a_count_that_is_not_one(
    unbelievable: Any,
) -> None:
    """The fold makes the read count a subset by construction, so the
    type is the one thing left to guard: a value that is not a count is
    added to nothing and reported as absent."""
    llm = anthropic(
        FakeUsage(
            input_tokens=11,
            output_tokens=7,
            cache_read_input_tokens=unbelievable,
            cache_creation_input_tokens=unbelievable,
        )
    )

    assert await usage_of(llm) == Usage(prompt_tokens=11, completion_tokens=7)
