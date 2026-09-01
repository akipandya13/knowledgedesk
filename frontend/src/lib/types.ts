// Shared response shapes mirrored from the FastAPI backend (backend/app/routers).

export type Role = "member" | "tenant_admin" | "superadmin" | "service";

/** Capability strings — mirror of backend/app/rbac.py (Permission). */
export type Permission =
  | "query.run"
  | "feedback.write"
  | "document.read"
  | "document.write.workspace"
  | "document.write.tenant"
  | "document.delete"
  | "insights.read"
  | "settings.read"
  | "settings.write"
  | "model_connector.manage"
  | "data_connector.manage"
  | "audit.read"
  | "observability.read"
  | "access.manage"
  | "user.manage"
  | "tenant.manage"
  | "platform.read";

/** How a document is stored. */
export type DocScope = "tenant" | "workspace";
/** Where an Ask/Search request should look. */
export type SearchScope = "workspace" | "company" | "all";

export interface TenantRef {
  slug: string;
  name: string;
}

export interface CurrentUser {
  id: number | null;
  email: string;
  full_name?: string;
  role: Role;
  tenant: TenantRef | null;
  force_password_change: boolean;
  mfa_enabled?: boolean;
  email_verified?: boolean;
  auth_provider?: string;
}

export type LoginResult = TokenPair | { mfa_required: true; mfa_token: string };

export interface AuthSession {
  id: number;
  user_agent: string;
  ip: string;
  label: string;
  current: boolean;
  session_started_at: string | null;
  created_at: string | null;
  last_used_at: string | null;
}

export interface AuthPolicy {
  mfa_required: boolean;
  require_verified_email: boolean;
  entitlements: Record<string, boolean>;
}

export interface ApiKeyRow {
  id: number;
  name: string;
  prefix: string;
  expires_at: string | null;
  last_used_at: string | null;
  revoked: boolean;
  created_at: string | null;
}

export interface SsoConfig {
  configured: boolean;
  entitled: boolean;
  display_name?: string;
  issuer?: string;
  client_id?: string;
  client_secret_set?: boolean;
  allowed_domains?: string[];
  default_role?: string;
  is_active?: boolean;
  callback_url?: string;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  user: CurrentUser;
}

export interface HealthStatus {
  app: string;
  qdrant: string;
  llm: string;
  llm_provider: string;
  llm_model: string;
  environment: string;
}

export interface DocumentRow {
  id: number;
  filename: string;
  source: string;
  status: "queued" | "processing" | "ready" | "failed" | "deleted";
  error: string | null;
  pages: number;
  chunks: number;
  size_bytes: number;
  content_hash: string;
  department: string;
  confidentiality: string;
  tags: string[];
  model_profile: string;
  embedding_provider: string;
  embedding_model: string;
  version: number;
  is_active: boolean;
  scope: DocScope;
  owner_user_id: number | null;
  owner_email: string | null;
  created_at: string | null;
}

export interface UploadResult {
  accepted: DocumentRow[];
  rejected: { filename: string; reason: string }[];
  total_seen?: number;
}

export interface QuerySource {
  n: number;
  filename: string;
  page: number;
  score: number;
  rerank_score: number | null;
  snippet: string;
}

export interface AnswerResult {
  query_id: number;
  answer: string;
  mode: string;
  confidence: number;
  sources: QuerySource[];
  model_profile?: string;
  llm_model?: string;
}

export type StreamEvent =
  | { type: "meta"; mode: string; sources: QuerySource[]; confidence: number; model_profile?: string; llm_model?: string }
  | { type: "token"; text: string }
  | { type: "status"; mode: string; message: string }
  | { type: "error"; message: string }
  | { type: "done"; query_id: number };

export interface AdminStats {
  documents_total: number;
  documents_ready: number;
  documents_failed: number;
  chunks_total: number;
  queries_total: number;
  queries_answered: number;
  knowledge_gaps: number;
  avg_latency_ms: number;
  feedback_helpful: number;
  feedback_unhelpful: number;
}

export interface RecentQuery {
  id: number;
  question: string;
  mode: string;
  confidence: number;
  latency_ms: number;
  feedback: number | null;
  created_at: string | null;
}

export interface KnowledgeGap {
  question: string;
  created_at: string | null;
}

export interface AuditEntry {
  id: number;
  actor: string;
  role?: string;
  action: string;
  detail: string;
  tenant_id?: number | null;
  created_at: string | null;
}

export interface UserRow {
  id: number;
  email: string;
  full_name: string;
  role: Role;
  is_active: boolean;
  clearance: number;
  last_login_at: string | null;
  created_at: string | null;
}

// ── Fine-grained access ──────────────────────────────────────────

export type GrantEffect = "allow" | "deny";
export type SubjectType = "user" | "group";

export interface PermissionInfo {
  key: string;
  description: string;
  resource_grantable: boolean;
}

export interface AccessCatalog {
  permissions: PermissionInfo[];
  confidentiality_levels: Record<string, number>;
  resource_types: string[];
}

export interface CustomRole {
  id: number;
  key: string;
  name: string;
  description: string;
  permissions: string[];
  created_at: string | null;
}

export interface AccessGroup {
  id: number;
  name: string;
  description: string;
  members: { user_id: number; email: string | null }[];
}

export interface SubjectAssignments {
  roles: { assignment_id: number; role_id: number; key: string }[];
  grants: { id: number; permission: string; effect: GrantEffect; note: string }[];
}

