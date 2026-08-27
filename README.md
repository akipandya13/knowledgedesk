# KnowledgeDesk v1

## MacBook Pro 16 GB / demo-safe model settings

This build is safe for a 16 GB MacBook Pro by default. The default profile is `demo_fast`:

- Embedding: `sentence-transformers/all-MiniLM-L6-v2`
- Generation: `gemma3:4b` through Ollama
- Reranker: disabled

Important: rerankers such as `BAAI/bge-reranker-base` are useful for production quality, but they still download and load a CrossEncoder model on the first question. On a 16 GB MacBook, keep:

```env
LAPTOP_SAFE_MODE=true
ALLOW_RERANKER_MODELS=false
ALLOW_HEAVY_LOCAL_MODELS=false
MODEL_PROFILE=demo_fast
RERANKER_ENABLED=false
RERANKER_MODEL=
```

To enable reranking later on stronger hardware, set `ALLOW_RERANKER_MODELS=true`, restart, and re-test latency before a customer demo.

If you previously selected an enterprise or premium profile, this build automatically disables stale reranker settings on startup when laptop-safe mode is enabled.


**Semantic internal search for enterprises.** Upload (or sync) all company documents to a private tenant, then ask anything in plain language and get a cited answer — running entirely on the customer's own infrastructure, with **zero LLM API cost** by default.

```
Browser UI ──► FastAPI ──► Qdrant (vectors, per-tenant + per-embedding collection)
                  │
                  ├──► Tenant-selectable embeddings: Qwen3 / BGE-M3 / Jina / MiniLM
                  ├──► Optional reranker: Qwen3 / BGE rerankers
                  ├──► Tenant-selectable LLM: Gemma 3 27B/12B/4B, Qwen, Mistral, Llama via Ollama
                  └──► SQLite (tenants, users, documents, query analytics, tenant settings)
Connectors: Google Drive · SharePoint (Microsoft Graph) · ZIP ingest · drag-and-drop upload
```

---

## Demo tomorrow — 3 commands

Requires Docker Desktop (or docker + compose plugin). The default is now `demo_fast`, which uses MiniLM embeddings and `gemma3:4b` so the demo does not silently pull Qwen 4B or other multi-GB Hugging Face models during a query. Premium models remain available in Settings for GPU-backed deployments.

```bash
cd knowledgedesk
docker compose up -d --build        # first build downloads CPU torch + Gemma 3 4B
# watch the model download finish:
docker logs -f kd-ollama-init       # wait for "Model ready."
```

Open **http://localhost:8000** and sign in with one of the demo accounts below.

## Default users and passwords

These are created automatically on first startup when the `app_data` Docker volume is empty. They are also listed in `DEFAULT_USERS_AND_PASSWORDS.md`.

| Role | Email / Key | Password | Notes |
|---|---|---|---|
| Platform superadmin | `superadmin@knowledgedesk.local` | `ChangeMe!Now1` | Forced password change on first login. Manages workspaces/platform only; no tenant document access. |
| Demo tenant admin | `admin@demo.knowledgedesk.local` | `Demo-Admin123!` | Upload documents, manage users, view audit, configure connectors, and change per-tenant models. |
| Demo employee/member | `employee@demo.knowledgedesk.local` | `Demo-User123!` | Ask questions, view documents and insights. |
| Demo service API key | `kd-demo-key` | N/A | Use as `X-API-Key: kd-demo-key` for API demos. |
| Legacy platform admin API key | `kd-admin-key` | N/A | Legacy script compatibility only; prefer superadmin login. |

Change these before real deployment. If Docker volumes already exist, `.env` changes will not rewrite existing users.

### The 5-minute demo script

