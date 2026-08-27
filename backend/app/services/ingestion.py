"""Ingestion pipeline (runs as a FastAPI background task).

parse → chunk → embed → upsert to Qdrant → mark document ready.
Synchronous on purpose: embedding is CPU-bound and BackgroundTasks run it
off the request thread, which is plenty for v1 scale (a 1,000-employee
company's documents ingest in minutes, not hours).
"""
from __future__ import annotations

import logging

from ..database import SessionLocal, Document, Tenant
from ..tenant_settings import effective_settings
from . import embeddings, vectorstore
from .chunking import chunk_pages
from .parsers import parse_file

log = logging.getLogger("knowledgedesk.ingest")


def ingest_document(doc_id: int, tenant_slug: str, filename: str, data: bytes) -> None:
    db = SessionLocal()
    try:
        doc = db.get(Document, doc_id)
        if not doc:
            return
        doc.status = "processing"
        db.commit()

        pages = parse_file(filename, data)
        if not any(text.strip() for _, text in pages):
            raise ValueError("No extractable text found (scanned PDF without OCR?)")

        chunks = chunk_pages(pages)
        if not chunks:
            raise ValueError("Document produced no usable chunks")

        tenant = db.query(Tenant).filter(Tenant.slug == tenant_slug).first()
        model_cfg = effective_settings(tenant)
        embedding_provider = model_cfg.get("embedding_provider", "local")
        embedding_model = model_cfg.get("embedding_model")
        vectors = embeddings.embed_texts(
            [c.text for c in chunks],
            provider=embedding_provider,
            model_name=embedding_model,
        )
        vectorstore.upsert_chunks(
            tenant_slug, doc_id, filename, chunks, vectors,
            metadata={
                "source": doc.source,
                "department": doc.department,
                "confidentiality": doc.confidentiality,
                "tags": doc.tags_json or [],
                "model_profile": model_cfg.get("model_profile", ""),
                "embedding_provider": embedding_provider,
                "embedding_model": embedding_model,
            },
        )

        doc.model_profile = model_cfg.get("model_profile", "")
        doc.embedding_provider = embedding_provider
        doc.embedding_model = embedding_model or ""
        doc.status = "ready"
        doc.pages = len(pages)
        doc.chunk_count = len(chunks)
        db.commit()
        log.info("Ingested %s (%d chunks)", filename, len(chunks))
    except Exception as e:  # noqa: BLE001 — surface every failure on the document row
        log.exception("Ingestion failed for %s", filename)
        doc = db.get(Document, doc_id)
        if doc:
            doc.status = "failed"
            doc.error = str(e)[:1000]
            db.commit()
    finally:
        db.close()
