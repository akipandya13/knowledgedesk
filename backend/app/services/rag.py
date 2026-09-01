"""RAG pipeline: retrieve → rerank → ground → answer with citations.

Tenant admins can select per-workspace embedding/reranker/generation models.
The pipeline always searches the vector collection that matches the tenant's
current embedding model, preventing incompatible vectors from being mixed.
"""
from __future__ import annotations

import time
from typing import AsyncIterator

from .. import observability as obs
from ..config import get_settings
from ..database import SessionLocal, QueryLog, Tenant
from ..tenant_settings import effective_settings, resolve_model_config, as_bool
from . import activity, embeddings, llm, vectorstore, reranker

NOT_FOUND_MESSAGE = ("I couldn't find anything in the company knowledge base that "
                     "answers this. It has been logged as a knowledge gap so the "
                     "right document can be added.")

MODEL_BLOCKED_PREFIX = "Model configuration needs admin attention"


def retrieve(tenant: Tenant, question: str, filters: dict | None = None,
             access: dict | None = None) -> list[dict]:
    cfg = resolve_model_config(tenant)
    top_k = int(cfg.get("retrieval_top_k", get_settings().retrieval_top_k))
    threshold = float(cfg.get("retrieval_score_threshold", get_settings().retrieval_score_threshold))
    embedding_provider = cfg.get("embedding_provider", "local")
    embedding_model = cfg.get("embedding_model")

    with obs.span("rag.embed_query", model=embedding_model), \
            obs.timer("rag.stage.seconds", stage="embed_query"):
        vector = embeddings.embed_query(question, provider=embedding_provider,
                                        model_name=embedding_model, runtime=cfg)
    with obs.span("rag.vector_search", top_k=top_k), \
            obs.timer("rag.stage.seconds", stage="vector_search"):
        hits = vectorstore.search(
            tenant.slug,
            vector,
            top_k,
            threshold,
            filters=filters,
            embedding_model=embedding_model,
            embedding_provider=embedding_provider,
            access=access,
        )
    obs.observe("rag.retrieval.hits", len(hits), stage="vector_search")

    if as_bool(cfg.get("reranker_enabled")) and cfg.get("reranker_model"):
        with obs.span("rag.rerank", model=str(cfg.get("reranker_model") or "")), \
                obs.timer("rag.stage.seconds", stage="rerank"):
            hits = reranker.rerank(
                question,
                hits,
                str(cfg.get("reranker_model") or ""),
                int(cfg.get("rerank_top_k") or min(8, len(hits))),
            )

    # Trim to the context budget.
    budget = int(cfg.get("retrieval_max_context_chars", get_settings().retrieval_max_context_chars))
    kept, used = [], 0
    for h in hits:
        if used + len(h["text"]) > budget and kept:
            break
        kept.append(h)
        used += len(h["text"])

    _record_retrieval(tenant, access, kept)
    return kept


def _record_retrieval(tenant: Tenant, access: dict | None, hits: list[dict]) -> None:
    """Activity trail: one ``document.retrieved`` row per distinct document a
    user's question actually surfaced content from. Best-effort — a logging
    failure must not affect the answer."""
    uid = (access or {}).get("user_id")
    if not uid or not hits:
        return
    seen: dict[int, dict] = {}
    for h in hits:
        did = h.get("doc_id")
        if did is not None and did not in seen:
            seen[did] = h
    if not seen:
        return
    db = SessionLocal()
    try:
        for did, h in seen.items():
            activity.record(db, action="document.retrieved", category="read",
                            user_id=uid, tenant_id=tenant.id,
                            target_type="document", target_id=did,
                            meta={"filename": h.get("filename"),
                                  "score": round(h.get("score") or 0, 3)})
    except Exception:                                    # pragma: no cover
        pass
    finally:
        db.close()


def _blocked_model_answer(exc: Exception) -> str:
    return (
        f"{MODEL_BLOCKED_PREFIX}: {exc}\n\n"
        "Open Settings as a tenant admin and switch the profile to 'Demo Fast / Laptop Safe' "
        "for this Docker demo, or enable premium models with ALLOW_HEAVY_LOCAL_MODELS=true, "
        "HF_TOKEN, and suitable GPU hardware. After changing the embedding model, re-upload or "
        "re-seed documents so the vector index matches the selected model."
    )


