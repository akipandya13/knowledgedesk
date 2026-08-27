# KnowledgeDesk v1 — sellable enterprise functionality list

KnowledgeDesk v1 is a tenant-isolated, Dockerized RAG knowledge assistant for enterprises that want an AI interpretation layer over internal documents without committing to high LLM spend.

## Core v1 capabilities

| Area | Functionality | Implementation in this package |
|---|---|---|
| Multi-tenancy | One tenant can upload/query only its own knowledge | SQLite tenant metadata + Qdrant collection per tenant and embedding model (`kd_<tenant>_<provider>_<model>`) |
| Authentication | Superadmin, tenant admin, member, service/API-key access | JWT auth, refresh tokens, password lockout, forced first password change |
| Document ingestion | Upload many docs from UI/API | `/api/documents/upload` with background ingestion |
| Bulk ingestion | Upload a ZIP export from Drive/SharePoint/local folder | `/api/documents/upload-zip`, recursive ZIP traversal, duplicate rejection |
| File support | PDF, DOCX, PPTX, XLSX, CSV, TXT, Markdown, HTML, JSON, LOG | Lightweight parsers in `backend/app/services/parsers.py` |
| Metadata | Department, confidentiality, tags, source, hash, version | Stored in SQLite and vector payloads |
| Duplicate control | Avoid billing/embedding same file twice | SHA-256 content hash per tenant |
| Retrieval | High-quality semantic search | Tenant-selectable embeddings: Qwen3, BGE-M3, Jina, MxBai, Nomic, MiniLM + Qdrant cosine search |
| Reranking | Improve final evidence quality before generation | Optional tenant-selectable reranker: Qwen3 or BGE rerankers |
| RAG answers | Grounded answers with citations | Retrieved chunks converted to numbered context; model cites `[1]`, `[2]` |
| Filtered questions | Ask only against a document/source/filename | `filters` in `/api/query/ask` and `/api/query/search` |
| Local generation default | Local Ollama Gemma model | `MODEL_PROFILE=enterprise_balanced`, `LLM_MODEL=gemma3:12b`; premium `gemma3:27b`; fast `gemma3:4b` |
| Fallback mode | Demo still works if LLM is down | Extractive answer fallback from top passages |
| Admin analytics | Usage, knowledge gaps, document state, feedback | `/api/admin/stats`, `/api/admin/gaps`, `/api/admin/queries` |
| Enterprise readiness | Demo checklist for buyer conversations | `/api/admin/readiness` |
| Auditability | Security and admin actions logged | `AuditLog` table + tenant/platform audit endpoints |
| Configurability | Tenant-level retrieval/model overrides | Tenant admin Settings dropdown + `/api/admin/settings`; `.env` for global defaults |
| Connectors | Google Drive and SharePoint connector skeletons | `services/connectors/gdrive.py`, `sharepoint.py` |
| Deployment | Demo tomorrow with one command | `docker compose up --build` |

## Functionalities to pitch to a 1,000-employee company

1. **Private tenant workspace**: every company gets isolated users, documents, vectors, settings, and audit trail.
2. **Upload all company documents**: upload files directly, seed sample docs, or import ZIP exports from existing repositories.
3. **Ask any policy/process question**: employees receive direct answers with cited source snippets.
4. **Source-grounded trust layer**: every answer returns confidence and document/page citations.
5. **Knowledge gap detection**: unanswered questions become a backlog for documentation teams.
6. **Admin cockpit**: track readiness, total documents, chunks, query volume, failed ingestions, gaps, feedback, and latency.
7. **Configurable AI cost profile**: tenant admins can choose `premium_best`, `enterprise_balanced`, `multilingual_efficient`, `demo_fast`, or `extractive_zero_llm`.
8. **Model tuning per tenant**: tune embedding model, reranker, generation model, top-k, rerank-k, threshold, context and token limits without code changes.
9. **Security-ready baseline**: roles, service API keys, password policy, lockout, JWT, refresh token revocation, soft document delete.
10. **Connector path for enterprise sale**: Drive and SharePoint integrations are scaffolded for production OAuth/client credential setup.

## Recommended demo flow

1. `docker compose up --build`
2. Open `http://localhost:8000`
3. Login with `admin@demo.knowledgedesk.local` / `Demo-Admin123!`
4. Seed sample docs or upload `sample_docs` as a ZIP.
5. Ask: `What is the refund SLA?`, `What is the laptop reimbursement limit?`, `What are the password requirements?`
6. Show citations, source snippets, analytics, and readiness endpoint.

## Production hardening backlog

- Replace permissive demo CORS with company domains.
- Add SSO/SAML/OIDC.
- Add row-level ACLs for departments/confidentiality.
- Add OCR for scanned PDFs.
- Add background worker queue such as Celery/RQ for massive ingestion.
- Add scheduled SharePoint/Drive sync with delta tokens.
- Add KMS/secret manager integration and encrypted object storage.
- Add evaluation set and hallucination regression tests.

## Added in model-selection update

- `backend/app/model_catalog.py`: curated model profile and dropdown options.
- `backend/app/tenant_settings.py`: global defaults + selected profile + tenant overrides.
- `GET /api/admin/model-catalog`: feeds the tenant-admin dropdowns.
- `GET /api/admin/config`: returns effective tenant configuration and reindex warning status.
- `PUT /api/admin/settings`: stores per-tenant model settings.
- Model-versioned Qdrant collections prevent incompatible embedding vectors from being mixed.
- `DEFAULT_USERS_AND_PASSWORDS.md`: all demo users, passwords and keys.
