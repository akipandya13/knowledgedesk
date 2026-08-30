"""Ingestion pipeline (runs as a FastAPI background task).

parse → chunk → embed → upsert to Qdrant → mark document ready.
Synchronous on purpose: embedding is CPU-bound and BackgroundTasks run it
off the request thread, which is plenty for v1 scale (a 1,000-employee
company's documents ingest in minutes, not hours).
"""
from __future__ import annotations

import hashlib
import logging
import time

from .. import observability as obs
from ..config import get_settings
from ..database import DOC_SCOPE_TENANT, SessionLocal, Document, Tenant
from ..tenant_settings import resolve_model_config
from . import embeddings, vectorstore
from .chunking import chunk_pages
from .parsers import SUPPORTED_EXTENSIONS, parse_file

log = logging.getLogger("knowledgedesk.ingest")


# ── Shared upload/queue helpers (used by both the documents router and
#    the connector sync worker so dedup + validation behave identically) ──

def validate_file(name: str, data: bytes) -> str | None:
    """Return a rejection reason, or None if the file is acceptable."""
    s = get_settings()
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in SUPPORTED_EXTENSIONS:
        return f"Unsupported type .{ext}"
    if len(data) > s.max_upload_mb * 1024 * 1024:
        return f"Larger than {s.max_upload_mb} MB limit"
    return None


def register_document(db, tenant, name: str, data: bytes, source: str,
                      department: str = "", confidentiality: str = "internal",
                      tags: list[str] | None = None, *,
                      scope: str = DOC_SCOPE_TENANT,
                      owner_user_id: int | None = None) -> tuple[Document | None, str | None]:
    """Create a queued Document row (no ingestion scheduled). Returns (doc, reason).

    Skips files that fail validation or duplicate an existing active document
    with the same content hash *in the same ownership scope* — so one user's
    private copy never collides with the company copy or with another user's.
    """
    reason = validate_file(name, data)
    if reason:
        return None, reason
    digest = hashlib.sha256(data).hexdigest()
    existing = (db.query(Document)
                .filter(Document.tenant_id == tenant.id,
                        Document.content_hash == digest,
                        Document.is_active == True,  # noqa: E712
                        Document.scope == scope,
                        Document.owner_user_id == owner_user_id)
                .first())
    if existing:
        return None, f"Duplicate of document #{existing.id} ({existing.filename})"
    doc = Document(tenant_id=tenant.id, filename=name, source=source,
                   status="queued", size_bytes=len(data), content_hash=digest,
                   department=department or "", confidentiality=confidentiality or "internal",
                   tags_json=tags or [], scope=scope, owner_user_id=owner_user_id)
    db.add(doc)
    db.commit()
    return doc, None


def queue_document(db, background, tenant, name: str, data: bytes, source: str,
                   department: str = "", confidentiality: str = "internal",
                   tags: list[str] | None = None, *,
                   scope: str = DOC_SCOPE_TENANT,
                   owner_user_id: int | None = None) -> tuple[Document | None, str | None]:
    """register_document + schedule ingestion on the FastAPI background queue."""
    doc, reason = register_document(db, tenant, name, data, source,
                                    department, confidentiality, tags,
                                    scope=scope, owner_user_id=owner_user_id)
    if doc:
        background.add_task(ingest_document, doc.id, tenant.slug, name, data)
    return doc, reason


def ingest_document(doc_id: int, tenant_slug: str, filename: str, data: bytes) -> None:
    db = SessionLocal()
    t0 = time.time()
    bind = obs.bound(tenant=tenant_slug)
    bind.__enter__()
    outcome = "ready"
    n_chunks = 0
    try:
        doc = db.get(Document, doc_id)
        if not doc:
            return
        doc.status = "processing"
        db.commit()

        with obs.span("ingest.parse"), obs.timer("ingest.stage.seconds", stage="parse"):
            pages = parse_file(filename, data)
        if not any(text.strip() for _, text in pages):
            raise ValueError("No extractable text found (scanned PDF without OCR?)")

        with obs.span("ingest.chunk"), obs.timer("ingest.stage.seconds", stage="chunk"):
            chunks = chunk_pages(pages)
        if not chunks:
            raise ValueError("Document produced no usable chunks")
        n_chunks = len(chunks)

        tenant = db.query(Tenant).filter(Tenant.slug == tenant_slug).first()
        model_cfg = resolve_model_config(tenant, db)
        embedding_provider = model_cfg.get("embedding_provider", "local")
        embedding_model = model_cfg.get("embedding_model")
        with obs.span("ingest.embed", chunks=n_chunks), obs.timer("ingest.stage.seconds", stage="embed"):
            vectors = embeddings.embed_texts(
                [c.text for c in chunks],
                provider=embedding_provider,
                model_name=embedding_model,
                runtime=model_cfg,
            )
        with obs.span("ingest.upsert"), obs.timer("ingest.stage.seconds", stage="upsert"):
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
                    "scope": doc.scope or DOC_SCOPE_TENANT,
                    "owner_user_id": doc.owner_user_id,
                },
            )

        doc.model_profile = model_cfg.get("model_profile", "")
        doc.embedding_provider = embedding_provider
        doc.embedding_model = embedding_model or ""
        doc.status = "ready"
        doc.pages = len(pages)
        doc.chunk_count = n_chunks

        # Snapshot the embedding identity this workspace is now locked to. The
        # lock itself is enforced by the presence of a ready document; this is
        # for display / diagnostics in the admin UI.
        if tenant is not None:
            snap = dict(tenant.settings_json or {})
            if not snap.get("embedding_locked_to"):
                snap["embedding_locked_to"] = {
                    "provider": embedding_provider,
                    "model": embedding_model or "",
                    "connector_id": snap.get("embedding_connector_id"),
                }
                tenant.settings_json = snap
                db.merge(tenant)
        db.commit()
        log.info("Ingested %s (%d chunks)", filename, n_chunks)
    except Exception as e:  # noqa: BLE001 — surface every failure on the document row
        outcome = "failed"
        log.exception("Ingestion failed for %s", filename)
        obs.event("document.ingest.failed", level="error", filename=filename, error=str(e)[:300])
        doc = db.get(Document, doc_id)
        if doc:
            doc.status = "failed"
            doc.error = str(e)[:1000]
            db.commit()
    finally:
        db.close()
        elapsed = time.time() - t0
        obs.count("ingest.documents", outcome=outcome, help="Documents ingested, by outcome")
        obs.observe("ingest.document.seconds", elapsed, outcome=outcome)
        if outcome == "ready":
            obs.observe("ingest.document.chunks", n_chunks)
            obs.event("document.ingested", filename=filename, chunks=n_chunks,
                      seconds=round(elapsed, 2))
        bind.__exit__(None, None, None)
