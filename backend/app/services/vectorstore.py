"""Qdrant vector store.

One collection per tenant *and embedding model* gives hard tenant isolation and
safe model upgrades. Embeddings from different models/dimensions are never mixed.
"""
from __future__ import annotations

import uuid
from typing import List

from qdrant_client import QdrantClient
from qdrant_client.models import (Distance, FieldCondition, Filter,
                                  IsEmptyCondition, MatchAny, MatchValue,
                                  PayloadField, PointStruct, VectorParams)

from ..config import get_settings
from ..crypto import decrypt, encrypt
from ..model_catalog import safe_slug
from ..resilience import retry_call
from .embeddings import embedding_dim

try:                                             # network/timeout errors talking to Qdrant
    from qdrant_client.http.exceptions import ResponseHandlingException
    _TRANSIENT = (ResponseHandlingException, ConnectionError, TimeoutError, OSError)
except Exception:                                # pragma: no cover
    _TRANSIENT = (ConnectionError, TimeoutError, OSError)

_client: QdrantClient | None = None


def client() -> QdrantClient:
    global _client
    if _client is None:
        _client = QdrantClient(url=get_settings().qdrant_url, timeout=30)
    return _client


def collection_name(tenant_slug: str, embedding_model: str | None = None,
                    embedding_provider: str | None = None) -> str:
    if not embedding_model:
        # Legacy collection name for older POC data.
        return f"kd_{tenant_slug}"
    return f"kd_{safe_slug(tenant_slug)}_{safe_slug(embedding_provider or 'local')}_{safe_slug(embedding_model)}"


def ensure_collection(tenant_slug: str, vector_size: int | None = None,
                      embedding_model: str | None = None,
                      embedding_provider: str | None = None) -> None:
    name = collection_name(tenant_slug, embedding_model, embedding_provider)
    if not client().collection_exists(name):
        client().create_collection(
            collection_name=name,
            vectors_config=VectorParams(
                size=vector_size or embedding_dim(embedding_provider, embedding_model),
                distance=Distance.COSINE,
            ),
        )


def upsert_chunks(tenant_slug: str, doc_id: int, filename: str,
                  chunks, vectors: List[List[float]], metadata: dict | None = None) -> None:
    metadata = metadata or {}
    embedding_model = metadata.get("embedding_model")
    embedding_provider = metadata.get("embedding_provider", "local")
    ensure_collection(
        tenant_slug,
        vector_size=len(vectors[0]) if vectors else None,
        embedding_model=embedding_model,
        embedding_provider=embedding_provider,
    )
    points = [
        PointStruct(
            id=str(uuid.uuid4()),
            vector=vec,
            payload={
                "doc_id": doc_id,
                "filename": filename,
                "page": ch.page,
                "chunk_index": ch.index,
                "text": encrypt(ch.text),          # document content — encrypted at rest
                "source": metadata.get("source", "upload"),
                "department": metadata.get("department", ""),
                "confidentiality": metadata.get("confidentiality", "internal"),
                "tags": metadata.get("tags", []),
                "model_profile": metadata.get("model_profile", ""),
                "embedding_provider": embedding_provider,
                "embedding_model": embedding_model or "",
                "scope": metadata.get("scope", "tenant"),
                "owner_user_id": metadata.get("owner_user_id"),
            },
        )
        for ch, vec in zip(chunks, vectors)
    ]
    cname = collection_name(tenant_slug, embedding_model, embedding_provider)
    for i in range(0, len(points), 256):
        batch = points[i:i + 256]
        retry_call(lambda b=batch: client().upsert(collection_name=cname, points=b),
                   op="qdrant.upsert", retry_on=_TRANSIENT)


def _access_conditions(access: dict | None) -> list:
    """MUST-clauses restricting hits to what the caller may read. Each is an
    OR-group; together they AND. Enforced server-side — a request cannot widen it.

    ``access`` = {
        user_id, scope,                         # identity + workspace|company|all
        granted_doc_ids: [int],                 # docs explicitly shared with the caller
        allowed_confidentialities: [str] | None  # ABAC clearance; None = unrestricted
    }

    Points written before the ownership model have no ``scope`` payload key; an
    ``IsEmpty`` clause treats those as company-wide so nothing 404s mid-migration.
    """
    if not access:
        return []
    uid = access.get("user_id")
    want = (access.get("scope") or "all").lower()
    granted = [int(x) for x in (access.get("granted_doc_ids") or [])]
    allowed_conf = access.get("allowed_confidentialities")

    company = [
        FieldCondition(key="scope", match=MatchValue(value="tenant")),
        IsEmptyCondition(is_empty=PayloadField(key="scope")),
    ]
    mine = ([FieldCondition(key="owner_user_id", match=MatchValue(value=uid))]
            if uid is not None else [])
    shared = [FieldCondition(key="doc_id", match=MatchAny(any=granted))] if granted else []

    if want == "company":
        visibility = company + shared
    elif want == "workspace":
        visibility = (mine + shared) or company
    else:                                # "all"
        visibility = company + mine + shared

    conds = [Filter(should=visibility)]

    # ABAC: clearance. Own / shared documents bypass it.
    if allowed_conf is not None:
        conf_ok = [FieldCondition(key="confidentiality", match=MatchAny(any=list(allowed_conf)))]
        conds.append(Filter(should=conf_ok + mine + shared))

    return conds


