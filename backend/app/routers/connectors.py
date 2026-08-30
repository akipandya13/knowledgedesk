"""Per-workspace data connectors — configure, test and sync external
document sources (Google Drive, SharePoint).

Credentials are encrypted at rest (app.crypto) and never returned by the API.
Everything a connector pulls goes through the same ingestion + dedup pipeline
as a manual upload.
"""
from __future__ import annotations

import datetime as dt
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from .. import observability as obs
from ..auth import get_db, require
from ..crypto import decrypt_secrets, encrypt_secrets
from ..database import ConnectorSyncRun, DataConnector, SessionLocal, Tenant, utcnow
from ..model_catalog import DATA_CONNECTOR_PROVIDERS
from ..rbac import Permission
from ..services import audit
from ..services.connectors import PROVIDERS
from ..services.connectors.base import ConnectorConfigError
from ..services.ingestion import ingest_document, register_document, validate_file

log = logging.getLogger("knowledgedesk.connectors")
router = APIRouter(prefix="/api/connectors", tags=["connectors"])

STALE_RUN_MINUTES = 30


def _tenant_or_400(principal) -> Tenant:
    if not principal.tenant:
        raise HTTPException(400, "Tenant context required")
    return principal.tenant


def _get_owned(db, principal, cid: int) -> DataConnector:
    conn = db.get(DataConnector, cid)
    tenant = _tenant_or_400(principal)
    if not conn or conn.tenant_id != tenant.id:
        raise HTTPException(404, "Connector not found")
    return conn


