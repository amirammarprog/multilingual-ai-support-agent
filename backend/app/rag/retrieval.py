"""Hybrid, cross-lingual retrieval.

1. Every version of the query (the customer's language, plus EN/FR/AR translations from the planner)
   is searched with pgvector cosine similarity and PostgreSQL full-text search.
2. All ranked lists are fused with weighted reciprocal rank fusion.
3. Each candidate is reranked by a cross-encoder against the query version written in the chunk's own
   language (small multilingual rerankers are much better within one language than across two).
4. The top reranker score is the retrieval confidence. Below the threshold the agent says it does not
   know instead of guessing.
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import asdict, dataclass, field

from sqlalchemy import cast, func, literal, select
from sqlalchemy.dialects.postgresql import REGCONFIG
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.language import ts_config_for
from app.models import DocumentChunk, DocumentStatus, KnowledgeDocument
from app.rag.embeddings import get_embedder
from app.rag.reranker import get_reranker

RRF_K = 60
SAME_LANGUAGE_BONUS = 0.1
# Keyword hits help for SKUs, names and exact terms but are noisy for cross-lingual questions.
KEYWORD_WEIGHT = 0.6

# fmt: off
_STOPWORDS = {
    "en": {"the", "a", "an", "is", "are", "do", "does", "you", "i", "my", "me", "your", "can", "what", "how",
           "when", "where", "which", "of", "to", "in", "on", "for", "and", "or", "it", "this", "that", "with",
           "be", "have", "has", "if", "will", "would", "please", "there", "any", "about"},
    "fr": {"le", "la", "les", "un", "une", "des", "de", "du", "et", "ou", "est", "je", "tu", "vous", "mon", "ma",
           "mes", "votre", "vos", "pour", "avec", "en", "dans", "sur", "que", "qui", "quoi", "quel", "quelle",
           "est-ce", "ce", "il", "elle", "on", "pas", "ne", "se", "sont", "y", "a", "au", "aux", "si", "svp"},
    "ar": {"في", "من", "على", "إلى", "الى", "عن", "هل", "ما", "ماذا", "كيف", "متى", "أين", "اين", "هذا", "هذه",
           "أن", "ان", "و", "او", "أو", "لي", "انا", "أنا", "هو", "هي", "مع", "كم", "التي", "الذي", "لا"},
}
# fmt: on
_TERM = re.compile(r"\w+", re.UNICODE)


@dataclass
class RetrievedChunk:
    source_id: str
    chunk_id: str
    document_id: str
    title: str
    doc_type: str
    heading: str
    content: str
    language: str
    vector_rank: int | None
    keyword_rank: int | None
    fused_score: float
    rerank_score: float

    def as_source(self) -> dict[str, object]:
        snippet = self.content if len(self.content) <= 400 else self.content[:400].rsplit(" ", 1)[0] + " …"
        return {
            "id": self.source_id,
            "document_id": self.document_id,
            "title": self.title,
            "heading": self.heading,
            "snippet": snippet,
            "score": round(self.rerank_score, 3),
        }


@dataclass
class RetrievalResult:
    query: str
    queries: dict[str, str] = field(default_factory=dict)
    chunks: list[RetrievedChunk] = field(default_factory=list)
    candidates: int = 0
    confidence: float = 0.0
    threshold: float = 0.0
    latency_ms: int = 0

    @property
    def answerable(self) -> bool:
        return bool(self.chunks) and self.confidence >= self.threshold

    def as_dict(self) -> dict[str, object]:
        return {
            "query": self.query,
            "queries": self.queries,
            "candidates": self.candidates,
            "confidence": round(self.confidence, 3),
            "threshold": self.threshold,
            "latency_ms": self.latency_ms,
            "chunks": [asdict(c) for c in self.chunks],
        }


def keyword_query(text: str, language: str) -> str:
    """OR-query of meaningful terms. Only word characters reach to_tsquery, so its syntax cannot be
    broken (SQL injection is impossible anyway: the string is a bound parameter)."""
    stop = set().union(*_STOPWORDS.values())
    terms: list[str] = []
    for term in _TERM.findall(text.lower()):
        term = term.strip("_")
        if len(term) < 2 or term in stop or term in terms:
            continue
        terms.append(term)
    return " | ".join(terms[:16])


def _passage(entry: dict) -> str:
    chunk = entry["chunk"]
    return (
        f"{entry['title']} > {chunk.heading}\n{chunk.content}"
        if chunk.heading
        else f"{entry['title']}\n{chunk.content}"
    )


async def retrieve(
    session: AsyncSession,
    shop_id: uuid.UUID,
    query: str,
    language: str = "en",
    *,
    translations: dict[str, str] | None = None,
    settings: Settings | None = None,
    top_k: int | None = None,
) -> RetrievalResult:
    """Retrieve evidence for ``query`` written in ``language``; ``translations`` maps other languages
    ("en", "fr", "ar") to the same question."""
    settings = settings or get_settings()
    started = time.perf_counter()
    top_k = top_k or settings.retrieval_top_k
    language = language.split("-")[0]
    queries: dict[str, str] = {language: query.strip()[:1000]}
    for lang, text_ in (translations or {}).items():
        lang = lang.split("-")[0]
        if lang in _STOPWORDS and lang not in queries and text_ and text_.strip():
            queries[lang] = text_.strip()[:1000]
    queries = {k: v for k, v in queries.items() if v}
    result = RetrievalResult(query=query, queries=queries, threshold=settings.retrieval_min_score)
    if not queries:
        return result

    base = (
        select(DocumentChunk, KnowledgeDocument.title, KnowledgeDocument.doc_type)
        .join(
            KnowledgeDocument,
            (KnowledgeDocument.id == DocumentChunk.document_id) & (KnowledgeDocument.shop_id == DocumentChunk.shop_id),
        )
        .where(
            DocumentChunk.shop_id == shop_id,
            KnowledgeDocument.status == DocumentStatus.READY,
            DocumentChunk.quarantined.is_(False),
        )
    )

    ranked_lists: list[tuple[str, list]] = []
    vectors = await get_embedder().embed_documents(list(queries.values()))
    for (lang, text_), vector in zip(queries.items(), vectors, strict=True):
        rows = (
            await session.execute(
                base.order_by(DocumentChunk.embedding.cosine_distance(vector)).limit(settings.retrieval_candidates)
            )
        ).all()
        ranked_lists.append(("vector", rows))
        terms = keyword_query(text_, lang)
        if terms:
            tsquery = func.to_tsquery(cast(literal("simple"), REGCONFIG), terms).op("||")(
                func.to_tsquery(cast(literal(ts_config_for(lang)), REGCONFIG), terms)
            )
            rows = (
                await session.execute(
                    base.where(DocumentChunk.search_vector.op("@@")(tsquery))
                    .order_by(func.ts_rank_cd(DocumentChunk.search_vector, tsquery).desc())
                    .limit(settings.retrieval_candidates)
                )
            ).all()
            ranked_lists.append(("keyword", rows))

    fused: dict[uuid.UUID, dict] = {}
    for kind, rows in ranked_lists:
        for rank, (chunk, title, doc_type) in enumerate(rows, start=1):
            entry = fused.setdefault(
                chunk.id,
                {"chunk": chunk, "title": title, "doc_type": doc_type, "vector": None, "keyword": None, "score": 0.0},
            )
            entry[kind] = rank if entry[kind] is None else min(entry[kind], rank)
            entry["score"] += (1.0 if kind == "vector" else KEYWORD_WEIGHT) / (RRF_K + rank)

    budget = settings.retrieval_candidates + 2 * (len(queries) - 1)
    candidates = sorted(fused.values(), key=lambda e: e["score"], reverse=True)[:budget]
    result.candidates = len(candidates)
    if not candidates:
        result.latency_ms = int((time.perf_counter() - started) * 1000)
        return result

    # Score each candidate against the query version in its own language when one exists.
    groups: dict[str, list[int]] = {}
    for i, entry in enumerate(candidates):
        lang = entry["chunk"].language if entry["chunk"].language in queries else language
        groups.setdefault(lang, []).append(i)
    scores = [0.0] * len(candidates)
    reranker = get_reranker()
    for lang, indexes in groups.items():
        group_scores = await reranker.score(queries[lang], [_passage(candidates[i]) for i in indexes])
        for i, score in zip(indexes, group_scores, strict=True):
            scores[i] = float(score)

    # Among equally relevant passages, prefer the customer's language (better quotes and citations).
    ranked = sorted(
        zip(candidates, scores, strict=True),
        key=lambda p: p[1] + (SAME_LANGUAGE_BONUS if p[0]["chunk"].language == language else 0.0),
        reverse=True,
    )
    result.confidence = max(scores)
    keep = [p for p in ranked if p[1] >= settings.retrieval_min_score][:top_k] or ranked[:1]
    for index, (entry, score) in enumerate(keep, start=1):
        chunk: DocumentChunk = entry["chunk"]
        result.chunks.append(
            RetrievedChunk(
                source_id=f"S{index}",
                chunk_id=str(chunk.id),
                document_id=str(chunk.document_id),
                title=entry["title"],
                doc_type=entry["doc_type"],
                heading=chunk.heading,
                content=chunk.content,
                language=chunk.language,
                vector_rank=entry["vector"],
                keyword_rank=entry["keyword"],
                fused_score=round(entry["score"], 5),
                rerank_score=round(score, 4),
            )
        )
    result.latency_ms = int((time.perf_counter() - started) * 1000)
    return result