1. **Documents tab → "Load sample documents".** Four realistic company policies (HR, Finance, Refund/SLA, IT Security) index in ~10 seconds. Watch status flip `queued → processing → ready`.
2. **Ask tab.** Click a suggested question — *"What is the refund policy for enterprise clients?"* The answer streams in live with `[1]` citations; click a source tab to see the exact passage and page.
3. **Ask something that isn't in the docs** — *"What is our policy on company cars?"* It honestly says it doesn't know instead of hallucinating.
4. **Insights tab.** That unanswered question now appears under **Knowledge gaps** — show the buyer this is how they discover missing documentation. Stats, latency, and feedback are all live.
5. **The closer:** "Drop *your* documents in" — drag in any PDF/DOCX of theirs and ask about it on the spot. (This is the 48-hour pilot pitch from the GTM plan, compressed to 30 seconds.)

API docs are auto-generated at **http://localhost:8000/docs**.

> **Need better quality?** In Settings choose `enterprise_balanced` after the demo is running, then re-seed/re-upload documents. For Qwen 4B premium embeddings/rerankers, set `ALLOW_HEAVY_LOCAL_MODELS=true` and `HF_TOKEN` in `.env`, use GPU hardware, restart, then re-index documents.

---

## What's in v1 (beyond an MVP)

| Capability | Detail |
|---|---|
| **Cited Q&A** | Streaming answers (SSE) grounded only in retrieved chunks; inline `[n]` citations with file + page; honest "not found" below a confidence threshold |
| **Multi-format ingestion** | PDF, DOCX, PPTX, XLSX, CSV, TXT, MD, HTML, JSON — drag-and-drop, multi-file, background indexing with live status |
| **Mass-ingestion connectors** | Google Drive folder sync (exports native Docs/Sheets/Slides) and SharePoint via Microsoft Graph — set credentials in `.env`, click Sync |
| **Multi-tenant SaaS core** | One Qdrant collection per tenant and embedding model (hard isolation + safe model upgrades), per-tenant API keys, tenant CRUD, per-tenant setting overrides |
| **Per-tenant model selection** | Tenant admins can choose model profile, embedding model, reranker, generation model and retrieval settings from a dropdown UI |
| **Reranking layer** | Optional cross-encoder reranker improves final context quality before the LLM sees the answer evidence |
| **Admin analytics** | Documents/chunks indexed, questions asked vs answered, **knowledge gaps** (unanswerable questions), latency, 👍/👎 feedback rates, query log |
| **Cost control** | Local Gemma 3 + local embeddings = ₹0 per query. One env var switches to OpenAI/Groq/Together/vLLM if a client wants higher quality |
| **Degradation safety** | LLM down? Answers fall back to extractive passages — the demo never dies |
| **Raw semantic search** | `/api/query/search` returns ranked passages with no LLM (instant, free) |

## Everything is configurable — nothing needs configuring

All knobs live in **`.env`** with working defaults. The ones buyers ask about:

