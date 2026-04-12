export type ChatScene =
  | ""
  | "qa_query"
  | "troubleshooting"
  | "onboarding"
  | "command_lookup";

export interface AuthUser {
  tenant_id: string;
  user_id: string;
  role: string;
  team_id: string;
  display_name: string;
  email: string;
  allowed_project_ids: string[];
  default_project_id: string;
  auth_source: string;
}

export interface AuthPayload {
  user: AuthUser;
  permissions: string[];
  active_project_id: string;
}

export interface OverviewPayload {
  app_name: string;
  app_version: string;
  data_dir: string;
  db_dir: string;
  logs_dir: string;
  llm_provider: string;
  embedding_provider: string;
  llm_api_ready: boolean;
  embedding_api_ready: boolean;
  knowledge_base_ready: boolean;
  source_file_count: number;
  chunk_count: number;
  indexed_file_count: number;
  changed_file_count: number;
  pending_file_count: number;
  failed_file_count: number;
  active_job_status: string;
  active_job_progress: number;
  auth_mode: string;
  deployment_mode: string;
}

export interface KnowledgeBaseJob {
  job_id: string;
  status: string;
  mode: string;
  stage: string;
  progress: number;
  message: string;
  total_documents?: number;
  processed_documents?: number;
  total_chunks?: number;
  processed_chunks?: number;
  started_at?: string;
  finished_at?: string;
  error?: string;
}

export interface KnowledgeStatusPayload {
  ready: boolean;
  chunk_count: number;
  document_count: number;
  indexed_count: number;
  changed_count: number;
  pending_count: number;
  failed_count: number;
  current_job: KnowledgeBaseJob | null;
}

export interface DocumentSummary {
  document_id: string;
  name: string;
  relative_path: string;
  extension: string;
  size_bytes: number;
  updated_at: string;
  status: string;
  theme: string;
  tags: string[];
  content_hash: string;
  indexed_hash: string;
  chunk_count: number;
  citation_count: number;
  last_indexed_at: string;
  last_error: string;
}

export interface DocumentPreview {
  document_id: string;
  preview: string;
  metadata: {
    file_type: string;
    parser_name: string;
    source_document_id?: string;
    segment_count?: number;
    title?: string;
    source_url?: string;
    resolved_url?: string;
    content_type?: string;
    page_count?: number;
    page_numbers?: number[];
    sheet_count?: number;
    sheet_names?: string[];
  };
}

export interface GraphNodePayload {
  id: string;
  label: string;
  node_type: string;
  size: number;
  meta: Record<string, unknown>;
}

export interface GraphEdgePayload {
  source: string;
  target: string;
  label: string;
  weight: number;
}

export interface GraphPayload {
  nodes: GraphNodePayload[];
  edges: GraphEdgePayload[];
  summary: Record<string, unknown>;
}

export interface WorkspaceBootstrap {
  overview: OverviewPayload;
  knowledge_status: KnowledgeStatusPayload;
  documents: DocumentSummary[];
  graph: GraphPayload;
  auth: AuthPayload;
}

export interface SettingsPayload {
  llm_provider: string;
  embedding_provider: string;
  llm_api_key: string;
  llm_api_base: string;
  llm_model: string;
  llm_temperature: number;
  llm_timeout: number;
  llm_max_tokens: number;
  embedding_api_key: string;
  embedding_api_base: string;
  embedding_model: string;
  chunk_size: number;
  chunk_overlap: number;
  top_k: number;
  max_history_turns: number;
  no_answer_min_score: number;
  collection_name: string;
  log_level: string;
  api_host: string;
  api_port: number;
  cors_origins: string;
  operations_managed_fields?: string[];
}

export interface SettingsTestPayload {
  llm: {
    ok: boolean;
    latency_ms: number;
    message: string;
  };
  embedding: {
    ok: boolean;
    latency_ms: number;
    message: string;
  };
  checked_at: string;
}

export interface RuntimeHelpPayload {
  description: string;
  managed_by_ops: string[];
}

export interface LogsPayload {
  summary: {
    path: string;
    exists: number;
    size_bytes: number;
    line_count: number;
  };
  filters: {
    level: string;
    keyword: string;
    start_time: string;
    end_time: string;
  };
  lines: string[];
}

export interface CitationPayload {
  knowledge_id: string;
  document_id: string;
  file_name: string;
  relative_path: string;
  snippet: string;
  full_text: string;
  score: number | null;
  vector_score?: number | null;
  lexical_score?: number;
  theme?: string;
  tags?: string[];
  chunk_id?: string;
  page_number?: number | null;
}

export interface ChatMessagePayload {
  id: string;
  tenant_id: string;
  session_id: string;
  user_id: string;
  role: "user" | "assistant" | "system" | "tool";
  content: string;
  provider: string;
  model: string;
  citations: CitationPayload[];
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface ChatSessionRecord {
  id: string;
  tenant_id: string;
  user_id: string;
  project_id: string;
  title: string;
  status: string;
  created_at: string;
  last_active_at: string;
}

export interface ChatSessionListItem {
  session: ChatSessionRecord;
  message_count: number;
  last_message: ChatMessagePayload | null;
}

export interface ChatSessionsResponse {
  items: ChatSessionListItem[];
  count: number;
  filters: Record<string, string | number>;
}

export interface ChatMessagesResponse {
  session: ChatSessionRecord;
  messages: ChatMessagePayload[];
  count: number;
}

export interface ChatRequestPayload {
  question: string;
  top_k?: number;
  chat_history: Array<{ role: string; content: string }>;
  session_id?: string;
  session_title?: string;
  request_id?: string;
  scene?: Exclude<ChatScene, "">;
}

export interface ChatMetaEvent {
  type: "meta";
  session_id: string;
  retrieved_count: number;
  retrieval_ms: number;
  rewritten_question: string;
  retrieval_query: string;
  confidence: number;
  summary: string;
  provider: string;
  model: string;
  steps: string[];
  used_knowledge_ids: string[];
  error_info: Record<string, unknown> | null;
}

export interface ChatDeltaEvent {
  type: "delta";
  content: string;
}

export interface ChatDoneEvent extends Omit<ChatMetaEvent, "type"> {
  type: "done";
  answer: string;
  citations: CitationPayload[];
  generation_ms: number;
  total_ms: number;
}

export interface ChatErrorEvent {
  type: "error";
  message: string;
}

export type ChatStreamEvent =
  | ChatMetaEvent
  | ChatDeltaEvent
  | ChatDoneEvent
  | ChatErrorEvent;

export interface StreamHandlers {
  onMeta?: (event: ChatMetaEvent) => void;
  onDelta?: (event: ChatDeltaEvent) => void;
  onDone?: (event: ChatDoneEvent) => void;
  onError?: (event: ChatErrorEvent) => void;
}
