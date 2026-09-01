"""LLM gateway with per-tenant model selection.

Providers (set globally, per tenant, or via a tenant model connector):
  * ollama             — local models via Ollama. Zero API cost.
  * openai_compatible  — any /v1/chat/completions endpoint.
  * azure_foundry      — Azure AI Foundry / Azure OpenAI deployment.
  * bedrock            — AWS Bedrock (Converse API).
  * none               — skip the LLM entirely; answers are extractive.
"""
from __future__ import annotations

import asyncio
import json
import logging
import queue as _queue
import threading
from typing import Any, AsyncIterator

import time

import httpx

from .. import observability as obs
from ..config import get_settings
from ..http_client import get_async_client
from ..model_catalog import LARGE_OLLAMA_MODELS, SAFE_DEMO_OLLAMA_MODELS

log = logging.getLogger("knowledgedesk.llm")


class LLMUnavailable(Exception):
    """Raised when the configured generation model cannot be used."""


class LLMModelMissing(LLMUnavailable):
    """Raised when Ollama is reachable but the selected model is not installed."""


def _cfg(runtime: dict[str, Any] | None = None) -> dict[str, Any]:
    s = get_settings()
    base = {
        "llm_provider": s.llm_provider,
        "llm_model": s.llm_model,
        "openai_model": s.openai_model,
        "llm_temperature": s.llm_temperature,
        "llm_max_tokens": s.llm_max_tokens,
        "llm_timeout_seconds": s.llm_timeout_seconds,
        "openai_base_url": s.openai_base_url,
        "openai_api_key": s.openai_api_key,
        "ollama_url": s.ollama_url,
        "ollama_auto_pull_safe_models": s.ollama_auto_pull_safe_models,
        "allow_large_ollama_models": s.allow_large_ollama_models,
        "laptop_safe_mode": s.laptop_safe_mode,
        # Populated only when a tenant model connector is selected.
        "aws_region": "",
        "aws_access_key_id": "",
        "aws_secret_access_key": "",
        "aws_session_token": "",
        "azure_endpoint": "",
        "azure_deployment": "",
        "azure_api_version": "",
        "azure_api_key": "",
    }
    if runtime:
        base.update({k: v for k, v in runtime.items() if v is not None})
    return base


_NONE_MSG = ("The tenant is configured with LLM_PROVIDER=none. Open Settings and select "
             "a generation model (built-in Gemma 3 4B or a model connector) for generated answers.")


async def generate(system: str, user: str, runtime: dict[str, Any] | None = None) -> str:
    c = _cfg(runtime)
    provider = c["llm_provider"]
    t0 = time.perf_counter()
    try:
        out = await _generate_dispatch(provider, system, user, c)
        obs.count("llm.calls", provider=provider, outcome="ok")
        obs.observe("llm.response.chars", len(out or ""), provider=provider)
        return out
    except Exception:
        obs.count("llm.calls", provider=provider, outcome="error")
        raise
    finally:
        obs.observe("llm.generate.seconds", time.perf_counter() - t0, provider=provider,
                    help="LLM generation latency (non-streaming)")


async def _generate_dispatch(provider, system, user, c) -> str:
    if provider == "ollama":
        return await _ollama(system, user, c)
    if provider == "openai_compatible":
        return await _openai(system, user, c)
    if provider == "azure_foundry":
        return await _openai(system, user, c, url=_azure_url(c, "chat/completions"),
                             headers=_azure_headers(c))
    if provider == "bedrock":
        return await _bedrock(system, user, c)
    raise LLMUnavailable(_NONE_MSG)


async def generate_stream(system: str, user: str,
                          runtime: dict[str, Any] | None = None) -> AsyncIterator[str]:
    c = _cfg(runtime)
    provider = c["llm_provider"]
    if provider == "ollama":
        async for tok in _ollama_stream(system, user, c):
            yield tok
    elif provider == "openai_compatible":
        async for tok in _openai_stream(system, user, c):
            yield tok
    elif provider == "azure_foundry":
        async for tok in _openai_stream(system, user, c, url=_azure_url(c, "chat/completions"),
                                        headers=_azure_headers(c)):
            yield tok
    elif provider == "bedrock":
        async for tok in _bedrock_stream(system, user, c):
            yield tok
    else:
        raise LLMUnavailable(_NONE_MSG)


