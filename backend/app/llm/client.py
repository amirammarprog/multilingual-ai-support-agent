"""OpenAI-compatible LLM client with a provider fallback chain, built for free-tier APIs too.

- Providers are tried in order (primary, then fallback). Each attempt is recorded with tokens, cost and
  latency, so the dashboard shows model usage and how often the fallback was needed.
- Each provider can be throttled (requests per minute). Rate-limit (429), server and connection errors
  are retried with exponential backoff, honouring the server's Retry-After, up to a maximum wait: a
  daily quota that resets in hours fails fast instead of hanging.
- Outputs are requested as strict JSON schema and validated with Pydantic. Providers or models that do
  not support JSON schema are switched to JSON mode, with the schema in the prompt. An invalid answer
  counts as a failure and moves on to the next provider.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import asdict, dataclass
from typing import Any, Literal

import httpx
from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    AsyncOpenAI,
    BadRequestError,
    InternalServerError,
    RateLimitError,
)
from pydantic import BaseModel, ValidationError

from app.config import Settings, get_settings
from app.logs import get_logger
from app.observability import tracer

log = get_logger("llm")

Tier = Literal["fast", "smart"]


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str
    api_key: str
    fast_model: str
    smart_model: str
    requests_per_minute: int = 0  # 0 = no client-side limit

    def model_for(self, tier: Tier) -> str:
        return (self.smart_model if tier == "smart" else self.fast_model) or self.fast_model or self.smart_model

    @property
    def is_openai(self) -> bool:
        return "api.openai.com" in self.base_url


@dataclass
class LLMUsage:
    purpose: str
    provider: str
    model: str
    tier: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    success: bool = True
    fallback_used: bool = False
    error: str | None = None
    retries: int = 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class LLMUnavailable(Exception):
    def __init__(self, usages: list[LLMUsage]) -> None:
        super().__init__("no LLM provider produced a valid answer")
        self.usages = usages


class _GiveUp(Exception):
    """A retryable error whose required wait is longer than allowed (e.g. a daily quota)."""

    def __init__(self, cause: Exception, wait: float) -> None:
        super().__init__(f"{type(cause).__name__}, retry after {wait:.0f}s")
        self.cause, self.wait = cause, wait


def configured_providers(settings: Settings) -> list[Provider]:
    providers = []
    primary_key = settings.llm_primary_api_key.get_secret_value()
    if primary_key or settings._is_local(settings.llm_primary_base_url):
        providers.append(
            Provider(
                "primary",
                settings.llm_primary_base_url,
                primary_key,
                settings.llm_primary_fast_model,
                settings.llm_primary_smart_model,
                settings.llm_primary_requests_per_minute,
            )
        )
    if settings.llm_fallback_base_url:
        providers.append(
            Provider(
                "fallback",
                settings.llm_fallback_base_url,
                settings.llm_fallback_api_key.get_secret_value(),
                settings.llm_fallback_fast_model,
                settings.llm_fallback_smart_model,
                settings.llm_fallback_requests_per_minute,
            )
        )
    return providers


def judge_provider(settings: Settings) -> Provider | None:
    """A dedicated judge model for evaluations (JUDGE_MODEL), on its own provider or the primary one."""
    if not settings.judge_model:
        return None
    return Provider(
        "judge",
        settings.judge_base_url or settings.llm_primary_base_url,
        settings.judge_api_key.get_secret_value() or settings.llm_primary_api_key.get_secret_value(),
        settings.judge_model,
        settings.judge_model,
        settings.judge_requests_per_minute or settings.llm_primary_requests_per_minute,
    )


def estimate_cost(settings: Settings, model: str, prompt_tokens: int, completion_tokens: int) -> float:
    price = settings.model_prices.get(model)
    if not price:
        return 0.0
    return round((prompt_tokens * price[0] + completion_tokens * price[1]) / 1_000_000, 8)


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Pydantic JSON schema -> the subset accepted by OpenAI strict structured outputs."""
    schema = model.model_json_schema()

    def fix(node: Any) -> Any:
        if isinstance(node, dict):
            node = {k: fix(v) for k, v in node.items() if k not in {"title", "default", "examples"}}
            if node.get("type") == "object" or "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node.get("properties", {}))
            return node
        if isinstance(node, list):
            return [fix(v) for v in node]
        return node

    return fix(schema)


