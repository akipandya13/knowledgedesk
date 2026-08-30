# Web client architecture

## What it does

A standalone Next.js 15 (App Router, React 19) front end that consumes the
FastAPI backend and is the only thing the browser talks to.

## How it works

- **Proxy** — `next.config` rewrites `/api/*` to the backend
  (`API_PROXY_TARGET`, baked at build time, `http://app:8000` in compose). The
  browser only ever hits `:3000`, so there is no CORS or base-URL config in the
  client.
- **Auth context** — `AuthProvider` holds the current user, hydrates from
  `localStorage` on load, revalidates via `/api/auth/me`, and exposes
  `signIn` / `signOut` / `refreshUser`.
- **API client** — `lib/api/client.ts` attaches the bearer token, transparently
  refreshes on `401`, and raises a typed `ApiError`. Feature modules
  (`lib/api/*.ts`) wrap each route group.
- **Layout** — `(dashboard)/layout.tsx` gates every page behind auth +
  [route permissions](40-navigation-and-route-guards.md); `Sidebar` and `TopBar`
  render the shell.
- **Deploy** — multi-stage Docker build producing the Next standalone server;
  runs as the `web` service alongside `app`, `qdrant`, `ollama`.

## Interfaces

The whole SPA under `/`, plus a history-mode fallback so deep links
(`/ask`, `/documents`, …) work on refresh.

## Configuration

`API_PROXY_TARGET` (build arg), `NODE_ENV`.

## Source

- [`frontend/src/lib/api/`](../../frontend/src/lib/api/), [`frontend/src/lib/auth/`](../../frontend/src/lib/auth/)
- [`frontend/src/app/(dashboard)/layout.tsx`](../../frontend/src/app/(dashboard)/layout.tsx)
- [`docker-compose.yml`](../../docker-compose.yml) — `web` service

## Related

[Navigation & route guards](40-navigation-and-route-guards.md) · [Authentication](01-authentication.md)
