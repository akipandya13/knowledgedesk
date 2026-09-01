"""Document management: upload, bulk ZIP ingest, list, reindex, delete.

Two layers of documents live in one workspace:

  * company-wide (``scope='tenant'``)   — published by a workspace admin,
    visible to and searchable by everyone in the workspace.
  * personal      (``scope='workspace'``) — owned by one user, visible only to
    that user (and to workspace admins, who manage everyone's documents).

Members may only create and delete documents in their own workspace layer.
Publishing company-wide, or acting on another user's document, needs
``document.write.tenant`` (workspace admin or service key).
"""
from __future__ import annotations

import io
import zipfile
from typing import Annotated, Literal

from fastapi import (APIRouter, BackgroundTasks, Depends, File, Form,
                     HTTPException, UploadFile)
from sqlalchemy import and_, or_

from .. import authz
from ..auth import Principal, get_db, require
from ..database import (DOC_SCOPE_TENANT, DOC_SCOPE_WORKSPACE, Document, User)
from ..rbac import Permission
from ..services import vectorstore
from ..services.ingestion import queue_document

router = APIRouter(prefix="/api/documents", tags=["documents"])

ScopeParam = Literal["workspace", "company", "all"]


def _split_tags(tags: str | None) -> list[str]:
    return [t.strip() for t in (tags or "").split(",") if t.strip()]


def _doc_out(d: Document, owner_email: str | None = None) -> dict:
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
        "scope": d.scope or DOC_SCOPE_TENANT,
        "owner_user_id": d.owner_user_id,
        "owner_email": owner_email,
        "created_at": d.created_at.isoformat() if d.created_at else None,
    }


def _resolve_target(principal: Principal, scope: str, owner_user_id: str,
                    db) -> tuple[str, int | None]:
    """Decide the (scope, owner_user_id) a new document should be created with,
    enforcing what this principal is allowed to do.

    * no scope given        → admins publish company-wide, members go to their
                              own workspace (matches the product's default).
    * scope='company'       → workspace admin / service only.
    * scope='workspace'     → the caller's own workspace, unless an admin names
                              another user via ``owner_user_id``.
    """
    is_admin = principal.can(Permission.DOC_WRITE_TENANT)
    want = (scope or "").strip().lower()
    if not want:
        want = "company" if is_admin else "workspace"

    if want in ("company", DOC_SCOPE_TENANT):
        if not is_admin:
            raise HTTPException(403, "Only workspace admins can publish company-wide documents")
        return DOC_SCOPE_TENANT, None

    if want != "workspace":
        raise HTTPException(400, "scope must be 'workspace' or 'company'")

    owner_id = principal.user_id
    target = (owner_user_id or "").strip()
    if target:
        if not is_admin:
            raise HTTPException(403, "You can only upload to your own workspace")
        user = db.get(User, int(target)) if target.isdigit() else None
        if not user or user.tenant_id != principal.tenant.id:
            raise HTTPException(404, "Target user not found in this workspace")
        owner_id = user.id
    if owner_id is None:
        raise HTTPException(400, "A workspace document needs an owner (service keys must publish company-wide)")
    return DOC_SCOPE_WORKSPACE, owner_id


@router.post("/upload")
async def upload(background: BackgroundTasks,
                 files: Annotated[list[UploadFile], File()],
                 department: Annotated[str, Form()] = "",
                 confidentiality: Annotated[str, Form()] = "internal",
                 tags: Annotated[str, Form()] = "",
                 scope: Annotated[str, Form()] = "",
                 owner_user_id: Annotated[str, Form()] = "",
                 principal: Principal = Depends(require(Permission.DOC_WRITE_WORKSPACE)),
                 db=Depends(get_db)):
    """Upload one or more documents into the caller's workspace, or (admins)
    company-wide / into a named user's workspace."""
    doc_scope, owner_id = _resolve_target(principal, scope, owner_user_id, db)
    accepted, rejected = [], []
    for f in files:
        name = f.filename or "unnamed"
        data = await f.read()
        doc, reason = queue_document(db, background, principal.tenant, name, data, "upload",
                                     department, confidentiality, _split_tags(tags),
                                     scope=doc_scope, owner_user_id=owner_id)
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
                     scope: Annotated[str, Form()] = "",
                     owner_user_id: Annotated[str, Form()] = "",
                     principal: Principal = Depends(require(Permission.DOC_WRITE_WORKSPACE)),
                     db=Depends(get_db)):
    """Bulk-ingest a ZIP export from Drive/SharePoint/local folders."""
    doc_scope, owner_id = _resolve_target(principal, scope, owner_user_id, db)
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
        doc, reason = queue_document(db, background, principal.tenant, name, payload, "zip",
                                     department, confidentiality, _split_tags(tags),
                                     scope=doc_scope, owner_user_id=owner_id)
        if doc:
            accepted.append(_doc_out(doc))
        else:
            rejected.append({"filename": name, "reason": reason})
    return {"accepted": accepted, "rejected": rejected, "total_seen": len(accepted) + len(rejected)}