_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)


def _extract_json(text: str) -> str:
    text = _THINK.sub("", text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if start != -1 and end > start else text


_UNITS = {"h": 3600.0, "m": 60.0, "s": 1.0, "ms": 0.001}


def parse_duration(value: str) -> float | None:
    """'7', '7.5', '7.66s', '2m59.56s', '1h2m', '250ms' -> seconds."""
    value = value.strip()
    try:
        return float(value)
    except ValueError:
        parts = re.findall(r"(\d+(?:\.\d+)?)(ms|h|m|s)", value)
        return sum(float(amount) * _UNITS[unit] for amount, unit in parts) if parts else None


def retry_after_seconds(exc: Exception) -> float | None:
    """Wait time requested by the server: Retry-After, else the provider's rate-limit reset headers."""
    response = getattr(exc, "response", None)
    if response is None:
        return None
    for header in ("retry-after", "x-ratelimit-reset-requests", "x-ratelimit-reset-tokens"):
        value = response.headers.get(header)
        seconds = parse_duration(value) if value else None
        if seconds is not None:
            return seconds
    return None


class _Throttle:
    """Spaces requests to at most ``per_minute`` per provider (shared by concurrent callers)."""

    def __init__(self, per_minute: int) -> None:
        self.interval = 60.0 / per_minute if per_minute > 0 else 0.0
        self._next = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        if not self.interval:
            return
        async with self._lock:
            now = time.monotonic()
            if self._next > now:
                await asyncio.sleep(self._next - now)
            self._next = max(now, self._next) + self.interval


class LLMClient:
    def __init__(
        self,
        settings: Settings | None = None,
        providers: list[Provider] | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.providers = providers if providers is not None else configured_providers(self.settings)
        self._clients = {
            p.name: AsyncOpenAI(
                base_url=p.base_url,
                api_key=p.api_key or "not-needed",
                timeout=self.settings.llm_timeout_seconds,
                max_retries=0,  # retries are handled here, with rate-limit-aware backoff
                http_client=http_client,
            )
            for p in self.providers
        }
        self._throttles = {p.name: _Throttle(p.requests_per_minute) for p in self.providers}
        mode = self.settings.llm_response_format
        self._json_mode = {p.name: "json_object" if mode == "json_object" else "json_schema" for p in self.providers}

    @property
    def available(self) -> bool:
        return bool(self.providers)

    def describe(self) -> list[dict[str, str]]:
        return [
            {"provider": p.name, "base_url": p.base_url, "fast": p.model_for("fast"), "smart": p.model_for("smart")}
            for p in self.providers
        ]

    async def _send(self, provider: Provider, kwargs: dict[str, Any], usage: LLMUsage) -> Any:
        """One request with throttling and retries on rate limits, server and connection errors."""
        settings = self.settings
        for attempt in range(settings.llm_max_retries + 1):
            await self._throttles[provider.name].wait()
            try:
                return await self._clients[provider.name].chat.completions.create(**kwargs)
            except (RateLimitError, InternalServerError, APIConnectionError) as exc:
                if attempt == settings.llm_max_retries:
                    raise
                wait = retry_after_seconds(exc)
                if wait is None:
                    wait = min(settings.llm_retry_base_seconds * 2**attempt, 60.0)
                if wait > settings.llm_max_retry_wait_seconds:
                    raise _GiveUp(exc, wait) from exc
                usage.retries += 1
                log.info(
                    "llm_retry",
                    provider=provider.name,
                    error=type(exc).__name__,
                    wait_s=round(wait, 1),
                    attempt=attempt + 1,
                )
                await asyncio.sleep(wait)
        raise AssertionError("unreachable")

    def _request(
        self, provider: Provider, messages: list[dict[str, str]], schema: type[BaseModel], tier: Tier, max_tokens: int
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"model": provider.model_for(tier), "temperature": self.settings.llm_temperature}
        if self._json_mode[provider.name] == "json_schema":
            kwargs["messages"] = messages
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": schema.__name__, "schema": strict_schema(schema), "strict": True},
            }
        else:
            hint = "\n\nReply with one JSON object only, matching this JSON schema:\n" + json.dumps(
                strict_schema(schema), ensure_ascii=False
            )
            kwargs["messages"] = [{**messages[0], "content": messages[0]["content"] + hint}, *messages[1:]]
            kwargs["response_format"] = {"type": "json_object"}
        if provider.is_openai:
            kwargs["max_completion_tokens"] = max_tokens
        else:
            kwargs["max_tokens"] = max_tokens
            if self.settings.llm_disable_thinking:
                kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
        if self.settings.llm_reasoning_effort:
            kwargs["reasoning_effort"] = self.settings.llm_reasoning_effort
        return kwargs

    async def structured[T: BaseModel](
        self,
        *,
        messages: list[dict[str, str]],
        schema: type[T],
        tier: Tier,
        purpose: str,
        max_tokens: int = 400,
    ) -> tuple[T, list[LLMUsage]]:
        usages: list[LLMUsage] = []
        for index, provider in enumerate(self.providers):
            model = provider.model_for(tier)
            usage = LLMUsage(purpose, provider.name, model, tier, fallback_used=index > 0)
            started = time.perf_counter()
            with tracer.generation(
                name=purpose, model=model, input=messages, metadata={"provider": provider.name, "tier": tier}
            ) as gen:
                try:
                    try:
                        response = await self._send(
                            provider, self._request(provider, messages, schema, tier, max_tokens), usage
                        )
                    except BadRequestError as exc:
                        # Some models reject strict JSON schema: switch this provider to JSON mode once.
                        unsupported = re.search(r"response_format|json_schema|structured", str(exc), re.I)
                        if not (
                            unsupported
                            and self.settings.llm_response_format == "auto"
                            and self._json_mode[provider.name] == "json_schema"
                        ):
                            raise
                        self._json_mode[provider.name] = "json_object"
                        log.info("llm_json_mode_fallback", provider=provider.name, model=model)
                        response = await self._send(
                            provider, self._request(provider, messages, schema, tier, max_tokens), usage
                        )
                    content = response.choices[0].message.content or ""
                    if response.usage:
                        usage.prompt_tokens = response.usage.prompt_tokens or 0
                        usage.completion_tokens = response.usage.completion_tokens or 0
                    usage.cost_usd = estimate_cost(self.settings, model, usage.prompt_tokens, usage.completion_tokens)
                    parsed = schema.model_validate_json(_extract_json(content))
                    usage.latency_ms = int((time.perf_counter() - started) * 1000)
                    usages.append(usage)
                    gen.update(
                        output=parsed.model_dump(),
                        usage_details={"input": usage.prompt_tokens, "output": usage.completion_tokens},
                        cost_details={"total": usage.cost_usd},
                    )
                    return parsed, usages
                except (
                    APIError,
                    APIStatusError,
                    _GiveUp,
                    ValidationError,
                    json.JSONDecodeError,
                    TimeoutError,
                    IndexError,
                ) as exc:
                    usage.success = False
                    usage.error = str(exc)[:200] if isinstance(exc, _GiveUp) else type(exc).__name__
                    usage.latency_ms = int((time.perf_counter() - started) * 1000)
                    usages.append(usage)
                    gen.update(level="ERROR", status_message=usage.error)
                    log.warning(
                        "llm_attempt_failed",
                        provider=provider.name,
                        model=model,
                        purpose=purpose,
                        error=usage.error,
                        retries=usage.retries,
                    )
        raise LLMUnavailable(usages)

    async def list_models(self) -> dict[str, list[str]]:
        """Model ids each provider offers (helps pick names for a free tier)."""
        out: dict[str, list[str]] = {}
        for provider in self.providers:
            try:
                page = await self._clients[provider.name].models.list()
                out[provider.name] = sorted(m.id for m in page.data)
            except APIError as exc:
                out[provider.name] = [f"error: {type(exc).__name__}"]
        return out


_client: LLMClient | None = None
_judge: LLMClient | None = None


def get_llm() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client


def get_judge_llm() -> LLMClient:
    """The evaluation judge: JUDGE_MODEL if configured, otherwise the agent's own providers."""
    global _judge
    if _judge is None:
        settings = get_settings()
        provider = judge_provider(settings)
        _judge = LLMClient(settings, providers=[provider]) if provider else get_llm()
    return _judge


def set_llm(client: LLMClient | None) -> None:
    """Swap the process-wide client (used by tests and the eval runner to compare configurations)."""
    global _client, _judge
    _client, _judge = client, None
