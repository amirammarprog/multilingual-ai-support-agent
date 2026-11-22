"""Rerankers score (query, passage) pairs jointly, which is far more precise than comparing two
independent embeddings. The default is mmarco-mMiniLMv2, a multilingual cross-encoder small enough for CPU
inference (about 2 s for 8 passages on a 4-core laptop CPU). Any fastembed cross-encoder, or any ONNX
cross-encoder on the Hugging Face Hub, can be configured instead (RERANKER_MODEL, RERANKER_MODEL_FILE)."""

from __future__ import annotations

import asyncio
import math
import threading
from functools import lru_cache
from typing import Protocol

from app.config import get_settings


class Reranker(Protocol):
    name: str

    async def score(self, query: str, passages: list[str]) -> list[float]:
        """Relevance probabilities in [0, 1], one per passage."""
        ...


class CrossEncoderReranker:
    def __init__(self, model_name: str, cache_dir: str, model_file: str | None = None) -> None:
        self.name = model_name
        self._cache_dir = cache_dir
        self._model_file = model_file
        self._model = None
        self._lock = threading.Lock()

    def _load(self):
        with self._lock:
            if self._model is None:
                from fastembed.common.model_description import ModelSource
                from fastembed.rerank.cross_encoder import TextCrossEncoder

                builtin = {m["model"] for m in TextCrossEncoder.list_supported_models()}
                if self.name not in builtin:
                    TextCrossEncoder.add_custom_model(
                        model=self.name,
                        sources=ModelSource(hf=self.name),
                        model_file=self._model_file or "onnx/model.onnx",
                    )
                self._model = TextCrossEncoder(self.name, cache_dir=self._cache_dir, threads=4)
        return self._model

    def _score(self, query: str, passages: list[str]) -> list[float]:
        logits = list(self._load().rerank(query, passages, batch_size=8))
        return [1 / (1 + math.exp(-float(x))) for x in logits]

    async def score(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        return await asyncio.to_thread(self._score, query, passages)

    def warm_up(self) -> None:
        self._score("warm up", ["warm up"])


class NoReranker:
    """Keeps the fused order and maps rank to a score. Only for very small deployments."""

    name = "none"

    async def score(self, query: str, passages: list[str]) -> list[float]:
        return [max(0.0, 0.9 - 0.1 * i) for i in range(len(passages))]


@lru_cache(maxsize=1)
def get_reranker() -> Reranker:
    settings = get_settings()
    if settings.reranker_provider == "none":
        return NoReranker()
    return CrossEncoderReranker(settings.reranker_model, settings.model_cache_dir, settings.reranker_model_file)