| Setting | Default | Why you'd change it |
|---|---|---|
| `LLM_PROVIDER` | `ollama` | `openai_compatible` for hosted models, `none` for pure extractive search |
| `MODEL_PROFILE` | `demo_fast` | `enterprise_balanced` for stronger production retrieval, `premium_best` for GPU quality, `extractive_zero_llm` for no generation model |
| `LLM_MODEL` | `gemma3:4b` | `gemma3:12b` for balanced quality, `gemma3:27b` for GPU quality — any Ollama model |
| `OPENAI_BASE_URL` | OpenAI | Point at Groq/Together/vLLM — anything speaking `/v1/chat/completions` |
| `EMBEDDING_PROVIDER` | `local` | `openai` for text-embedding-3-small or local BGE/Qwen/Jina embeddings |
| `EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | `BAAI/bge-m3` for enterprise quality; `Qwen/Qwen3-Embedding-4B` for premium GPU quality |
| `RERANKER_ENABLED` / `RERANKER_MODEL` | `false` / `BAAI/bge-reranker-base` | Enable BGE/Qwen rerankers for better document relevance on larger hosts |
| `RETRIEVAL_TOP_K` | 12 | First-stage vector retrieval pool before reranking |
| `RERANK_TOP_K` | 8 | Final chunks sent to the answer prompt |
| `RETRIEVAL_SCORE_THRESHOLD` | 0.28 | Raise → stricter "I don't know"; lower → more attempted answers |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | 1100 / 180 | Tune for very long contracts vs short FAQs |
| `ANSWER_LANGUAGE` | `auto` | Force `English`, `Hindi`, `Gujarati`, … |
| `ADMIN_API_KEY`, `DEMO_TENANT_API_KEY` | demo values | **Change before any real deployment** |

Per-tenant overrides now live in the tenant admin **Settings** page. A workspace admin can choose `premium_best`, `enterprise_balanced`, `multilingual_efficient`, `demo_fast`, or `extractive_zero_llm`, then override individual models if needed. The same settings are available through `PUT /api/admin/settings`; `X-API-Key` is the canonical service header and `X-Tenant-Key` is still accepted for older demo scripts.

> When changing the embedding model, re-upload or re-seed documents. KnowledgeDesk creates model-versioned Qdrant collections so incompatible vectors are never mixed.

## Heavy model safety guard

The admin dropdown includes best-quality models such as `Qwen/Qwen3-Embedding-4B` and `Qwen/Qwen3-Reranker-4B`, but the Docker demo blocks them by default to avoid the log pattern where the first query starts downloading large safetensor shards on CPU.

```env
ALLOW_HEAVY_LOCAL_MODELS=false
AUTO_DOWNGRADE_BLOCKED_MODELS=true
HF_TOKEN=
```

With these defaults, any existing tenant saved with Qwen 4B embedding/reranker is reset to `demo_fast` on startup. To intentionally use the premium profile, set `ALLOW_HEAVY_LOCAL_MODELS=true`, add `HF_TOKEN`, run on GPU hardware, and re-index documents after the model change.


## API in 30 seconds

```bash
K='X-API-Key: kd-demo-key'
curl -s -H "$K" -X POST localhost:8000/api/demo/seed                       # load samples
curl -s -H "$K" localhost:8000/api/documents | jq                          # index status
curl -s -H "$K" -H 'Content-Type: application/json' \
  -d '{"question":"Who approves expenses above ₹50,000?"}' \
  localhost:8000/api/query/ask | jq .answer,.sources                       # cited answer
curl -s -H "$K" localhost:8000/api/admin/stats | jq                        # analytics

# New customer tenant (platform admin):
# Login as the demo tenant admin to get a JWT:
curl -s -H 'Content-Type: application/json' \
  -d '{"email":"admin@demo.knowledgedesk.local","password":"Demo-Admin123!"}' \
  localhost:8000/api/auth/login | jq

# Model catalog for the tenant-admin dropdown:
curl -s -H "$K" localhost:8000/api/admin/model-catalog | jq
```

## Connector setup (when a pilot wants mass ingestion)

**Google Drive** — fastest path for a demo: open https://developers.google.com/oauthplayground, authorize `https://www.googleapis.com/auth/drive.readonly`, copy the access token into `GDRIVE_ACCESS_TOKEN`, put the folder's ID (from its URL) in `GDRIVE_FOLDER_ID`, restart, click **Sync Google Drive**. (Access tokens expire in ~1 h — fine for demos; a pilot gets a service account.)

**SharePoint** — register an Azure AD app with `Sites.Read.All` application permission, grant admin consent, fill the four `MSGRAPH_*` values, restart, click **Sync SharePoint**.

## Scaling notes (the questions a 1,000-employee CTO will ask)

- **Data isolation:** per-tenant + per-embedding Qdrant collections + per-tenant API keys; nothing leaves their cloud — the whole stack is three containers on their Azure/AWS/GCP VM.
- **Model upgrades:** changing embeddings creates a new vector collection and the UI warns when reindexing is required.
- **Volume:** `demo_fast` indexes fastest on CPU; `enterprise_balanced` and `premium_best` are quality-first and should use GPU-backed hosts for large corpora.
- **Concurrency:** Gemma 3 12B/27B should run on GPU for real pilots; for >20 concurrent users, give Ollama/vLLM a GPU or point `LLM_PROVIDER=openai_compatible` at a hosted inference endpoint.
- **Permissions (roadmap → v1.1):** today access control is at tenant level; document-level ACL mapping from Drive/SharePoint permissions is the next milestone, and the payload schema already carries `doc_id` to filter on.