def _public(c: DataConnector) -> dict:
    sec = decrypt_secrets(c.secret_encrypted)
    return {
        "id": c.id, "name": c.name, "provider": c.provider,
        "config": c.config_json or {},
        "is_active": bool(c.is_active),
        "secret_fields_set": sorted(k for k, v in sec.items() if v),
        "last_sync_at": c.last_sync_at.isoformat() if c.last_sync_at else None,
        "last_sync_status": c.last_sync_status or "",
        "last_sync_detail": c.last_sync_detail or "",
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


def _run_public(r: ConnectorSyncRun) -> dict:
    return {
        "id": r.id, "connector_id": r.connector_id, "status": r.status,
        "queued": r.queued, "skipped": r.skipped, "failed": r.failed,
        "detail": r.detail or "",
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
    }


def _validate_fields(provider: str, config: dict, secrets_present: set[str]) -> None:
    spec = DATA_CONNECTOR_PROVIDERS.get(provider)
    if not spec:
        raise HTTPException(400, f"Unknown provider '{provider}'. Allowed: {sorted(DATA_CONNECTOR_PROVIDERS)}")
    for f in spec["config_fields"]:
        if f["required"] and not (config or {}).get(f["key"]):
            raise HTTPException(400, f"Missing required field: {f['label']}")
    for f in spec["secret_fields"]:
        if f["required"] and f["key"] not in secrets_present:
            raise HTTPException(400, f"Missing required secret: {f['label']}")


# ── Models ─────────────────────────────────────────────────────────

class ConnectorCreate(BaseModel):
    name: str
    provider: str
    config: dict = {}
    secrets: dict = {}


class ConnectorUpdate(BaseModel):
    name: str | None = None
    config: dict | None = None
    secrets: dict | None = None       # only provided keys change; "" clears one
    is_active: bool | None = None


# ── Provider catalog + legacy status ─────────────────────────────

@router.get("/providers")
def connector_providers(principal=Depends(require(Permission.DATA_CONNECTOR_MANAGE))):
    return DATA_CONNECTOR_PROVIDERS


@router.get("/status")
def status(principal=Depends(require(Permission.DATA_CONNECTOR_MANAGE))):
    """Legacy .env global connectors (deprecated — use per-workspace below)."""
    from ..services.connectors import gdrive, sharepoint
    return {
        "gdrive": {"configured": gdrive.is_configured()},
        "sharepoint": {"configured": sharepoint.is_configured()},
        "note": "Legacy .env connectors. Configure per-workspace connectors instead.",
    }


# ── CRUD ──────────────────────────────────────────────────────────

@router.get("")
def list_connectors(principal=Depends(require(Permission.DATA_CONNECTOR_MANAGE)), db=Depends(get_db)):
    tenant = _tenant_or_400(principal)
    rows = (db.query(DataConnector)
            .filter(DataConnector.tenant_id == tenant.id)
            .order_by(DataConnector.provider, DataConnector.name).all())
    return [_public(c) for c in rows]


@router.post("")
def create_connector(req: ConnectorCreate, principal=Depends(require(Permission.DATA_CONNECTOR_MANAGE)),
                     db=Depends(get_db)):
    tenant = _tenant_or_400(principal)
    clean_secrets = {k: v for k, v in (req.secrets or {}).items() if v}
    _validate_fields(req.provider, req.config or {}, set(clean_secrets))
    conn = DataConnector(
        tenant_id=tenant.id, name=req.name.strip() or req.provider,
        provider=req.provider, config_json=req.config or {},
        secret_encrypted=encrypt_secrets(clean_secrets),
    )
    db.add(conn)
    db.commit()
    audit.record(db, action="tenant.data_connector_created", actor_email=principal.email,
                 actor_role=principal.role, tenant_id=tenant.id,
                 detail=f"{req.provider} (#{conn.id})")
    return _public(conn)


@router.put("/{cid}")
def update_connector(cid: int, req: ConnectorUpdate, principal=Depends(require(Permission.DATA_CONNECTOR_MANAGE)),
                     db=Depends(get_db)):
    conn = _get_owned(db, principal, cid)

    if req.name is not None:
        conn.name = req.name.strip() or conn.name
    if req.config is not None:
        conn.config_json = req.config or {}
    if req.is_active is not None:
        conn.is_active = req.is_active
    if req.secrets is not None:
        current = decrypt_secrets(conn.secret_encrypted)
        for k, v in req.secrets.items():
            if v == "":
                current.pop(k, None)
            elif v is not None:
                current[k] = v
        conn.secret_encrypted = encrypt_secrets(current)

    db.merge(conn)
    db.commit()
    audit.record(db, action="tenant.data_connector_updated", actor_email=principal.email,
                 actor_role=principal.role, tenant_id=conn.tenant_id, detail=f"#{conn.id}")
    return _public(conn)


@router.delete("/{cid}")
def delete_connector(cid: int, principal=Depends(require(Permission.DATA_CONNECTOR_MANAGE)), db=Depends(get_db)):
    conn = _get_owned(db, principal, cid)
    db.query(ConnectorSyncRun).filter(ConnectorSyncRun.connector_id == cid).delete()
    db.delete(conn)
    db.commit()
    audit.record(db, action="tenant.data_connector_deleted", actor_email=principal.email,
                 actor_role=principal.role, tenant_id=conn.tenant_id, detail=f"#{cid}")
    return {"deleted": cid}


# ── Test ─────────────────────────────────────────────────────────

@router.post("/{cid}/test")
def test_connector(cid: int, principal=Depends(require(Permission.DATA_CONNECTOR_MANAGE)), db=Depends(get_db)):
    conn = _get_owned(db, principal, cid)
    provider = PROVIDERS.get(conn.provider)
    if not provider:
        return {"ok": False, "detail": f"Unknown provider '{conn.provider}'"}
    cfg = conn.config_json or {}
    secrets = decrypt_secrets(conn.secret_encrypted)
    try:
        provider.validate(cfg, secrets)
        files = provider.list_files(cfg, secrets)
        supported = [f for f in files if not validate_file(f.get("name", ""), b"")]
        return {"ok": True, "detail": f"{len(files)} files visible, {len(supported)} supported types"}
    except ConnectorConfigError as e:
        return {"ok": False, "detail": str(e)}
    except Exception as e:  # noqa: BLE001 — surface any backend failure to the admin
        return {"ok": False, "detail": str(e)[:400]}


# ── Sync ─────────────────────────────────────────────────────────

@router.post("/{cid}/sync")
def start_sync(cid: int, background: BackgroundTasks, principal=Depends(require(Permission.DATA_CONNECTOR_MANAGE)),
               db=Depends(get_db)):
    conn = _get_owned(db, principal, cid)
    if not conn.is_active:
        raise HTTPException(400, "Connector is disabled")

    running = (db.query(ConnectorSyncRun)
               .filter(ConnectorSyncRun.connector_id == cid,
                       ConnectorSyncRun.status == "running")
               .order_by(ConnectorSyncRun.started_at.desc()).first())
    if running:
        started = running.started_at
        if started and started.tzinfo is None:
            started = started.replace(tzinfo=dt.timezone.utc)
        age_min = (utcnow() - started).total_seconds() / 60 if started else 999
        if age_min < STALE_RUN_MINUTES:
            raise HTTPException(409, "A sync is already running for this connector")
        running.status = "failed"
        running.detail = "Superseded — previous run looked stuck"
        running.finished_at = utcnow()

    run = ConnectorSyncRun(connector_id=cid, tenant_id=conn.tenant_id, status="running")
    db.add(run)
    conn.last_sync_status = "running"
    db.merge(conn)
    db.commit()
    run_id = run.id

    background.add_task(_run_sync, cid, principal.tenant.slug, run_id)
    audit.record(db, action="tenant.data_connector_sync", actor_email=principal.email,
                 actor_role=principal.role, tenant_id=conn.tenant_id,
                 detail=f"#{cid} run={run_id}")
    return {"run_id": run_id, "status": "running"}


@router.get("/{cid}/runs")
def list_runs(cid: int, limit: int = 20, principal=Depends(require(Permission.DATA_CONNECTOR_MANAGE)),
              db=Depends(get_db)):
    _get_owned(db, principal, cid)
    rows = (db.query(ConnectorSyncRun)
            .filter(ConnectorSyncRun.connector_id == cid)
            .order_by(ConnectorSyncRun.started_at.desc())
            .limit(min(limit, 100)).all())
    return [_run_public(r) for r in rows]


def _run_sync(connector_id: int, tenant_slug: str, run_id: int) -> None:
    """Background worker: list → download → register → ingest, tallying results.

    Connector documents are ingested inline here (not via BackgroundTasks) since
    this function is already running off the request thread and still holds the
    downloaded bytes.
    """
    db = SessionLocal()
    queued = skipped = failed = 0
    errors: list[str] = []
    try:
        conn = db.get(DataConnector, connector_id)
        tenant = db.query(Tenant).filter(Tenant.slug == tenant_slug).first()
        run = db.get(ConnectorSyncRun, run_id)
        if not (conn and tenant and run):
            return
        provider = PROVIDERS.get(conn.provider)
        if not provider:
            raise ConnectorConfigError(f"Unknown provider '{conn.provider}'")

        cfg = conn.config_json or {}
        secrets = decrypt_secrets(conn.secret_encrypted)
        files = provider.list_files(cfg, secrets)

        pending: list[tuple[int, str, bytes]] = []
        for f in files:
            name = f.get("name", "unnamed")
            if validate_file(name, b"x"):         # unsupported extension
                skipped += 1
                continue
            try:
                fname, data = provider.download_file(f, cfg, secrets)
            except Exception as e:  # noqa: BLE001
                failed += 1
                errors.append(f"{name}: download failed: {e}")
                continue
            doc, _reason = register_document(db, tenant, fname, data, conn.provider)
            if doc:
                queued += 1
                pending.append((doc.id, fname, data))
            else:
                skipped += 1                      # duplicate / too large

        status = "failed" if (failed and not queued) else ("partial" if failed else "success")
        summary = f"{queued} queued, {skipped} skipped, {failed} failed"
        detail = summary + (" — " + "; ".join(errors[:5]) if errors else "")
        run.status, run.detail, run.finished_at = status, detail[:2000], utcnow()
        run.queued, run.skipped, run.failed = queued, skipped, failed
        conn.last_sync_at = utcnow()
        conn.last_sync_status = status
        conn.last_sync_detail = summary
        db.merge(run)
        db.merge(conn)
        db.commit()

        obs.count("connector.syncs", provider=conn.provider, status=status,
                  help="Connector sync runs, by outcome")
        obs.event("connector.sync.completed", tenant=tenant_slug, provider=conn.provider,
                  status=status, queued=queued, skipped=skipped, failed=failed)

        for doc_id, fname, data in pending:
            try:
                ingest_document(doc_id, tenant_slug, fname, data)
            except Exception:  # noqa: BLE001 — per-doc failure is recorded on the Document row
                log.exception("connector ingest failed for doc %s", doc_id)
    except Exception as e:  # noqa: BLE001
        obs.count("connector.syncs", provider="?", status="error")
        obs.event("connector.sync.completed", tenant=tenant_slug, status="error",
                  level="error", error=str(e)[:300])
        log.exception("connector sync failed (connector=%s run=%s)", connector_id, run_id)
        run = db.get(ConnectorSyncRun, run_id)
        conn = db.get(DataConnector, connector_id)
        if run:
            run.status = "failed"
            run.detail = f"{queued} queued before error — {e}"[:2000]
            run.finished_at = utcnow()
            run.queued, run.skipped, run.failed = queued, skipped, failed
            db.merge(run)
        if conn:
            conn.last_sync_at = utcnow()
            conn.last_sync_status = "failed"
            conn.last_sync_detail = str(e)[:400]
            db.merge(conn)
        db.commit()
    finally:
        db.close()
