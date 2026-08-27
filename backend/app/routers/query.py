"""Ask & search endpoints."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..auth import get_db, get_tenant
from ..database import QueryLog
from ..services import rag

router = APIRouter(prefix="/api/query", tags=["query"])


class QueryFilters(BaseModel):
    doc_ids: list[int] | None = None
    source: str | None = None
    filename: str | None = None

    def clean(self) -> dict:
        return {k: v for k, v in self.model_dump().items() if v not in (None, [], "")}


class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    filters: QueryFilters | None = None


class FeedbackRequest(BaseModel):
    query_id: int
    helpful: bool


@router.post("/ask")
async def ask(req: AskRequest, tenant=Depends(get_tenant)):
    """One-shot answer with citations and optional document/source filters."""
    return await rag.answer(tenant, req.question.strip(), req.filters.clean() if req.filters else None)


@router.post("/ask/stream")
async def ask_stream(req: AskRequest, tenant=Depends(get_tenant)):
    """Server-Sent Events stream: meta → token* → done."""
    filters = req.filters.clean() if req.filters else None

    async def event_source():
        async for event in rag.answer_stream(tenant, req.question.strip(), filters):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_source(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@router.post("/search")
def search(req: AskRequest, tenant=Depends(get_tenant)):
    """Raw semantic search — passages only, no LLM. Instant, zero cost."""
    try:
        hits = rag.retrieve(tenant, req.question.strip(), req.filters.clean() if req.filters else None)
    except rag.embeddings.ModelLoadBlocked as exc:
        raise HTTPException(status_code=409, detail=rag._blocked_model_answer(exc)) from exc
    return {"results": rag._sources(hits)}


@router.post("/feedback")
def feedback(req: FeedbackRequest, tenant=Depends(get_tenant), db=Depends(get_db)):
    row = (db.query(QueryLog)
           .filter(QueryLog.id == req.query_id,
                   QueryLog.tenant_id == tenant.id).first())
    if not row:
        raise HTTPException(404, "Query not found")
    row.feedback = 1 if req.helpful else -1
    db.commit()
    return {"ok": True}