def _build_prompts(tenant: Tenant, question: str, hits: list[dict]) -> tuple[str, str]:
    s = get_settings()
    cfg = effective_settings(tenant)
    context = "\n\n".join(
        f"[{i}] (Source: {h['filename']}, page {h['page']})\n{h['text']}"
        for i, h in enumerate(hits, start=1)
    )

    answer_language = cfg.get("answer_language", s.answer_language)
    lang = ("Answer in the same language as the question."
            if answer_language == "auto"
            else f"Always answer in {answer_language}.")
    refusal = ("If the context does not contain the answer, say you don't know — "
               "never invent information." if s.answer_refuse_outside_knowledge else "")
    citations = ("Cite the sources you used inline as [1], [2] etc., matching the "
                 "numbered context blocks." if s.answer_include_citations else "")

    system = (
        f"You are {s.app_name}, the internal knowledge assistant for "
        f"{tenant.name}. Answer employee questions using ONLY the provided "
        f"context from company documents. Be direct and concise. {refusal} "
        f"{citations} {lang}"
    )
    user = f"Context from company documents:\n\n{context}\n\nQuestion: {question}"
    return system, user


def _extractive_answer(hits: list[dict], reason: str | None = None) -> str:
    parts = []
    for i, h in enumerate(hits[:3], start=1):
        snippet = h["text"][:500].rstrip() + ("…" if len(h["text"]) > 500 else "")
        parts.append(f"[{i}] {snippet}")
    detail = f" Reason: {reason}" if reason else ""
    return (
        "AI generation is currently unavailable, but document retrieval worked."
        f"{detail}\n\n"
        "Showing the most relevant excerpts instead. To get generated answers on a "
        "16 GB MacBook demo, open Settings and use Demo Fast / Laptop Safe with "
        "Gemma 3 4B, then wait until Ollama shows the model as ready.\n\n"
        + "\n\n".join(parts)
    )


def _sources(hits: list[dict]) -> list[dict]:
    return [
        {
            "n": i,
            "filename": h["filename"],
            "page": h["page"],
            "score": round(h["score"] or 0, 3),
            "rerank_score": round(h.get("rerank_score"), 3) if h.get("rerank_score") is not None else None,
            "snippet": h["text"][:280],
        }
        for i, h in enumerate(hits, start=1)
    ]


def _log(tenant_id: int, question: str, answer: str, mode: str,
         confidence: float, latency_ms: int, sources: list[dict],
         filters: dict | None = None, user_id: int | None = None) -> int:
    db = SessionLocal()
    try:
        row = QueryLog(tenant_id=tenant_id, user_id=user_id, question=question,
                       answer=answer, mode=mode, confidence=confidence,
                       latency_ms=latency_ms, sources_json=sources,
                       filters_json=filters or {})
        db.add(row)
        db.commit()
        return row.id
    finally:
        db.close()


def _emit_answer(tenant: Tenant, mode: str, latency_ms: int, confidence: float,
                 n_sources: int, streamed: bool = False) -> None:
    """One place the answer outcome is turned into metrics + a domain event."""
    obs.count("rag.answers", mode=mode, streamed=str(streamed).lower(),
              help="Answers produced, by outcome mode")
    obs.observe("rag.answer.seconds", latency_ms / 1000.0, mode=mode,
                help="End-to-end answer latency")
    kind = "question.not_found" if mode == "not_found" else "question.answered"
    obs.event(kind, level="warn" if mode in ("not_found", "model_blocked") else "info",
              mode=mode, latency_ms=latency_ms, confidence=round(float(confidence or 0), 3),
              sources=n_sources, streamed=streamed)


