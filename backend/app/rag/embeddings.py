"""Embedding providers. The vector size is fixed by the schema (384), so both providers return 384
dimensions: the local multilingual model natively, OpenAI through the ``dimensions`` parameter."""

from __future__ import annotations

import asyncio
import threading
from functools import lru_cache
from typing import Protocol

import numpy as np

from app.config import get_settings


class Embedder(Protocol):
    name: str

    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


class LocalEmbedder:
    """Multilingual sentence embeddings with ONNX Runtime (fastembed), no API key and no GPU needed."""

    def __init__(self, model_name: str, cache_dir: str) -> None:
        self.name = model_name
        self._cache_dir = cache_dir
        self._model = None
        self._lock = threading.Lock()

    def _load(self):
        with self._lock:
            if self._model is None:
                from fastembed import TextEmbedding

                self._model = TextEmbedding(self.name, cache_dir=self._cache_dir, threads=2)
        return self._model

    def _embed(self, texts: list[str]) -> list[list[float]]:
        vectors = list(self._load().embed(texts, batch_size=16))
        return [np.asarray(v, dtype=np.float32).tolist() for v in vectors]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return await asyncio.to_thread(self._embed, texts)

    async def embed_query(self, text: str) -> list[float]:
        return (await asyncio.to_thread(self._embed, [text]))[0]

    def warm_up(self) -> None:
        self._embed(["warm up"])


class OpenAIEmbedder:
    def __init__(self, model_name: str, api_key: str, base_url: str, dim: int) -> None:
        from openai import AsyncOpenAI

        self.name = model_name
        self._dim = dim
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        response = await self._client.embeddings.create(model=self.name, input=texts, dimensions=self._dim)
        return [item.embedding for item in response.data]

    async def embed_query(self, text: str) -> list[float]:
        return (await self.embed_documents([text]))[0]


@lru_cache(maxsize=1)
def get_embedder() -> Embedder:
    settings = get_settings()
    if settings.embedding_provider == "openai":
        return OpenAIEmbedder(
            settings.openai_embedding_model,
            settings.llm_primary_api_key.get_secret_value(),
            settings.llm_primary_base_url,
            settings.embedding_dim,
        )
    return LocalEmbedder(settings.embedding_model, settings.model_cache_dir)