## Project layout

```
knowledgedesk/
├── docker-compose.yml        # app + qdrant + ollama (+ one-shot model pull)
├── .env                      # ALL configuration, demo-ready defaults
├── sample_docs/              # 4 realistic policies for instant demos
└── backend/
    ├── Dockerfile            # CPU torch, embedding model pre-baked (offline-safe)
    ├── static/index.html     # full UI: ask / documents / insights
    └── app/
        ├── main.py           # startup, health, demo seeding
        ├── config.py         # every setting, typed, env-driven
        ├── model_catalog.py  # tenant dropdown model profiles/options
        ├── tenant_settings.py# effective per-tenant model configuration
        ├── database.py       # SQLite: tenants, users, documents, query log
        ├── auth.py           # tenant keys + admin key
        ├── routers/          # documents, query, admin, connectors
        └── services/         # parsers, chunking, embeddings, vectorstore,
                              # llm (ollama/openai/none), rag, ingestion,
                              # connectors/ (gdrive, sharepoint)
```

---


### Frontend routes fixed in this build

The UI now supports real browser URLs for all pages, so refreshes and direct links work:
`/ask`, `/documents`, `/insights`, `/users`, `/audit`, `/connectors`, `/settings`, `/change-password`, and `/platform/*`.
FastAPI serves the same SPA shell for those routes while preserving all `/api/*` endpoints.

## v1 enterprise upgrade notes in this ZIP

This build enhances the earlier POC/MVP into a more sellable v1 demo for enterprise buyers:

- Bulk ZIP ingestion endpoint: `POST /api/documents/upload-zip`
- Upload metadata: `department`, `confidentiality`, `tags`
- SHA-256 duplicate detection per tenant
- Soft-delete of documents while removing vectors from Qdrant
- Metadata-aware Qdrant payloads
- Filtered retrieval/answering via `filters.doc_ids`, `filters.source`, `filters.filename`
- Tenant readiness endpoint: `GET /api/admin/readiness`
- Tenant-admin model dropdowns for embedding, reranker, generation model and quality/cost profile
- Model-versioned Qdrant collections to safely switch embeddings per tenant
- Optional reranker layer before answer generation
- Backward-compatible SQLite column migration for existing demo volumes
- Added `docs/FUNCTIONALITIES_V1.md` as a buyer-facing functionality and implementation list
- Added `scripts/demo_seed_zip.sh` to create a ZIP from sample documents for a bulk-ingestion demo

### Example filtered question

```bash
curl -X POST http://localhost:8000/api/query/ask \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: kd-demo-key' \
  -d '{
    "question": "What is the refund SLA?",
    "filters": {"source": "seed"}
  }'
```

### Example ZIP ingestion

```bash
./scripts/demo_seed_zip.sh
curl -X POST http://localhost:8000/api/documents/upload-zip \
  -H 'X-API-Key: kd-demo-key' \
  -F 'archive=@/tmp/knowledgedesk-sample-docs.zip' \
  -F 'department=Company Ops' \
  -F 'confidentiality=internal' \
  -F 'tags=demo,policies'
```


### MacBook note: generated answers vs direct excerpts

If you see “AI generation is currently unavailable” or older text like “Direct excerpts — language model unavailable”, retrieval is working but Ollama generation is not ready for the selected tenant model. This build defaults to `gemma3:4b`, waits for the model pull before starting the app, and blocks larger tenant LLM settings in `LAPTOP_SAFE_MODE`. See `docs/LLM_UNAVAILABLE_FIX.md`.


## Frontend navigation fix

This build includes hardened sidebar navigation for Ask, History, Documents, Collections, Insights, Users, Webhooks, Audit log, Connectors, Settings, and Change password. See `docs/NAVIGATION_REPAIR_V2.md`.
