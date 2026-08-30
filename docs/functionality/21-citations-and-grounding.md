# Citations & grounding

## What it does

Keeps answers tied to source documents: the model is told to use only the
provided context and to cite it inline as `[1]`, `[2]`, matching numbered
passages the UI renders as expandable source chips.

## How it works

- `_build_prompts()` composes a system prompt for
  `"<app>, the internal knowledge assistant for <tenant>"` with three toggles:
  - **Refusal** — "if the context doesn't contain the answer, say you don't
    know; never invent" (`ANSWER_REFUSE_OUTSIDE_KNOWLEDGE`).
  - **Citations** — "cite sources inline as [1], [2] matching the numbered
    context blocks" (`ANSWER_INCLUDE_CITATIONS`).
  - **Language** — answer in `ANSWER_LANGUAGE` (`auto` = match the question).
- The user message is `Context from company documents:\n\n[1] (Source: file.pdf,
  page 3)\n<text>\n\n[2] ...\n\nQuestion: <q>`.
- The response's `sources[]` array carries `{n, filename, page, score,
  rerank_score?, snippet}`; the UI shows `[n] filename · p.N` chips that expand
  to the snippet.
- `confidence` = the rerank score of the top hit, or its vector score if no
  reranking.

## Interfaces

Part of every [Ask](16-ask-grounded-answers.md) /
[stream](17-streaming-answers.md) response and the `meta` event.

## Configuration

`ANSWER_INCLUDE_CITATIONS`, `ANSWER_REFUSE_OUTSIDE_KNOWLEDGE`, `ANSWER_LANGUAGE`.

## Source

- [`backend/app/services/rag.py`](../../backend/app/services/rag.py) — `_build_prompts`, `_sources`
- [`frontend/src/app/(dashboard)/ask/page.tsx`](../../frontend/src/app/(dashboard)/ask/page.tsx) — `SourceChip`

## Related

[Ask — grounded answers](16-ask-grounded-answers.md) · [Extractive fallback](24-extractive-fallback.md)
