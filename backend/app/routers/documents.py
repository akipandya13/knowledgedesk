"""Document management: upload, bulk ZIP ingest, list, reindex, delete."""
from __future__ import annotations

import hashlib
import io
import zipfile
from typing import Annotated

from fastapi import (APIRouter, BackgroundTasks, Depends, File, Form,
                     HTTPException, UploadFile)

from ..auth import get_db, get_tenant
from ..config import get_settings
from ..database import Document
from ..services import vectorstore
from ..services.ingestion import ingest_document
from ..services.parsers import SUPPORTED_EXTENSIONS

router = APIRouter(prefix="/api/documents", tags=["documents"])


def _split_tags(tags: str | None) -> list[str]:
    return [t.strip() for t in (tags or "").split(",") if t.strip()]


def _doc_out(d: Document) -> dict:
    return {
        "id": d.id, "filename": d.filename, "source": d.source,
        "status": d.status, "error": d.error, "pages": d.pages,
        "chunks": d.chunk_count, "size_bytes": d.size_bytes,
        "content_hash": d.content_hash, "department": d.department,
        "confidentiality": d.confidentiality, "tags": d.tags_json or [],
        "model_profile": d.model_profile,
        "embedding_provider": d.embedding_provider,
        "embedding_model": d.embedding_model,
        "version": d.version, "is_active": bool(d.is_active),
        "created_at": d.created_at.isoformat() if d.created_at else None,
    }


def _validate_file(name: str, data: bytes) -> str | None:
    s = get_settings()
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in SUPPORTED_EXTENSIONS:
        return f"Unsupported type .{ext}"
    if len(data) > s.max_upload_mb * 1024 * 1024:
        return f"Larger than {s.max_upload_mb} MB limit"
    return None


def _queue_document(db, background: BackgroundTasks, tenant, name: str, data: bytes,
                    source: str, department: str = "", confidentiality: str = "internal",
                    tags: list[str] | None = None) -> tuple[Document | None, str | None]:
    reason = _validate_file(name, data)
    if reason:
        return None, reason
    digest = hashlib.sha256(data).hexdigest()
    existing = (db.query(Document)
                .filter(Document.tenant_id == tenant.id,
                        Document.content_hash == digest,
                        Document.is_active == True)  # noqa: E712
                .first())
    if existing:
        return None, f"Duplicate of document #{existing.id} ({existing.filename})"
    doc = Document(tenant_id=tenant.id, filename=name, source=source,
                   status="queued", size_bytes=len(data), content_hash=digest,
                   department=department or "", confidentiality=confidentiality or "internal",
                   tags_json=tags or [])
    db.add(doc)
    db.commit()
    background.add_task(ingest_document, doc.id, tenant.slug, name, data)
    return doc, None


@router.post("/upload")
async def upload(background: BackgroundTasks,
                 files: Annotated[list[UploadFile], File()],
                 department: Annotated[str, Form()] = "",
                 confidentiality: Annotated[str, Form()] = "internal",
                 tags: Annotated[str, Form()] = "",
                 tenant=Depends(get_tenant), db=Depends(get_db)):
    """Upload one or more documents with optional enterprise metadata."""
    accepted, rejected = [], []
    for f in files:
        name = f.filename or "unnamed"
        data = await f.read()
        doc, reason = _queue_document(db, background, tenant, name, data, "upload",
                                      department, confidentiality, _split_tags(tags))
        if doc:
            accepted.append(_doc_out(doc))
        else:
            rejected.append({"filename": name, "reason": reason})
    return {"accepted": accepted, "rejected": rejected}


@router.post("/upload-zip")
async def upload_zip(background: BackgroundTasks,
                     archive: Annotated[UploadFile, File()],
                     department: Annotated[str, Form()] = "",
                     confidentiality: Annotated[str, Form()] = "internal",
                     tags: Annotated[str, Form()] = "",
                     tenant=Depends(get_tenant), db=Depends(get_db)):
    """Bulk-ingest a ZIP export from Drive/SharePoint/local folders."""
    data = await archive.read()
    accepted, rejected = [], []
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise HTTPException(400, "Invalid ZIP archive") from exc
    for info in zf.infolist():
        if info.is_dir() or info.filename.startswith("__MACOSX/"):
            continue
        name = info.filename.replace("\\", "/")
        payload = zf.read(info)
        doc, reason = _queue_document(db, background, tenant, name, payload, "zip",
                                      department, confidentiality, _split_tags(tags))
        if doc:
            accepted.append(_doc_out(doc))
        else:
            rejected.append({"filename": name, "reason": reason})
    return {"accepted": accepted, "rejected": rejected, "total_seen": len(accepted) + len(rejected)}


@router.get("")
def list_documents(status: str | None = None, source: str | None = None,
                   tenant=Depends(get_tenant), db=Depends(get_db)):
    q = db.query(Document).filter(Document.tenant_id == tenant.id,
                                  Document.is_active == True)  # noqa: E712
    if status:
        q = q.filter(Document.status == status)
    if source:
        q = q.filter(Document.source == source)
    docs = q.order_by(Document.created_at.desc()).all()
    return [_doc_out(d) for d in docs]


@router.post("/{doc_id}/reindex")
def reindex_document(doc_id: int):
    """Placeholder for connector-backed reindexing. Uploads are immutable in v1 demo."""
    raise HTTPException(501, "Reindex requires original connector/file source; re-upload the file for now")


@router.delete("/{doc_id}")
def delete_document(doc_id: int, tenant=Depends(get_tenant), db=Depends(get_db)):
    doc = (db.query(Document)
           .filter(Document.id == doc_id, Document.tenant_id == tenant.id).first())
    if not doc:
        raise HTTPException(404, "Document not found")
    vectorstore.delete_document(tenant.slug, doc.id)
    doc.is_active = False
    doc.status = "deleted"
    db.commit()
    return {"deleted": doc_id}