export interface ResourceGrantRow {
  id: number;
  subject_type: SubjectType;
  subject_id: number;
  subject_label: string | null;
  permission: string;
}

export interface MyAccess {
  role: Role;
  permissions: string[];
  custom_roles: { id: number; key: string; name: string }[];
  groups: { id: number; name: string }[];
  clearance: number;
  confidentiality_enforced: boolean;
}

export interface TenantRow {
  id: number;
  slug: string;
  name: string;
  api_key: string;
  users: number;
  documents: number;
  created_at: string | null;
}

// ── Model catalog + connectors ────────────────────────────────────

export interface CatalogOption {
  value: string;
  label: string;
  provider?: string;
  demo_safe?: boolean;
  requires_gpu?: boolean;
  notes?: string;
}

export interface ModelProfile {
  key: string;
  label: string;
  description: string;
  demo_safe: boolean;
  requires_gpu: boolean;
  embedding_model: string;
  llm_model: string;
  reranker_model: string;
  reranker_enabled: boolean;
  retrieval_top_k: number;
  rerank_top_k: number;
  retrieval_score_threshold: number;
  retrieval_max_context_chars: number;
  llm_max_tokens: number;
  llm_temperature: number;
}

export interface ConnectorField {
  key: string;
  label: string;
  required: boolean;
  placeholder?: string;
  multiline?: boolean;
}

export interface ConnectorProviderSpec {
  label: string;
  kinds: ("llm" | "embedding")[];
  model_id_hint: string;
  config_fields: ConnectorField[];
  secret_fields: ConnectorField[];
  secret_note?: string;
}

export interface ModelCatalog {
  profiles: ModelProfile[];
  embedding_models: CatalogOption[];
  reranker_models: CatalogOption[];
  llm_models: CatalogOption[];
  heavy_local_models: Record<string, string>;
  large_ollama_models: Record<string, string>;
  safe_demo_ollama_models: string[];
  optional_reranker_models: Record<string, string>;
  connector_providers: Record<string, ConnectorProviderSpec>;
}

export type ConnectorKind = "llm" | "embedding";

export interface ModelConnector {
  id: number;
  kind: ConnectorKind;
  name: string;
  provider: string;
  model_id: string;
  config: Record<string, string>;
  is_active: boolean;
  secret_fields_set: string[];
  created_at: string | null;
  updated_at: string | null;
}

export interface ConnectorTestResult {
  ok: boolean;
  detail: string;
}

export interface EffectiveConfig {
  model_profile: string;
  embedding_provider: string;
  embedding_model: string;
  llm_provider: string;
  llm_model: string;
  reranker_enabled: boolean;
  reranker_model: string;
  rerank_top_k: number;
  retrieval_top_k: number;
  retrieval_score_threshold: number;
  retrieval_max_context_chars: number;
  llm_temperature: number;
  llm_max_tokens: number;
  answer_language: string;
  chunk_size: number;
  chunk_overlap: number;
  tenant_overrides: Record<string, unknown>;
  llm_connector: { id: number; name: string; provider: string; model_id: string; kind: string } | null;
  embedding_connector: { id: number; name: string; provider: string; model_id: string; kind: string } | null;
  embedding_locked: boolean;
  embedding_locked_reason: string | null;
  embedding_locked_to: { provider: string; model: string; connector_id?: string | null } | null;
  index_status: {
    ready_documents: number;
    documents_indexed_for_current_embedding: number;
    reindex_required: boolean;
    current_embedding_model: string;
  };
}

export interface ConnectorStatus {
  gdrive: { configured: boolean };
  sharepoint: { configured: boolean };
  note?: string;
}

// ── Data connectors (external document sources) ───────────────────

export interface DataConnectorProviderSpec {
  label: string;
  config_fields: ConnectorField[];
  secret_fields: ConnectorField[];
  secret_note?: string;
}

export interface DataConnector {
  id: number;
  name: string;
  provider: string;
  config: Record<string, string>;
  is_active: boolean;
  secret_fields_set: string[];
  last_sync_at: string | null;
  last_sync_status: string;
  last_sync_detail: string;
  created_at: string | null;
  updated_at: string | null;
}

export interface ConnectorSyncRun {
  id: number;
  connector_id: number;
  status: string;
  queued: number;
  skipped: number;
  failed: number;
  detail: string;
  started_at: string | null;
  finished_at: string | null;
}

// ── Observability ────────────────────────────────────────────────

export interface ObsConfig {
  enabled: boolean;
  service: string;
  sinks: string[];
  trace_sample_rate: number;
  queue_dropped: number;
}

export interface MetricSeries {
  labels: Record<string, string>;
  value?: number;
  count?: number;
  sum?: number;
  buckets?: Record<string, number>;
}

export interface Metric {
  name: string;
  type: "counter" | "gauge" | "histogram";
  help: string;
  series: MetricSeries[];
}

export interface MetricsSnapshot {
  service: string;
  generated_at: number;
  uptime_seconds: number;
  series_dropped: number;
  sinks: string[];
  metrics: Metric[];
}

export interface ObsEvent {
  ts: number;
  kind: string;
  level: "info" | "warn" | "error";
  tenant: string | null;
  actor: string | null;
  route: string | null;
  request_id: string | null;
  trace_id: string | null;
  fields: Record<string, unknown>;
}

export interface ObsSpan {
  ts: number;
  name: string;
  span_id: string;
  parent_id: string | null;
  trace_id: string | null;
  tenant: string | null;
  status: "ok" | "error";
  duration_ms: number | null;
  attributes: Record<string, unknown>;
}
