# KnowledgeDesk — Web client (Next.js)

A distributed frontend for the KnowledgeDesk FastAPI backend. Built with the
Next.js App Router (v15) + TypeScript. Every backend capability is wired up:

| Area | Backend router | UI |
| --- | --- | --- |
| Auth (login, refresh rotation, forced password change, logout) | `auth_routes` | `/login`, `/change-password`, `AuthProvider` |
| Ask with SSE token streaming, citations, feedback | `query` | `/ask` |
| Query history | `admin` | `/history` |
| Documents: upload, ZIP ingest, delete, sample seed | `documents`, `main` | `/documents` |
| Collections (derived) | `documents` | `/collections` |
| Insights: stats, gaps, readiness | `admin` | `/insights` |
| Users: create, role, enable/disable, reset password | `users` | `/users`, `/platform/users` |
| Audit log (workspace + platform) | `admin` | `/audit`, `/platform/audit` |
| Data connectors: Drive / SharePoint sync | `connectors` | `/connectors` |
| **Model connectors**: Bedrock / Azure Foundry / local, encrypted, test | `admin` (`/model-connectors`) | `/model-connectors` |
| **Settings**: profile, LLM/embedding connector selection, embedding lock, retrieval tuning | `admin` (`/settings`, `/config`) | `/settings` |
| Platform: tenants CRUD, platform stats | `admin` | `/platform/*` |
| Health (vector index + LLM status) | `main` | top bar |

## Architecture

```
src/
  app/                 route tree (App Router)
    (dashboard)/        authenticated shell: sidebar + top bar + role guard
    login, change-password
  lib/
    api/               one typed module per backend router
    auth/              token store (localStorage) + AuthProvider + useAuth
    types.ts           response shapes mirrored from the backend
  components/           Sidebar, TopBar, Modal, Toast, ConnectorModal, ui primitives
```

- The browser only ever calls same-origin `/api/*`. `next.config.mjs` rewrites
  those to `API_PROXY_TARGET` (the FastAPI service) — no CORS, no base URL in
  client code.
- Access + refresh tokens live in `localStorage`. `lib/api/client.ts`
  transparently rotates the refresh token on a 401 and retries once, else
  redirects to `/login`.
- Answer streaming reads the `text/event-stream` body frame-by-frame
  (`lib/api/query.ts#streamAsk`).

## Run

Everything is containerised — start the whole stack from the repo root:

```bash
docker compose up --build
```

- Web client: http://localhost:3000
- API + legacy static UI: http://localhost:8000

For local development against a running backend on :8000:

```bash
cd frontend
npm install
npm run dev        # http://localhost:3000
```

Set `API_PROXY_TARGET` if the backend is not on `http://127.0.0.1:8000`.