def _query_filter(filters: dict | None, access: dict | None) -> Filter | None:
    must = []
    if filters:
        if filters.get("doc_ids"):
            must.append(FieldCondition(key="doc_id", match=MatchAny(any=filters["doc_ids"])))
        if filters.get("source"):
            must.append(FieldCondition(key="source", match=MatchValue(value=filters["source"])))
        if filters.get("filename"):
            must.append(FieldCondition(key="filename", match=MatchValue(value=filters["filename"])))
        if filters.get("department"):
            must.append(FieldCondition(key="department", match=MatchValue(value=filters["department"])))
        if filters.get("confidentiality"):
            must.append(FieldCondition(key="confidentiality", match=MatchValue(value=filters["confidentiality"])))
    must.extend(_access_conditions(access))
    return Filter(must=must) if must else None


def search(tenant_slug: str, vector: List[float], top_k: int,
           score_threshold: float, filters: dict | None = None,
           embedding_model: str | None = None,
           embedding_provider: str | None = None,
           access: dict | None = None):
    ensure_collection(
        tenant_slug,
        vector_size=len(vector),
        embedding_model=embedding_model,
        embedding_provider=embedding_provider,
    )
    hits = retry_call(
        lambda: client().query_points(
            collection_name=collection_name(tenant_slug, embedding_model, embedding_provider),
            query=vector,
            query_filter=_query_filter(filters, access),
            limit=top_k,
            score_threshold=score_threshold,
            with_payload=True,
        ),
        op="qdrant.search", retry_on=_TRANSIENT).points
    return [
        {
            "score": h.score,
            "doc_id": h.payload.get("doc_id"),
            "filename": h.payload.get("filename"),
            "page": h.payload.get("page"),
            "text": decrypt(h.payload.get("text", "")) or "",
            "embedding_model": h.payload.get("embedding_model", ""),
            "scope": h.payload.get("scope", "tenant"),
        }
        for h in hits
    ]


def _tenant_collection_names(tenant_slug: str) -> list[str]:
    prefix = f"kd_{safe_slug(tenant_slug)}"
    legacy = f"kd_{tenant_slug}"
    try:
        cols = client().get_collections().collections
        return [c.name for c in cols if c.name == legacy or c.name.startswith(prefix)]
    except Exception:
        return [legacy]


def delete_document(tenant_slug: str, doc_id: int) -> None:
    for name in _tenant_collection_names(tenant_slug):
        if client().collection_exists(name):
            client().delete(
                collection_name=name,
                points_selector=Filter(
                    must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]
                ),
            )


def drop_tenant(tenant_slug: str) -> None:
    for name in _tenant_collection_names(tenant_slug):
        if client().collection_exists(name):
            client().delete_collection(name)


def healthy() -> bool:
    try:
        client().get_collections()
        return True
    except Exception:
        return False


def reencrypt_text_payloads() -> dict:
    """Encrypt any legacy plaintext ``text`` payloads across every KnowledgeDesk
    collection. Idempotent — already-encrypted values are skipped. Returns a
    per-collection tally. Used by scripts/reencrypt_at_rest.py."""
    from ..crypto import encrypt
    c = client()
    tally: dict[str, int] = {}
    try:
        names = [col.name for col in c.get_collections().collections
                 if col.name.startswith("kd_")]
    except Exception:
        return tally
    for name in names:
        updated, offset = 0, None
        while True:
            points, offset = c.scroll(collection_name=name, limit=256, offset=offset,
                                      with_payload=True, with_vectors=False)
            for p in points:
                txt = (p.payload or {}).get("text")
                if isinstance(txt, str) and not txt.startswith("kdenc:"):
                    c.set_payload(collection_name=name, payload={"text": encrypt(txt)},
                                  points=[p.id])
                    updated += 1
            if not offset:
                break
        if updated:
            tally[name] = updated
    return tally
