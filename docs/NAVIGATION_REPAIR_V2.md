# Frontend navigation repair v2

This build hardens the single-page frontend navigation for Docker demos and reverse-proxy use.

## What changed

- Sidebar items are now real `<button>` controls instead of passive `div` elements.
- Every nav item has `data-page`, `aria-controls`, keyboard support, an inline click fallback, and a JavaScript event listener.
- A capture-phase delegated click handler catches clicks from SVGs/spans inside menu items.
- The router supports hash routes like `#documents` and direct routes like `/documents`.
- Added clickable pages for History, Collections, and Webhooks so the admin menu does not contain dead entries.
- Page data loading happens after visual page activation, so an API error cannot leave the UI stuck on the previous page.

## MacBook-safe demo pages

The MacBook-safe model defaults are unchanged: MiniLM embeddings, reranker disabled, and Gemma 3 4B via Ollama.
