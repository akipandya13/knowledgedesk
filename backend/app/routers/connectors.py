"""Connector sync endpoints — mass ingestion from Google Drive / SharePoint."""
from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from ..auth import get_db, get_tenant
from ..database import Document, SessionLocal
from ..services.connectors import gdrive, sharepoint
from ..services.ingestion import ingest_document
from ..services.parsers import SUPPORTED_EXTENSIONS

log = logging.getLogger("knowledgedesk.connectors")
router = APIRouter(prefix="/api/connectors", tags=["connectors"])


@router.get("/status")
def status():
    return {
        "gdrive": {"configured": gdrive.is_configured()},
        "sharepoint": {"configured": sharepoint.is_configured()},
    }


def _sync_worker(connector, files: list[dict], doc_ids: list[int], tenant_slug: str):
    for file, doc_id in zip(files, doc_ids):
        try:
            name, data = connector.download_file(file)
            ingest_document(doc_id, tenant_slug, name, data)
        except Exception as e:  # noqa: BLE001
            log.exception("Connector download failed: %s", file.get("name"))
            db = SessionLocal()
            try:
                doc = db.get(Document, doc_id)
                if doc:
                    doc.status = "failed"
                    doc.error = f"Download failed: {e}"[:1000]
                    db.commit()
            finally:
                db.close()


def _start_sync(connector, source: str, background: BackgroundTasks, tenant, db):
    if not connector.is_configured():
        raise HTTPException(400, f"{source} is not configured — set its credentials in .env")
    try:
        files = connector.list_files()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Could not list {source} files: {e}")

    files = [f for f in files
             if f["name"].rsplit(".", 1)[-1].lower() in SUPPORTED_EXTENSIONS
             or f.get("mimeType", "").startswith("application/vnd.google-apps")]

    doc_ids = []
    for f in files:
        doc = Document(tenant_id=tenant.id, filename=f["name"], source=source,
                       status="queued", size_bytes=int(f.get("size") or 0))
        db.add(doc)
        db.commit()
        doc_ids.append(doc.id)

    background.add_task(_sync_worker, connector, files, doc_ids, tenant.slug)
    return {"queued": len(files), "source": source}


@router.post("/gdrive/sync")
def sync_gdrive(background: BackgroundTasks, tenant=Depends(get_tenant),
                db=Depends(get_db)):
    return _start_sync(gdrive, "gdrive", background, tenant, db)


@router.post("/sharepoint/sync")
def sync_sharepoint(background: BackgroundTasks, tenant=Depends(get_tenant),
                    db=Depends(get_db)):
    return _start_sync(sharepoint, "sharepoint", background, tenant, db)
