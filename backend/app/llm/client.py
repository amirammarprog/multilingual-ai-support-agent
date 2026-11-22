"""OpenAI-compatible LLM client with a provider fallback chain.

Providers are tried in order (primary, then fallback). Each attempt is recorded with tokens, cost and
latency, so the dashboard can show model usage and how often the fallback was needed. Outputs are
requested as strict JSON schema and validated with Pydantic; an invalid answer counts as a failure
and moves on to the next provider.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from typing import Any, Literal

import httpx
from openai import APIError, AsyncOpenAI
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

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class LLMUnavailable(Exception):
    def __init__(self, usages: list[LLMUsage]) -> None:
        super().__init__("no LLM provider produced a valid answer")
        self.usages = usages


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
            )
        )
    return providers


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
                max_retries=1,
                http_client=http_client,
            )
            for p in self.providers
        }

    @property
    def available(self) -> bool:
        return bool(self.providers)

    def describe(self) -> list[dict[str, str]]:
        return [
            {
                "provider": p.name,
                "base_url": p.base_url,
                "fast": p.model_for("fast"),
                "smart": p.model_for("smart"),
            }
            for p in self.providers
        ]

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
        response_format = {
            "type": "json_schema",
            "json_schema": {"name": schema.__name__, "schema": strict_schema(schema), "strict": True},
        }
        for index, provider in enumerate(self.providers):
            model = provider.model_for(tier)
            usage = LLMUsage(purpose, provider.name, model, tier, fallback_used=index > 0)
            started = time.perf_counter()
            kwargs: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "response_format": response_format,
                "temperature": self.settings.llm_temperature,
            }
            if provider.is_openai:
                kwargs["max_completion_tokens"] = max_tokens
            else:
                kwargs["max_tokens"] = max_tokens
                if self.settings.llm_disable_thinking:
                    kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
            with tracer.generation(
                name=purpose, model=model, input=messages, metadata={"provider": provider.name, "tier": tier}
            ) as gen:
                try:
                    response = await self._clients[provider.name].chat.completions.create(**kwargs)
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
                except (APIError, ValidationError, json.JSONDecodeError, TimeoutError, IndexError) as exc:
                    usage.success = False
                    usage.error = type(exc).__name__
                    usage.latency_ms = int((time.perf_counter() - started) * 1000)
                    usages.append(usage)
                    gen.update(level="ERROR", status_message=type(exc).__name__)
                    log.warning(
                        "llm_attempt_failed",
                        provider=provider.name,
                        model=model,
                        purpose=purpose,
                        error=type(exc).__name__,
                    )
        raise LLMUnavailable(usages)


_client: LLMClient | None = None


def get_llm() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client


def set_llm(client: LLMClient | None) -> None:
    """Swap the process-wide client (used by the eval runner to compare configurations)."""
    global _client
    _client = client
