# TLS / encryption in transit

The stack terminates TLS at a **Caddy** reverse proxy — the only service that
should face the internet. It proxies to the `app` (FastAPI) and `web` (Next.js)
containers over the private Docker network.

```
            :443 (HTTPS, HSTS)          private network
browser ───────────────► Caddy ──┬──► app:8000    (/api/*, /metrics, /docs)
            :80 → 308 redirect     └──► web:3000    (everything else)
```

## Quick start

```bash
cp .env.example .env          # KD_DOMAIN=localhost by default
docker compose up -d --build

# trust Caddy's local CA so the browser stops warning (localhost only):
docker compose exec caddy caddy trust        # macOS/Linux host
open https://localhost
```

`app` and `web` are also published on `127.0.0.1:8000` / `:3000` for local
development. Remove those `ports:` blocks for a hardened deployment so nothing
bypasses TLS.

## Production

1. Point a real DNS record at the host and open ports **80 + 443**.
2. In `.env`:
   ```
   KD_DOMAIN=knowledge.acme.com
   KD_TLS_EMAIL=ops@acme.com
   PUBLIC_BASE_URL=https://knowledge.acme.com
   TRUSTED_HOSTS=knowledge.acme.com
   CORS_ALLOW_ORIGINS=https://knowledge.acme.com
   # optional, if the app is ever reachable without the proxy:
   FORCE_HTTPS_REDIRECT=true
   ```
3. `docker compose up -d`. Caddy obtains and renews a Let's Encrypt certificate
   automatically; HSTS, `X-Frame-Options`, `X-Content-Type-Options` and
   `Referrer-Policy` are set on every response.

`PUBLIC_BASE_URL` is what the app uses to build the **SSO redirect URI**
(`<PUBLIC_BASE_URL>/api/auth/sso/callback` — register this with the IdP) and the
links in verification / password-reset emails. Set it whenever the app is behind
a proxy.

## How the app trusts the proxy

`uvicorn` runs with `--proxy-headers --forwarded-allow-ips=*`, so
`X-Forwarded-Proto` / `X-Forwarded-For` from Caddy are honoured:
`request.url.scheme` is `https`, `Secure` cookies work, and `_client_ip()` sees
the real client. This is only safe because `:8000` is not publicly reachable —
keep it that way (or set `--forwarded-allow-ips` to Caddy's IP).

Optional in-app middleware (usually unnecessary behind Caddy):
`TRUSTED_HOSTS` (Host allow-list), `FORCE_HTTPS_REDIRECT` (in-app 308).

## Internal legs

`app → qdrant:6333` and `app → ollama:11434` are plain HTTP on the private
Docker network. For defence-in-depth, enable Qdrant TLS + API key
(`QDRANT_URL=https://…`, mount certs) and run Ollama behind its own TLS proxy;
outbound calls to IdPs, model providers and HIBP are already HTTPS.

## Files

- [`Caddyfile`](../Caddyfile), [`docker-compose.yml`](../docker-compose.yml) (`caddy` service)
- [`backend/Dockerfile`](../backend/Dockerfile) — uvicorn proxy flags
- [`backend/app/main.py`](../backend/app/main.py) — `TrustedHostMiddleware` / `HTTPSRedirectMiddleware`
- [`backend/app/config.py`](../backend/app/config.py) — `public_base_url`, `trusted_hosts`, `force_https_redirect`, `app_base_url`
