"""Provider fallback, cost accounting and output validation of the LLM client, exercised through the real
OpenAI SDK against an in-process HTTP transport (no network, no keys)."""

import json

import httpx
import pytest

from app.agent.prompts import Answer
from app.config import Settings
from app.llm.client import LLMClient, LLMUnavailable, Provider

ANSWER = {"answer": "Order BC-10421 is shipped.", "source_ids": ["T1"], "answered": True}


def completion(content: str, prompt_tokens: int = 100, completion_tokens: int = 20) -> dict:
    return {
        "id": "cmpl-1",
        "object": "chat.completion",
        "created": 0,
        "model": "m",
        "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def make_client(handler) -> tuple[LLMClient, list[dict]]:
    seen: list[dict] = []

    def record(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append({"host": request.url.host, "model": body["model"], "body": body})
        return handler(request, body)

    settings = Settings(model_prices={"cheap-model": (1.0, 2.0)}, llm_timeout_seconds=5)
    providers = [
        Provider("primary", "http://primary.test/v1", "k1", "cheap-model", "big-model"),
        Provider("fallback", "http://fallback.test/v1", "", "local-fast", "local-smart"),
    ]
    http = httpx.AsyncClient(transport=httpx.MockTransport(record))
    return LLMClient(settings=settings, providers=providers, http_client=http), seen


async def test_primary_answer_is_used_and_costed():
    client, seen = make_client(lambda req, body: httpx.Response(200, json=completion(json.dumps(ANSWER))))
    answer, usages = await client.structured(
        messages=[{"role": "user", "content": "x"}], schema=Answer, tier="fast", purpose="respond"
    )
    assert answer.answer == ANSWER["answer"]
    assert [u.provider for u in usages] == ["primary"]
    assert usages[0].cost_usd == pytest.approx((100 * 1.0 + 20 * 2.0) / 1_000_000)
    assert seen[0]["body"]["response_format"]["json_schema"]["strict"] is True


async def test_falls_back_when_primary_fails():
    def handler(req, body):
        if req.url.host == "primary.test":
            return httpx.Response(503, json={"error": {"message": "overloaded"}})
        return httpx.Response(200, json=completion(json.dumps(ANSWER)))

    client, seen = make_client(handler)
    _, usages = await client.structured(
        messages=[{"role": "user", "content": "x"}], schema=Answer, tier="smart", purpose="respond"
    )
    assert [(u.provider, u.success) for u in usages] == [("primary", False), ("fallback", True)]
    assert usages[1].fallback_used and usages[1].model == "local-smart"
    assert {s["host"] for s in seen} == {"primary.test", "fallback.test"}


async def test_invalid_json_counts_as_failure_and_think_blocks_are_ignored():
    def handler(req, body):
        if req.url.host == "primary.test":
            return httpx.Response(200, json=completion("Sure! Here is the answer: maybe 42"))
        return httpx.Response(200, json=completion("<think>hmm</think>```json\n" + json.dumps(ANSWER) + "\n```"))

    client, _ = make_client(handler)
    answer, usages = await client.structured(
        messages=[{"role": "user", "content": "x"}], schema=Answer, tier="fast", purpose="respond"
    )
    assert answer.answered and usages[0].error == "ValidationError"


async def test_raises_when_every_provider_fails():
    client, _ = make_client(lambda req, body: httpx.Response(500, json={"error": {"message": "down"}}))
    with pytest.raises(LLMUnavailable) as exc:
        await client.structured(
            messages=[{"role": "user", "content": "x"}], schema=Answer, tier="fast", purpose="respond"
        )
    assert len(exc.value.usages) == 2 and not any(u.success for u in exc.value.usages)
