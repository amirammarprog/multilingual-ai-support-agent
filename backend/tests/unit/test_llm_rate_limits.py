"""Free-tier behaviour of the LLM client: rate-limit retries, give-up on daily quotas, request pacing and
the JSON-mode fallback. Exercised through the real OpenAI SDK against an in-process transport."""

import itertools
import json
import time

import httpx
import pytest

from app.agent.prompts import Answer
from app.config import Settings
from app.llm.client import LLMClient, LLMUnavailable, Provider, parse_duration
from tests.unit.test_llm_client import ANSWER, completion

MESSAGES = [{"role": "system", "content": "You answer."}, {"role": "user", "content": "x"}]


def client(handler, *, rpm: int = 0, fallback: bool = False, **overrides) -> tuple[LLMClient, list[dict]]:
    seen: list[dict] = []

    def record(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append({"host": request.url.host, "body": body, "at": time.monotonic()})
        return handler(request, body, len(seen))

    settings = Settings(llm_timeout_seconds=5, llm_retry_base_seconds=0.01, **overrides)
    providers = [Provider("primary", "http://free.test/v1", "k", "small", "big", requests_per_minute=rpm)]
    if fallback:
        providers.append(Provider("fallback", "http://other.test/v1", "k", "small", "big"))
    return LLMClient(
        settings=settings, providers=providers, http_client=httpx.AsyncClient(transport=httpx.MockTransport(record))
    ), seen


def ok(_request=None, _body=None, _n=None) -> httpx.Response:
    return httpx.Response(200, json=completion(json.dumps(ANSWER)))


def rate_limited(retry_after: str) -> httpx.Response:
    return httpx.Response(
        429,
        headers={"retry-after": retry_after},
        json={"error": {"message": "Rate limit reached", "type": "rate_limit"}},
    )


@pytest.mark.parametrize(
    ("value", "seconds"),
    [("7", 7.0), ("0.5", 0.5), ("7.66s", 7.66), ("2m59.5s", 179.5), ("1h2m", 3720.0), ("250ms", 0.25), ("soon", None)],
)
def test_parse_duration(value, seconds):
    assert parse_duration(value) == seconds


async def test_rate_limit_is_retried_after_the_requested_wait():
    llm, seen = client(lambda req, body, n: rate_limited("0.2") if n <= 2 else ok())
    started = time.monotonic()
    answer, usages = await llm.structured(messages=MESSAGES, schema=Answer, tier="fast", purpose="respond")
    assert answer.answered and len(seen) == 3
    assert usages[0].retries == 2 and usages[0].success
    assert time.monotonic() - started >= 0.4  # waited as the server asked


async def test_daily_quota_gives_up_quickly_and_uses_the_fallback():
    def handler(req, body, n):
        return rate_limited("3600") if req.url.host == "free.test" else ok()

    llm, _ = client(handler, fallback=True)
    started = time.monotonic()
    _, usages = await llm.structured(messages=MESSAGES, schema=Answer, tier="fast", purpose="respond")
    assert time.monotonic() - started < 5  # did not sleep for an hour
    assert [(u.provider, u.success) for u in usages] == [("primary", False), ("fallback", True)]
    assert "retry after 3600s" in usages[0].error


async def test_server_errors_are_retried_then_reported():
    llm, seen = client(lambda req, body, n: httpx.Response(503, json={"error": {"message": "busy"}}), llm_max_retries=2)
    with pytest.raises(LLMUnavailable) as exc:
        await llm.structured(messages=MESSAGES, schema=Answer, tier="fast", purpose="respond")
    assert len(seen) == 3 and exc.value.usages[0].retries == 2


async def test_requests_are_paced_to_the_configured_rate():
    llm, seen = client(ok, rpm=300)  # one request every 0.2 s
    for _ in range(3):
        await llm.structured(messages=MESSAGES, schema=Answer, tier="fast", purpose="respond")
    gaps = [b["at"] - a["at"] for a, b in itertools.pairwise(seen)]
    assert all(gap >= 0.18 for gap in gaps), gaps


async def test_models_without_json_schema_switch_to_json_mode():
    def handler(req, body, n):
        if body["response_format"]["type"] == "json_schema":
            return httpx.Response(400, json={"error": {"message": "response_format json_schema is not supported"}})
        return ok()

    llm, seen = client(handler)
    answer, _ = await llm.structured(messages=MESSAGES, schema=Answer, tier="smart", purpose="respond")
    assert answer.answered
    retried = seen[1]["body"]
    assert retried["response_format"] == {"type": "json_object"}
    assert '"source_ids"' in retried["messages"][0]["content"]  # schema moved into the prompt
    # Later calls go straight to JSON mode.
    await llm.structured(messages=MESSAGES, schema=Answer, tier="smart", purpose="respond")
    assert seen[-1]["body"]["response_format"] == {"type": "json_object"} and len(seen) == 3


async def test_reasoning_effort_is_sent_only_when_configured():
    llm, seen = client(ok, llm_reasoning_effort="low")
    await llm.structured(messages=MESSAGES, schema=Answer, tier="fast", purpose="respond")
    assert seen[0]["body"]["reasoning_effort"] == "low"
    plain, seen_plain = client(ok)
    await plain.structured(messages=MESSAGES, schema=Answer, tier="fast", purpose="respond")
    assert "reasoning_effort" not in seen_plain[0]["body"]


def invalid_generation() -> httpx.Response:
    # Groq's reply when a reasoning model runs out of tokens before writing the JSON answer.
    return httpx.Response(
        400,
        json={
            "error": {
                "message": "Generated JSON does not match the expected schema. Please adjust your prompt.",
                "type": "invalid_request_error",
                "code": "json_validate_failed",
                "failed_generation": "",
            }
        },
    )


async def test_rejected_generation_is_retried_once_on_the_capable_model_with_a_larger_budget():
    llm, seen = client(lambda req, body, n: invalid_generation() if n == 1 else ok())
    answer, usages = await llm.structured(messages=MESSAGES, schema=Answer, tier="fast", purpose="respond")
    assert answer.answered and len(seen) == 2
    assert [s["body"]["model"] for s in seen] == ["small", "big"]
    assert seen[1]["body"]["max_tokens"] > seen[0]["body"]["max_tokens"]
    assert seen[1]["body"]["response_format"]["type"] == "json_schema"  # not mistaken for "schema unsupported"
    assert (usages[0].model, usages[0].tier, usages[0].retries, usages[0].success) == ("big", "smart", 1, True)


async def test_rejected_generation_on_the_capable_model_is_retried_on_the_same_model():
    llm, seen = client(lambda req, body, n: invalid_generation() if n == 1 else ok())
    await llm.structured(messages=MESSAGES, schema=Answer, tier="smart", purpose="respond")
    assert [s["body"]["model"] for s in seen] == ["big", "big"]


async def test_a_second_rejected_generation_moves_on_to_the_fallback():
    def handler(req, body, n):
        return invalid_generation() if req.url.host == "free.test" else ok()

    llm, seen = client(handler, fallback=True)
    _, usages = await llm.structured(messages=MESSAGES, schema=Answer, tier="fast", purpose="respond")
    assert [s["host"] for s in seen] == ["free.test", "free.test", "other.test"]  # no retry loop
    assert [(u.provider, u.success) for u in usages] == [("primary", False), ("fallback", True)]


async def test_extra_output_tokens_are_added_to_every_call():
    plain, seen_plain = client(ok)
    await plain.structured(messages=MESSAGES, schema=Answer, tier="fast", purpose="respond")
    llm, seen = client(ok, llm_extra_output_tokens=1024)
    await llm.structured(messages=MESSAGES, schema=Answer, tier="fast", purpose="respond")
    assert seen[0]["body"]["max_tokens"] == seen_plain[0]["body"]["max_tokens"] + 1024
