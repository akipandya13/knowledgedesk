# KnowledgeDesk — Functionality Reference

One file per platform capability. Each page follows the same shape: **What it
does · How it works · Interfaces (API / UI) · Permissions · Configuration ·
Source · Related**.

Permissions are named from the RBAC model in
[`../RBAC_V1.md`](../RBAC_V1.md) / [`backend/app/rbac.py`](../../backend/app/rbac.py).

## Identity & access

| # | Capability |
|---|------------|
| 01 | [Authentication](01-authentication.md) |
| 02 | [Password management](02-password-management.md) |
| 43 | [Multi-factor authentication (TOTP)](43-multi-factor-authentication.md) |
| 44 | [Single sign-on (OIDC)](44-single-sign-on.md) — subscription-gated |
| 45 | [Session & API-key management](45-session-and-api-key-management.md) |
| 03 | [Roles & permissions (RBAC)](03-roles-and-permissions.md) |
| 42 | [Fine-grained access control](42-fine-grained-access.md) — custom roles, groups, grants, ACLs, clearance |
| 04 | [API keys / service accounts](04-api-keys-and-service-accounts.md) |
| 05 | [Multi-tenancy & workspaces](05-multi-tenancy-and-workspaces.md) |
| 06 | [User management](06-user-management.md) |

## Documents & ingestion

| # | Capability |
|---|------------|
| 07 | [Document upload](07-document-upload.md) |
| 08 | [Bulk ZIP ingestion](08-bulk-zip-ingestion.md) |
| 09 | [Document scope — personal vs company-wide](09-document-scope.md) |
| 10 | [Ingestion pipeline](10-ingestion-pipeline.md) |
| 11 | [File-format support](11-file-format-support.md) |
| 12 | [Document lifecycle & de-duplication](12-document-lifecycle.md) |

## Data connectors

| # | Capability |
|---|------------|
| 13 | [Google Drive connector](13-google-drive-connector.md) |
| 14 | [SharePoint / OneDrive connector](14-sharepoint-connector.md) |
| 15 | [Connector sync & run history](15-connector-sync-and-history.md) |

## Search & answers

| # | Capability |
|---|------------|
| 16 | [Ask — grounded answers with citations](16-ask-grounded-answers.md) |
| 17 | [Streaming answers (SSE)](17-streaming-answers.md) |
| 18 | [Semantic search](18-semantic-search.md) |
| 19 | [Search scope](19-search-scope.md) |
| 20 | [Retrieval & reranking pipeline](20-retrieval-and-reranking.md) |
| 21 | [Citations & grounding](21-citations-and-grounding.md) |
| 22 | [Answer feedback](22-answer-feedback.md) |
| 23 | [Knowledge gaps](23-knowledge-gaps.md) |
| 24 | [Extractive fallback](24-extractive-fallback.md) |

## Models & configuration

| # | Capability |
|---|------------|
| 25 | [Model profiles](25-model-profiles.md) |
| 26 | [Model connectors (LLM & embedding backends)](26-model-connectors.md) |
| 27 | [Workspace settings](27-workspace-settings.md) |
| 28 | [Embedding lock](28-embedding-lock.md) |
| 29 | [Laptop-safe mode & heavy-model guard](29-laptop-safe-mode.md) |
| 30 | [Credential encryption](30-credential-encryption.md) |
| 48 | [Secrets management](48-secrets-management.md) — pluggable secret sources for every subsystem |
| 47 | [Encryption at rest](47-encryption-at-rest.md) — envelope KEK/DEK, encrypted transcript + vectors |

## Analytics & operations

| # | Capability |
|---|------------|
| 31 | [Workspace insights](31-workspace-insights.md) |
| 32 | [Query history](32-query-history.md) |
| 33 | [Audit log](33-audit-log.md) — tamper-evident, hash-chained, filterable, CSV export |
| 50 | [User activity tracking](50-user-activity-tracking.md) — behavioural stream, per-user timeline, self-service view |
| 49 | [Security event logging](49-security-event-logging.md) — audit + SIEM stream, authz denials, pw expiry |
| 34 | [Platform administration](34-platform-administration.md) |
| 35 | [Collections view](35-collections-view.md) |
| 36 | [Enterprise readiness view](36-enterprise-readiness.md) |
| 37 | [Health check](37-health-check.md) — liveness / readiness / dependency probes |
| 38 | [Demo seed](38-demo-seed.md) |
| 41 | [Observability](41-observability.md) — metrics, events, traces; pluggable sinks |
| 51 | [Application logging](51-application-logging.md) — structured JSON logs, correlation ids, error handler, centralized collection (Postgres/Mongo) |
| 52 | [Resilience & recovery](52-resilience-and-recovery.md) — timeouts, retries, idempotency, startup reconciler, error isolation |
| 53 | [Backup & restore](53-backup-and-restore.md) — consistent DB + keys + Qdrant snapshots |

## Architecture

| # | Capability |
|---|------------|
| 39 | [Web client architecture](39-web-client-architecture.md) |
| 40 | [Navigation & route guards](40-navigation-and-route-guards.md) |
| 46 | [TLS & reverse proxy](46-tls-and-reverse-proxy.md) — HTTPS termination, HSTS, forwarded headers |
