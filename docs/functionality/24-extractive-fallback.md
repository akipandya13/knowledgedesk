# Extractive fallback

## What it does

Keeps the product useful when generation is unavailable or disabled: instead of
failing, it returns the top cited excerpts.

## How it works

- Two triggers:
  - **`llm_provider = none`** (the *Zero LLM Cost / Extractive* profile) — no
    generation model is configured at all.
  - **LLM unavailable at query time** — Ollama model missing, remote endpoint
    down, timeout — and `LLM_FALLBACK_TO_EXTRACTIVE` is true.
- `_extractive_answer()` returns the top ~3 retrieved passages, numbered `[1..3]`
  with a short note explaining generation is off. `mode` is `llm_unavailable`
  (or `model_blocked` when the embedding model itself is blocked by safe mode).
- In streaming, a `status` event announces the fallback before the excerpt tokens.
- If `LLM_FALLBACK_TO_EXTRACTIVE` is false, generation failure surfaces as an
  `error` instead.

## Interfaces

Automatic within [Ask](16-ask-grounded-answers.md) /
[stream](17-streaming-answers.md). The *Zero LLM* [profile](25-model-profiles.md)
makes it the permanent behaviour for a workspace.

## Configuration

`LLM_FALLBACK_TO_EXTRACTIVE` (default true), `LLM_PROVIDER=none`.

## Source

- [`backend/app/services/rag.py`](../../backend/app/services/rag.py) — `_extractive_answer`, `_blocked_model_answer`
- [`backend/app/services/llm.py`](../../backend/app/services/llm.py) — `LLMUnavailable`

## Related

[Model profiles](25-model-profiles.md) · [Laptop-safe mode](29-laptop-safe-mode.md)
