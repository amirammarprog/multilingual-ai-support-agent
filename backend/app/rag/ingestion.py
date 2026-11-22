"""Document ingestion: validate -> store -> parse -> chunk -> injection scan -> embed -> index.

Uploads return immediately with status ``pending``; processing runs in the background and moves the
document to ``ready`` or ``failed`` (with a safe error message the admin UI shows).
"""

from __future__ import annotations

import hashlib
import uuid
from collections import Counter
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import tenant_session
from app.errors import AppError, Conflict, PayloadTooLarge
from app.language import ts_config_for
from app.logs import get_logger
from app.models import DocumentChunk, DocumentStatus, KnowledgeDocument
from app.rag.chunking import chunk_sections, estimate_tokens
from app.rag.embeddings import get_embedder
from app.rag.parsers import SUPPORTED_EXTENSIONS, detect_type, parse
from app.security.guardrails import scan_untrusted_document_text

log = get_logger("ingestion")

DOC_TYPES = {"product", "shipping", "returns", "warranty", "faq", "other"}


def default_title(filename: str) -> str:
    return filename.rsplit(".", 1)[0].replace("-", " ").replace("_", " ").strip().title()


def guess_doc_type(filename: str) -> str:
    name = filename.lower()
    for key, words in {
        "shipping": ("ship", "livraison", "delivery"),
        "returns": ("return", "retour", "refund", "rembours"),
        "warranty": ("warrant", "garantie"),
        "faq": ("faq",),
        "product": ("product", "catalog", "produit", "setup", "guide"),
    }.items():
        if any(w in name for w in words):
            return key
    return "other"


async def create_document(
    session: AsyncSession,
    shop_id: uuid.UUID,
    filename: str,
    data: bytes,
    *,
    title: str | None = None,
    doc_type: str | None = None,
    uploaded_by: uuid.UUID | None = None,
) -> KnowledgeDocument:
    settings = get_settings()
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise PayloadTooLarge(f"Files are limited to {settings.max_upload_mb} MB.")
    if not data:
        raise AppError("The file is empty.")
    safe_name = filename.replace("\\", "/").rsplit("/", 1)[-1][:255] or "document"
    ext = detect_type(safe_name, data)
    digest = hashlib.sha256(data).hexdigest()
    existing = await session.scalar(
        select(KnowledgeDocument.id).where(KnowledgeDocument.shop_id == shop_id, KnowledgeDocument.sha256 == digest)
    )
    if existing:
        raise Conflict("This document has already been uploaded.", details={"document_id": str(existing)})
    doc = KnowledgeDocument(
        shop_id=shop_id,
        title=(title or default_title(safe_name))[:255],
        filename=safe_name,
        content_type=SUPPORTED_EXTENSIONS[ext],
        doc_type=doc_type if doc_type in DOC_TYPES else guess_doc_type(safe_name),
        size_bytes=len(data),
        sha256=digest,
        status=DocumentStatus.PENDING,
        uploaded_by=uploaded_by,
        raw_content=data,
    )
    session.add(doc)
    await session.flush()
    return doc


async def process_document(shop_id: uuid.UUID, document_id: uuid.UUID) -> None:
    """Index one document. Safe to call again: existing chunks are replaced."""
    settings = get_settings()
    async with tenant_session(shop_id) as session:
        doc = await session.get(KnowledgeDocument, document_id, options=[])
        if doc is None:
            return
        doc.status = DocumentStatus.PROCESSING
        doc.error = None
        await session.commit()
        try:
            raw = (
                await session.execute(select(KnowledgeDocument.raw_content).where(KnowledgeDocument.id == document_id))
            ).scalar_one()
            sections = parse(doc.filename, raw or b"")
            chunks = chunk_sections(sections, settings.chunk_size, settings.chunk_overlap)
            if not chunks:
                raise AppError("The document contains no usable text.")
            vectors = await get_embedder().embed_documents([c.embedding_text(doc.title) for c in chunks])
            await session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
            quarantined = 0
            for chunk, vector in zip(chunks, vectors, strict=True):
                verdict = scan_untrusted_document_text(f"{chunk.heading}\n{chunk.content}")
                if verdict.action == "block":
                    quarantined += 1
                    log.warning(
                        "chunk_quarantined",
                        document_id=str(document_id),
                        index=chunk.index,
                        categories=verdict.categories,
                    )
                session.add(
                    DocumentChunk(
                        shop_id=shop_id,
                        document_id=document_id,
                        chunk_index=chunk.index,
                        heading=chunk.heading,
                        content=chunk.content,
                        language=chunk.language,
                        ts_config=ts_config_for(chunk.language),
                        token_count=estimate_tokens(chunk.content),
                        quarantined=verdict.action == "block",
                        embedding=vector,
                    )
                )
            doc.language = Counter(c.language for c in chunks).most_common(1)[0][0]
            # Titles derived from the file name are replaced by the document's own first heading.
            first_heading = next((s.heading.split(" > ")[0] for s in sections if s.heading), "")
            has_styled_headings = doc.filename.lower().endswith((".md", ".markdown", ".docx"))
            if has_styled_headings and first_heading and doc.title == default_title(doc.filename):
                doc.title = first_heading[:255]
            doc.chunk_count = len(chunks)
            doc.quarantined_chunks = quarantined
            doc.status = DocumentStatus.READY
            doc.processed_at = datetime.now(UTC)
            await session.commit()
            log.info("document_indexed", document_id=str(document_id), chunks=len(chunks), quarantined=quarantined)
        except Exception as exc:
            await session.rollback()
            message = exc.message if isinstance(exc, AppError) else "Processing failed. See server logs."
            if not isinstance(exc, AppError):
                log.exception("document_processing_failed", document_id=str(document_id))
            failed = await session.get(KnowledgeDocument, document_id)
            if failed is not None:
                failed.status = DocumentStatus.FAILED
                failed.error = message[:500]
                await session.commit()


async def resume_pending(shop_ids: list[uuid.UUID]) -> int:
    """Re-run documents left pending/processing by a restart."""
    count = 0
    for shop_id in shop_ids:
        async with tenant_session(shop_id) as session:
            ids = (
                await session.scalars(
                    select(KnowledgeDocument.id).where(
                        KnowledgeDocument.shop_id == shop_id,
                        KnowledgeDocument.status.in_([DocumentStatus.PENDING, DocumentStatus.PROCESSING]),
                    )
                )
            ).all()
        for doc_id in ids:
            await process_document(shop_id, doc_id)
            count += 1
    return count
