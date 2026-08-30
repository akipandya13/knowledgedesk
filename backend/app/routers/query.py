"""Ask & search endpoints.

Every request is scoped to what the caller may read: their own workspace
documents plus any company-wide documents a workspace admin has published.
The ``scope`` field only narrows that set — it can never widen it.
"""
from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..auth import Principal, get_db, require
from ..database import QueryLog
from ..rbac import Permission
from ..services import rag

router = APIRouter(prefix="/api/query", tags=["query"])

# workspace = only my private docs · company = only admin-published docs · all = both
SearchScope = Literal["workspace", "company", "all"]


class QueryFilters(BaseModel):
    doc_ids: list[int] | None = None
    source: str | None = None
    filename: str | None = None

    def clean(self) -> dict:
        return {k: v for k, v in self.model_dump().items() if v not in (None, [], "")}


class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    filters: QueryFilters | None = None
    scope: SearchScope = "all"


class FeedbackRequest(BaseModel):
    query_id: int
    helpful: bool


def _access(principal: Principal, scope: SearchScope) -> dict:
    return {"user_id": principal.user_id, "scope": scope}


@router.post("/ask")
async def ask(req: AskRequest,
             principal: Principal = Depends(require(Permission.QUERY_RUN))):
    """One-shot answer with citations and optional document/source filters."""
    return await rag.answer(principal.tenant, req.question.strip(),
                            req.filters.clean() if req.filters else None,
                            access=_access(principal, req.scope))


@router.post("/ask/stream")
async def ask_stream(req: AskRequest,
                     principal: Principal = Depends(require(Permission.QUERY_RUN))):
    """Server-Sent Events stream: meta → token* → done."""
    filters = req.filters.clean() if req.filters else None
    access = _access(principal, req.scope)

    async def event_source():
        async for event in rag.answer_stream(principal.tenant, req.question.strip(),
                                             filters, access=access):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_source(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@router.post("/search")
def search(req: AskRequest,
           principal: Principal = Depends(require(Permission.QUERY_RUN))):
    """Raw semantic search — passages only, no LLM. Instant, zero cost."""
    try:
        hits = rag.retrieve(principal.tenant, req.question.strip(),
                            req.filters.clean() if req.filters else None,
                            _access(principal, req.scope))
    except (rag.embeddings.ModelLoadBlocked, rag.embeddings.EmbeddingError) as exc:
        raise HTTPException(status_code=409, detail=rag._blocked_model_answer(exc)) from exc
    return {"results": rag._sources(hits)}


@router.post("/feedback")
def feedback(req: FeedbackRequest,
             principal: Principal = Depends(require(Permission.FEEDBACK_WRITE)),
             db=Depends(get_db)):
    row = (db.query(QueryLog)
           .filter(QueryLog.id == req.query_id,
                   QueryLog.tenant_id == principal.tenant.id).first())
    if not row:
        raise HTTPException(404, "Query not found")
    row.feedback = 1 if req.helpful else -1
    db.commit()
    return {"ok": True}
