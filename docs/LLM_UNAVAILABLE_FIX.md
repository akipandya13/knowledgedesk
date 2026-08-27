# Fix: “Direct excerpts — language model unavailable”

That message meant retrieval succeeded, but the configured generation model could not answer. In earlier builds this was too silent: the UI showed raw excerpts without telling the admin whether the tenant was in no-LLM mode, the selected Ollama model was missing, or the model timed out.

## What changed

- MacBook/demo safe mode now resets unsafe tenant profiles to `demo_fast` at startup.
- In laptop safe mode, saved tenant settings cannot persist large Ollama models such as `gemma3:12b`, `gemma3:27b`, `qwen3:14b`, etc. unless `ALLOW_LARGE_OLLAMA_MODELS=true` is set.
- The app now waits for `ollama-init` to finish pulling the default model before the web app starts.
- The default LLM timeout is increased to 300 seconds for first CPU generations.
- If Ollama is reachable but `gemma3:4b` is missing, the app can auto-pull it because it is the approved demo-safe model.
- If generation still fails, the UI shows the exact reason instead of only saying “language model unavailable”.

## Recommended MacBook Pro 16 GB settings

```text
Model Profile: Demo Fast / Laptop Safe
Embedding: sentence-transformers/all-MiniLM-L6-v2
Reranker: disabled
LLM: gemma3:4b
Retrieval Top K: 12
Context chars: 9000
Max tokens: 700–900
Temperature: 0.1
```

## When using larger models deliberately

Only do this on stronger hardware or after you have manually pulled the model:

```env
ALLOW_LARGE_OLLAMA_MODELS=true
ALLOW_RERANKER_MODELS=true
ALLOW_HEAVY_LOCAL_MODELS=true
```

Then restart and re-index documents if the embedding model changed.