@router.get("")
def list_documents(status: str | None = None, source: str | None = None,
                   scope: ScopeParam = "all", owner_user_id: int | None = None,
                   principal: Principal = Depends(require(Permission.DOC_READ)),
                   db=Depends(get_db)):
    tenant = principal.tenant
    is_admin = principal.can(Permission.DOC_WRITE_TENANT)
    q = db.query(Document).filter(Document.tenant_id == tenant.id,
                                  Document.is_active == True)  # noqa: E712

    # Documents explicitly shared with this caller (or a group) via a per-object
    # ACL — visible regardless of scope / ownership / clearance.
    shared_ids = {int(x) for x in
                  authz.granted_resource_ids(db, principal, "document", Permission.DOC_READ)
                  if str(x).isdigit()}

    # Visibility: admins see everything in the workspace; members see company-wide
    # documents plus their own plus anything shared with them. `scope` narrows.
    if not is_admin:
        uid = principal.user_id
        mine = and_(Document.scope == DOC_SCOPE_WORKSPACE, Document.owner_user_id == uid)
        shared = Document.id.in_(shared_ids) if shared_ids else False
        if scope == "company":
            q = q.filter(or_(Document.scope == DOC_SCOPE_TENANT, shared))
        elif scope == "workspace":
            q = q.filter(or_(mine, shared))
        else:
            q = q.filter(or_(Document.scope == DOC_SCOPE_TENANT, mine, shared))

        # ABAC: confidentiality clearance (opt-in per tenant). Own / shared docs
        # bypass the clearance check.
        allowed = authz.allowed_confidentialities(
            principal.user, authz.confidentiality_enforced(tenant))
        if allowed is not None:
            q = q.filter(or_(Document.confidentiality.in_(allowed), mine, shared))
    else:
        if scope == "company":
            q = q.filter(Document.scope == DOC_SCOPE_TENANT)
        elif scope == "workspace":
            q = q.filter(Document.scope == DOC_SCOPE_WORKSPACE)
        if owner_user_id is not None:
            q = q.filter(Document.owner_user_id == owner_user_id)

    if status:
        q = q.filter(Document.status == status)
    if source:
        q = q.filter(Document.source == source)
    docs = q.order_by(Document.created_at.desc()).all()

    owner_ids = {d.owner_user_id for d in docs if d.owner_user_id}
    emails = ({u.id: u.email for u in db.query(User).filter(User.id.in_(owner_ids))}
              if owner_ids else {})
    return [_doc_out(d, emails.get(d.owner_user_id)) for d in docs]


@router.post("/{doc_id}/reindex")
def reindex_document(doc_id: int,
                     principal: Principal = Depends(require(Permission.DOC_WRITE_WORKSPACE))):
    """Placeholder for connector-backed reindexing. Uploads are immutable in v1 demo."""
    raise HTTPException(501, "Reindex requires original connector/file source; re-upload the file for now")


@router.delete("/{doc_id}")
def delete_document(doc_id: int,
                    principal: Principal = Depends(require(Permission.DOC_READ)),
                    db=Depends(get_db)):
    tenant = principal.tenant
    doc = (db.query(Document)
           .filter(Document.id == doc_id, Document.tenant_id == tenant.id).first())
    if not doc:
        raise HTTPException(404, "Document not found")

    is_admin = principal.can(Permission.DOC_WRITE_TENANT)
    owns_it = (doc.scope == DOC_SCOPE_WORKSPACE
               and doc.owner_user_id is not None
               and doc.owner_user_id == principal.user_id)
    granted = authz.can_on(db, principal, Permission.DOC_DELETE, "document", doc.id)
    if not (is_admin or owns_it or granted):
        raise HTTPException(403, "You can only delete documents in your own workspace")

    vectorstore.delete_document(tenant.slug, doc.id)
    doc.is_active = False
    doc.status = "deleted"
    db.commit()
    return {"deleted": doc_id}
