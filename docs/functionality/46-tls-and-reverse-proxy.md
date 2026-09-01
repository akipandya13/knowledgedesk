# TLS & reverse proxy (encryption in transit)

## What it does

Terminates HTTPS at a Caddy reverse proxy and routes to the app / web
containers over the private network. Adds HSTS + hardening headers and an
HTTP→HTTPS redirect. The app trusts the proxy's forwarded headers so schemes,
client IPs and Secure cookies are correct.

## How it works

- **Caddy** (`caddy` compose service, `:80` + `:443`) — automatic certificates:
  Let's Encrypt for a real `KD_DOMAIN`, Caddy's local CA for `localhost`.
  `Caddyfile` routes `/api/*`, `/metrics`, `/docs` → `app:8000`; everything else
  → `web:3000`. Sends `Strict-Transport-Security`, `X-Frame-Options`,
  `X-Content-Type-Options`, `Referrer-Policy`; strips `Server`.
- `app` / `web` ports are bound to `127.0.0.1` (dev convenience) — remove for a
  hardened deploy so all traffic goes through TLS.
- **uvicorn** runs `--proxy-headers --forwarded-allow-ips=*` → `request.url.scheme`
  is `https`, `_client_ip()` sees the real client, `Secure` cookies work.
- **Config**: `PUBLIC_BASE_URL` (SSO redirect URI + email links),
  `TRUSTED_HOSTS` (`TrustedHostMiddleware`), `FORCE_HTTPS_REDIRECT`
  (`HTTPSRedirectMiddleware`, off by default — Caddy handles it).
- **Not yet encrypted**: `app→qdrant`, `app→ollama` (private Docker network).
  Outbound to IdPs / model providers / HIBP is already HTTPS.

## Interfaces

Operational — no API. `https://<KD_DOMAIN>/` (web), `https://<KD_DOMAIN>/api/…`.

## Configuration

`KD_DOMAIN`, `KD_TLS_EMAIL`, `PUBLIC_BASE_URL`, `TRUSTED_HOSTS`,
`FORCE_HTTPS_REDIRECT`. Full guide: [`../DEPLOYMENT_TLS.md`](../DEPLOYMENT_TLS.md).

## Source

- [`Caddyfile`](../../Caddyfile), [`docker-compose.yml`](../../docker-compose.yml)
- [`backend/Dockerfile`](../../backend/Dockerfile), [`backend/app/main.py`](../../backend/app/main.py), [`backend/app/config.py`](../../backend/app/config.py)

## Related

[Authentication](01-authentication.md) · [Session & API-key management](45-session-and-api-key-management.md) ·
[Web client architecture](39-web-client-architecture.md)