async def answer(tenant: Tenant, question: str, filters: dict | None = None,
                 access: dict | None = None) -> dict:
    s = get_settings()
    cfg = resolve_model_config(tenant)
    uid = (access or {}).get("user_id")
    t0 = time.time()
    with obs.span("rag.answer", tenant=tenant.slug) as _sp:
        try:
            hits = retrieve(tenant, question, filters, access)
        except (embeddings.ModelLoadBlocked, embeddings.EmbeddingError) as exc:
            text = _blocked_model_answer(exc)
            ms = int((time.time() - t0) * 1000)
            qid = _log(tenant.id, question, text, "model_blocked", 0.0, ms, [], filters, uid)
            _emit_answer(tenant, "model_blocked", ms, 0.0, 0)
            _sp.set(mode="model_blocked")
            return {"query_id": qid, "answer": text, "mode": "model_blocked",
                    "confidence": 0.0, "sources": [], "model_profile": cfg.get("model_profile")}

        if not hits:
            ms = int((time.time() - t0) * 1000)
            qid = _log(tenant.id, question, NOT_FOUND_MESSAGE, "not_found", 0.0, ms, [], filters, uid)
            _emit_answer(tenant, "not_found", ms, 0.0, 0)
            _sp.set(mode="not_found")
            return {"query_id": qid, "answer": NOT_FOUND_MESSAGE, "mode": "not_found",
                    "confidence": 0.0, "sources": []}

        system, user = _build_prompts(tenant, question, hits)
        try:
            with obs.span("rag.llm_generate", model=cfg.get("llm_model")), \
                    obs.timer("rag.stage.seconds", stage="llm_generate"):
                text = await llm.generate(system, user, runtime=cfg)
            mode = "llm"
        except llm.LLMUnavailable as exc:
            obs.count("rag.llm.failures", provider=cfg.get("llm_provider", "?"))
            if not s.llm_fallback_to_extractive:
                raise
            text, mode = _extractive_answer(hits, str(exc)), "llm_unavailable"

        sources = _sources(hits)
        confidence = hits[0].get("rerank_score") if hits[0].get("rerank_score") is not None else hits[0]["score"]
        ms = int((time.time() - t0) * 1000)
        qid = _log(tenant.id, question, text, mode, float(confidence or 0), ms, sources, filters, uid)
        _emit_answer(tenant, mode, ms, confidence or 0, len(sources))
        _sp.set(mode=mode, sources=len(sources))
        return {"query_id": qid, "answer": text, "mode": mode,
                "confidence": confidence, "sources": sources,
                "model_profile": cfg.get("model_profile"), "llm_model": cfg.get("llm_model")}


async def answer_stream(tenant: Tenant, question: str, filters: dict | None = None,
                        access: dict | None = None) -> AsyncIterator[dict]:
    """Yields events: {type: meta|token|done, ...} for SSE streaming."""
    s = get_settings()
    cfg = resolve_model_config(tenant)
    uid = (access or {}).get("user_id")
    t0 = time.time()
    try:
        hits = retrieve(tenant, question, filters, access)
    except (embeddings.ModelLoadBlocked, embeddings.EmbeddingError) as exc:
        text = _blocked_model_answer(exc)
        ms = int((time.time() - t0) * 1000)
        qid = _log(tenant.id, question, text, "model_blocked", 0.0, ms, [], filters, uid)
        _emit_answer(tenant, "model_blocked", ms, 0.0, 0, streamed=True)
        yield {"type": "meta", "mode": "model_blocked", "sources": [], "confidence": 0.0,
               "model_profile": cfg.get("model_profile")}
        yield {"type": "token", "text": text}
        yield {"type": "done", "query_id": qid}
        return

    if not hits:
        ms = int((time.time() - t0) * 1000)
        qid = _log(tenant.id, question, NOT_FOUND_MESSAGE, "not_found", 0.0, ms, [], filters, uid)
        _emit_answer(tenant, "not_found", ms, 0.0, 0, streamed=True)
        yield {"type": "meta", "mode": "not_found", "sources": [], "confidence": 0.0}
        yield {"type": "token", "text": NOT_FOUND_MESSAGE}
        yield {"type": "done", "query_id": qid}
        return

    sources = _sources(hits)
    confidence = hits[0].get("rerank_score") if hits[0].get("rerank_score") is not None else hits[0]["score"]
    yield {"type": "meta", "mode": "retrieved", "sources": sources,
           "confidence": confidence, "model_profile": cfg.get("model_profile"),
           "llm_model": cfg.get("llm_model")}

    system, user = _build_prompts(tenant, question, hits)
    collected: list[str] = []
    mode = "llm"
    try:
        async for tok in llm.generate_stream(system, user, runtime=cfg):
            collected.append(tok)
            yield {"type": "token", "text": tok}
    except llm.LLMUnavailable as exc:
        obs.count("rag.llm.failures", provider=cfg.get("llm_provider", "?"))
        if not s.llm_fallback_to_extractive:
            _emit_answer(tenant, "error", int((time.time() - t0) * 1000), 0.0, len(sources), streamed=True)
            yield {"type": "error", "message": f"LLM unavailable: {exc}"}
            return
        mode = "llm_unavailable"
        text = _extractive_answer(hits, str(exc))
        collected = [text]
        yield {"type": "status", "mode": mode, "message": str(exc)}
        yield {"type": "token", "text": text}

    full = "".join(collected)
    ms = int((time.time() - t0) * 1000)
    qid = _log(tenant.id, question, full, mode, float(confidence or 0), ms, sources, filters, uid)
    _emit_answer(tenant, mode, ms, confidence or 0, len(sources), streamed=True)
    yield {"type": "done", "query_id": qid}