def _name_variants(model: str) -> set[str]:
    model = (model or "").strip()
    if not model or model == "none":
        return set()
    variants = {model}
    if ":" not in model:
        variants.add(f"{model}:latest")
    return variants


async def _ollama_tags(c: dict[str, Any]) -> set[str]:
    h = get_async_client()
    r = await h.get(f"{c['ollama_url']}/api/tags", timeout=10)
    r.raise_for_status()
    payload = r.json()
    return {m.get("name", "") for m in payload.get("models", []) if m.get("name")}


async def _pull_ollama_model(c: dict[str, Any]) -> None:
    model = c.get("llm_model")
    if not model or model == "none":
        raise LLMUnavailable("No Ollama model selected.")
    if model in LARGE_OLLAMA_MODELS and not c.get("allow_large_ollama_models"):
        raise LLMModelMissing(
            f"Ollama model '{model}' is not installed and large model auto-pull is blocked for MacBook/demo mode. "
            "Switch to 'gemma3:4b' or set ALLOW_LARGE_OLLAMA_MODELS=true deliberately."
        )
    if model not in SAFE_DEMO_OLLAMA_MODELS and not c.get("allow_large_ollama_models"):
        raise LLMModelMissing(
            f"Ollama model '{model}' is not installed and is not in the laptop-safe auto-pull allowlist. "
            "Use 'gemma3:4b' for the local Docker demo."
        )
    log.warning("Ollama model %s is missing; attempting one-time auto-pull because it is demo-safe.", model)
    # A model pull is large but must still be bounded — no infinite hang.
    pull_timeout = httpx.Timeout(connect=10.0, read=900.0, write=30.0, pool=10.0)
    async with httpx.AsyncClient(timeout=pull_timeout) as h:
        r = await h.post(f"{c['ollama_url']}/api/pull", json={"model": model, "stream": False})
        if r.status_code >= 400:
            detail = r.text[:400]
            raise LLMModelMissing(f"Failed to pull Ollama model '{model}': {detail}")


