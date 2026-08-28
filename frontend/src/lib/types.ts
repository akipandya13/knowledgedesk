// Shared response shapes mirrored from the FastAPI backend (backend/app/routers).

export type Role = "member" | "tenant_admin" | "superadmin" | "service";

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
  last_login_at: string | null;
  created_at: string | null;
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
}