async def ensure_available(runtime: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return generation readiness details for UI/admin diagnostics."""
    c = _cfg(runtime)
    provider = c.get("llm_provider")
    model = c.get("llm_model")
    if provider == "none" or model == "none":
        return {"available": False, "provider": provider, "model": model, "reason": "Generation is disabled for this tenant."}
    if provider == "openai_compatible":
        ok = bool(c.get("openai_api_key")) or "localhost" in c.get("openai_base_url", "")
        return {"available": ok, "provider": provider, "model": c.get("openai_model") or model,
                "reason": None if ok else "OPENAI_API_KEY is not set."}
    if provider == "azure_foundry":
        ok = bool(c.get("azure_endpoint") and c.get("azure_deployment")
                  and c.get("azure_api_version") and c.get("azure_api_key"))
        return {"available": ok, "provider": provider, "model": c.get("azure_deployment") or model,
                "reason": None if ok else "Azure connector is missing endpoint, deployment, api_version, or api_key."}
    if provider == "bedrock":
        # Credential validity is only known on first call; treat a configured
        # connector as available so the UI does not hard-fail before use.
        return {"available": bool(model), "provider": provider, "model": model,
                "reason": None if model else "Bedrock connector has no model id."}
    if provider != "ollama":
        return {"available": False, "provider": provider, "model": model, "reason": f"Unsupported LLM provider: {provider}"}
    try:
        tags = await _ollama_tags(c)
        installed = bool(_name_variants(str(model)) & tags)
        if installed:
            return {"available": True, "provider": "ollama", "model": model, "installed_models": sorted(tags), "reason": None}
        if c.get("ollama_auto_pull_safe_models"):
            await _pull_ollama_model(c)
            tags = await _ollama_tags(c)
            installed = bool(_name_variants(str(model)) & tags)
            if installed:
                return {"available": True, "provider": "ollama", "model": model, "installed_models": sorted(tags), "reason": None}
        return {"available": False, "provider": "ollama", "model": model, "installed_models": sorted(tags),
                "reason": f"Ollama is running, but model '{model}' is not installed yet."}
    except Exception as exc:  # intentionally broad: this powers diagnostics
        return {"available": False, "provider": "ollama", "model": model, "reason": str(exc)}


async def is_available(runtime: dict[str, Any] | None = None) -> bool:
    return bool((await ensure_available(runtime)).get("available"))


async def _ensure_ollama_ready(c: dict[str, Any]) -> None:
    info = await ensure_available(c)
    if not info.get("available"):
        reason = info.get("reason") or "Ollama generation model is unavailable."
        raise LLMUnavailable(reason)


# ── Ollama ──────────────────────────────────────────────────────────

def _ollama_body(system: str, user: str, stream: bool, c: dict[str, Any]) -> dict:
    return {
        "model": c["llm_model"],
        "stream": stream,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "options": {
            "temperature": float(c.get("llm_temperature", 0.1)),
            "num_predict": int(c.get("llm_max_tokens", 900)),
        },
    }


async def _ollama(system: str, user: str, c: dict[str, Any]) -> str:
    await _ensure_ollama_ready(c)
    try:
        h = get_async_client()
        r = await h.post(f"{c['ollama_url']}/api/chat",
                         json=_ollama_body(system, user, stream=False, c=c),
                         timeout=int(c["llm_timeout_seconds"]))
        if r.status_code >= 400:
            raise LLMUnavailable(f"Ollama /api/chat failed: {r.status_code} {r.text[:400]}")
        data = r.json()
        return data["message"]["content"].strip()
    except LLMUnavailable:
        raise
    except (httpx.TimeoutException, httpx.HTTPError, KeyError, json.JSONDecodeError) as e:
        raise LLMUnavailable(f"Ollama generation failed for model '{c.get('llm_model')}': {e}") from e


async def _ollama_stream(system: str, user: str, c: dict[str, Any]) -> AsyncIterator[str]:
    await _ensure_ollama_ready(c)
    try:
        h = get_async_client()
        async with h.stream("POST", f"{c['ollama_url']}/api/chat",
                            json=_ollama_body(system, user, stream=True, c=c),
                            timeout=int(c["llm_timeout_seconds"])) as r:
            if r.status_code >= 400:
                detail = await r.aread()
                raise LLMUnavailable(f"Ollama /api/chat failed: {r.status_code} {detail.decode(errors='ignore')[:400]}")
            async for line in r.aiter_lines():
                if not line.strip():
                    continue
                data = json.loads(line)
                if data.get("error"):
                    raise LLMUnavailable(f"Ollama returned an error: {data['error']}")
                tok = data.get("message", {}).get("content", "")
                if tok:
                    yield tok
                if data.get("done"):
                    break
    except LLMUnavailable:
        raise
    except (httpx.TimeoutException, httpx.HTTPError, json.JSONDecodeError) as e:
        raise LLMUnavailable(f"Ollama streaming failed for model '{c.get('llm_model')}': {e}") from e


# ── OpenAI-compatible (also powers Azure AI Foundry) ────────────────

def _openai_headers(c: dict[str, Any]) -> dict:
    return {"Authorization": f"Bearer {c.get('openai_api_key','')}",
            "Content-Type": "application/json"}


def _azure_url(c: dict[str, Any], path: str) -> str:
    endpoint = str(c.get("azure_endpoint", "")).rstrip("/")
    deployment = c.get("azure_deployment", "")
    version = c.get("azure_api_version", "")
    if not (endpoint and deployment and version):
        raise LLMUnavailable("Azure AI Foundry connector is missing endpoint, deployment, or api_version.")
    return f"{endpoint}/openai/deployments/{deployment}/{path}?api-version={version}"


def _azure_headers(c: dict[str, Any]) -> dict:
    return {"api-key": c.get("azure_api_key", ""), "Content-Type": "application/json"}


def _openai_body(system: str, user: str, stream: bool, c: dict[str, Any]) -> dict:
    return {
        "model": c.get("openai_model") or c.get("llm_model"),
        "stream": stream,
        "temperature": float(c.get("llm_temperature", 0.1)),
        "max_tokens": int(c.get("llm_max_tokens", 900)),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }


async def _openai(system: str, user: str, c: dict[str, Any],
                  url: str | None = None, headers: dict | None = None) -> str:
    url = url or f"{c['openai_base_url']}/chat/completions"
    try:
        h = get_async_client()
        r = await h.post(url, headers=headers or _openai_headers(c),
                         json=_openai_body(system, user, stream=False, c=c),
                         timeout=int(c["llm_timeout_seconds"]))
        if r.status_code >= 400:
            raise LLMUnavailable(f"Chat completions failed: {r.status_code} {r.text[:400]}")
        return r.json()["choices"][0]["message"]["content"].strip()
    except LLMUnavailable:
        raise
    except (httpx.TimeoutException, httpx.HTTPError, KeyError, IndexError, json.JSONDecodeError) as e:
        raise LLMUnavailable(f"Chat completions generation failed: {e}") from e


async def _openai_stream(system: str, user: str, c: dict[str, Any],
                         url: str | None = None, headers: dict | None = None) -> AsyncIterator[str]:
    url = url or f"{c['openai_base_url']}/chat/completions"
    try:
        h = get_async_client()
        async with h.stream("POST", url, headers=headers or _openai_headers(c),
                            json=_openai_body(system, user, stream=True, c=c),
                            timeout=int(c["llm_timeout_seconds"])) as r:
            if r.status_code >= 400:
                detail = await r.aread()
                raise LLMUnavailable(f"Chat completions stream failed: {r.status_code} {detail.decode(errors='ignore')[:400]}")
            async for line in r.aiter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                delta = (json.loads(payload)["choices"][0]
                         .get("delta", {}).get("content"))
                if delta:
                    yield delta
    except LLMUnavailable:
        raise
    except (httpx.TimeoutException, httpx.HTTPError, json.JSONDecodeError, KeyError, IndexError) as e:
        raise LLMUnavailable(f"Chat completions streaming failed: {e}") from e


# ── AWS Bedrock (Converse API) ─────────────────────────────────────

def _bedrock_client(c: dict[str, Any]):
    try:
        import boto3  # noqa: PLC0415 — optional dependency, imported lazily
    except ImportError as e:  # pragma: no cover
        raise LLMUnavailable("boto3 is not installed; cannot use an AWS Bedrock connector.") from e
    region = c.get("aws_region") or "us-east-1"
    kwargs: dict[str, Any] = {"region_name": region}
    if c.get("aws_access_key_id") and c.get("aws_secret_access_key"):
        kwargs["aws_access_key_id"] = c["aws_access_key_id"]
        kwargs["aws_secret_access_key"] = c["aws_secret_access_key"]
        if c.get("aws_session_token"):
            kwargs["aws_session_token"] = c["aws_session_token"]
    return boto3.client("bedrock-runtime", **kwargs)


def _bedrock_converse_args(system: str, user: str, c: dict[str, Any]) -> dict:
    return {
        "modelId": c.get("llm_model"),
        "system": [{"text": system}],
        "messages": [{"role": "user", "content": [{"text": user}]}],
        "inferenceConfig": {
            "temperature": float(c.get("llm_temperature", 0.1)),
            "maxTokens": int(c.get("llm_max_tokens", 900)),
        },
    }


async def _bedrock(system: str, user: str, c: dict[str, Any]) -> str:
    def _call() -> str:
        client = _bedrock_client(c)
        resp = client.converse(**_bedrock_converse_args(system, user, c))
        parts = resp["output"]["message"]["content"]
        return "".join(p.get("text", "") for p in parts).strip()

    try:
        return await asyncio.to_thread(_call)
    except LLMUnavailable:
        raise
    except Exception as e:  # noqa: BLE001 — boto3 raises many client-error types
        raise LLMUnavailable(f"AWS Bedrock generation failed for '{c.get('llm_model')}': {e}") from e


async def _bedrock_stream(system: str, user: str, c: dict[str, Any]) -> AsyncIterator[str]:
    q: _queue.Queue = _queue.Queue()
    _SENTINEL = object()

    def _worker() -> None:
        try:
            client = _bedrock_client(c)
            resp = client.converse_stream(**_bedrock_converse_args(system, user, c))
            for event in resp["stream"]:
                delta = event.get("contentBlockDelta", {}).get("delta", {}).get("text")
                if delta:
                    q.put(delta)
        except Exception as e:  # noqa: BLE001
            q.put(LLMUnavailable(f"AWS Bedrock streaming failed for '{c.get('llm_model')}': {e}"))
        finally:
            q.put(_SENTINEL)

    threading.Thread(target=_worker, daemon=True).start()
    while True:
        item = await asyncio.to_thread(q.get)
        if item is _SENTINEL:
            break
        if isinstance(item, Exception):
            raise item
        yield item
