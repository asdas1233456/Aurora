import { startTransition, useDeferredValue, useEffect, useRef, useState } from "react";
import {
  cancelKnowledgeJob,
  clearLogs,
  getDocumentPreview,
  getDocuments,
  getCurrentKnowledgeJob,
  getKnowledgeGraph,
  getKnowledgeStatus,
  getLogs,
  getOverview,
  getSettings,
  rebuildKnowledgeBase,
  removeDocuments,
  renameDocument,
  saveSettings,
  streamChat,
  testSettings,
  updateDocumentMetadata,
  uploadDocumentFiles,
} from "./api";
import {
  formatConfidence,
  formatPercent,
  inferCategory,
  parseTagsInput,
  stringifyTags,
} from "./lib/document-utils";

const NAV_ITEMS = [
  { id: "overview", label: "总览", hint: "状态与近期资产" },
  { id: "knowledge", label: "知识库", hint: "文档管理与重建" },
  { id: "chat", label: "对话", hint: "流式问答工作区" },
  { id: "graph", label: "图谱", hint: "结构与节点概览" },
  { id: "settings", label: "设置", hint: "长期环境配置" },
  { id: "logs", label: "日志", hint: "最近运行输出" },
];

const QUICK_PROMPTS = [
  "ADB 怎么查看当前前台 Activity？",
  "Linux 中如何快速定位端口占用问题？",
  "弱网场景下的移动端测试，应该优先关注什么？",
];

const WORKBENCH_SCENARIOS = [
  "文档入库",
  "RAG 联调",
  "知识图谱",
  "问答验收",
  "日志排查",
];

const LLM_PROVIDER_OPTIONS = [
  { value: "openai", label: "OpenAI 官方" },
  { value: "openai_compatible", label: "OpenAI 兼容接口" },
  { value: "deepseek", label: "DeepSeek" },
  { value: "qwen", label: "通义千问" },
  { value: "zhipu", label: "智谱 AI" },
  { value: "moonshot", label: "Kimi / Moonshot" },
  { value: "siliconflow", label: "硅基流动" },
  { value: "openrouter", label: "OpenRouter" },
];

const EMBEDDING_PROVIDER_OPTIONS = [
  { value: "openai", label: "OpenAI 官方" },
  { value: "openai_compatible", label: "OpenAI 兼容接口" },
  { value: "qwen", label: "通义千问" },
  { value: "zhipu", label: "智谱 AI" },
  { value: "siliconflow", label: "硅基流动" },
];

const PROVIDER_PRESETS = {
  openai: {
    key: "openai",
    label: "OpenAI",
    badge: "OA",
    description: "官方接口，适合 GPT 与 OpenAI Embedding。",
    llm: {
      provider: "openai",
      model: "gpt-4.1-mini",
      apiBase: "",
    },
    embedding: {
      provider: "openai",
      model: "text-embedding-3-small",
      apiBase: "",
    },
  },
  openai_compatible: {
    key: "openai_compatible",
    label: "兼容接口",
    badge: "API",
    description: "适合自建网关或任意 OpenAI 兼容服务。",
    llm: {
      provider: "openai_compatible",
      model: "your-compatible-model",
      apiBase: "https://your-compatible-api.example.com/v1",
    },
    embedding: {
      provider: "openai_compatible",
      model: "your-embedding-model",
      apiBase: "https://your-compatible-api.example.com/v1",
    },
  },
  deepseek: {
    key: "deepseek",
    label: "DeepSeek",
    badge: "DS",
    description: "聊天推荐直接填 `deepseek-chat`。",
    llm: {
      provider: "deepseek",
      model: "deepseek-chat",
      apiBase: "https://api.deepseek.com/v1",
    },
  },
  qwen: {
    key: "qwen",
    label: "通义千问",
    badge: "QW",
    description: "阿里云兼容模式，适合大多数中文场景。",
    llm: {
      provider: "qwen",
      model: "qwen-plus",
      apiBase: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    },
    embedding: {
      provider: "qwen",
      model: "text-embedding-v4",
      apiBase: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    },
  },
  zhipu: {
    key: "zhipu",
    label: "智谱 AI",
    badge: "ZP",
    description: "适合 GLM 与中文 Embedding 场景。",
    llm: {
      provider: "zhipu",
      model: "glm-4-air",
      apiBase: "https://open.bigmodel.cn/api/paas/v4",
    },
    embedding: {
      provider: "zhipu",
      model: "embedding-3",
      apiBase: "https://open.bigmodel.cn/api/paas/v4",
    },
  },
  moonshot: {
    key: "moonshot",
    label: "Kimi",
    badge: "KM",
    description: "适合长文本问答与摘要场景。",
    llm: {
      provider: "moonshot",
      model: "moonshot-v1-8k",
      apiBase: "https://api.moonshot.cn/v1",
    },
  },
  siliconflow: {
    key: "siliconflow",
    label: "硅基流动",
    badge: "SF",
    description: "适合快速切换国产模型与向量模型。",
    llm: {
      provider: "siliconflow",
      model: "Qwen/Qwen2.5-72B-Instruct",
      apiBase: "https://api.siliconflow.cn/v1",
    },
    embedding: {
      provider: "siliconflow",
      model: "BAAI/bge-m3",
      apiBase: "https://api.siliconflow.cn/v1",
    },
  },
  openrouter: {
    key: "openrouter",
    label: "OpenRouter",
    badge: "OR",
    description: "适合统一接入多个兼容聊天模型。",
    llm: {
      provider: "openrouter",
      model: "openai/gpt-4.1-mini",
      apiBase: "https://openrouter.ai/api/v1",
    },
  },
};

const LLM_PRESET_KEYS = ["openai", "deepseek", "qwen", "zhipu", "moonshot", "siliconflow", "openrouter", "openai_compatible"];
const EMBEDDING_PRESET_KEYS = ["openai", "qwen", "zhipu", "siliconflow", "openai_compatible"];

const SETTINGS_SECTIONS = [
  {
    title: "模型服务",
    description: "这里保存会长期复用的 LLM 与 Embedding 配置，并写入 .env。",
    fields: [
      { key: "LLM_PROVIDER", label: "LLM 提供方", type: "select", options: LLM_PROVIDER_OPTIONS },
      { key: "EMBEDDING_PROVIDER", label: "Embedding 提供方", type: "select", options: EMBEDDING_PROVIDER_OPTIONS },
      { key: "LLM_MODEL", label: "LLM 模型", type: "text" },
      { key: "EMBEDDING_MODEL", label: "Embedding 模型", type: "text" },
      { key: "LLM_API_BASE", label: "LLM 接口地址", type: "text", placeholder: "https://your-llm.example.com/v1" },
      { key: "EMBEDDING_API_BASE", label: "Embedding 接口地址", type: "text", placeholder: "https://your-embedding.example.com/v1" },
      { key: "LLM_API_KEY", label: "LLM 密钥", type: "password", hint: "留空表示保留当前已保存的值。" },
      { key: "EMBEDDING_API_KEY", label: "Embedding 密钥", type: "password", hint: "留空表示保留当前已保存的值。" },
    ],
  },
  {
    title: "检索参数",
    description: "控制切片、召回数量、超时、历史轮次与生成上限。",
    fields: [
      { key: "CHUNK_SIZE", label: "切片大小", type: "number" },
      { key: "CHUNK_OVERLAP", label: "切片重叠", type: "number" },
      { key: "TOP_K", label: "召回数量", type: "number" },
      { key: "MAX_HISTORY_TURNS", label: "历史轮次上限", type: "number" },
      { key: "NO_ANSWER_MIN_SCORE", label: "拒答阈值", type: "number", step: "0.01", hint: "越高越保守，越低越容易给出答案。" },
      { key: "LLM_TEMPERATURE", label: "采样温度", type: "number", step: "0.1" },
      { key: "LLM_TIMEOUT", label: "请求超时", type: "number", step: "1" },
      { key: "LLM_MAX_TOKENS", label: "最大生成 Token", type: "number" },
      { key: "CHROMA_COLLECTION_NAME", label: "向量集合名", type: "text" },
    ],
  },
  {
    title: "服务运行",
    description: "基础服务地址、日志级别与跨域等运行参数。",
    fields: [
      { key: "LOG_LEVEL", label: "日志级别", type: "select", options: ["DEBUG", "INFO", "WARNING", "ERROR"] },
      { key: "API_HOST", label: "API 主机", type: "text" },
      { key: "API_PORT", label: "API 端口", type: "number" },
      { key: "CORS_ORIGINS", label: "跨域来源", type: "text" },
    ],
  },
];

const DEFAULT_RUNTIME_CONFIG = {
  llmApiKey: "",
  embeddingApiKey: "",
  llmApiBase: "",
  embeddingApiBase: "",
  useSameEmbeddingKey: true,
  useSameEmbeddingBase: true,
};

const DEFAULT_OVERVIEW = {
  app_name: "Aurora",
  app_version: "--",
  data_dir: "",
  db_dir: "",
  logs_dir: "",
  llm_provider: "--",
  embedding_provider: "--",
  llm_api_ready: false,
  embedding_api_ready: false,
  knowledge_base_ready: false,
  source_file_count: 0,
  chunk_count: 0,
  indexed_file_count: 0,
  changed_file_count: 0,
  pending_file_count: 0,
  failed_file_count: 0,
  active_job_status: "",
  active_job_progress: 0,
};

const DEFAULT_KB_STATUS = {
  ready: false,
  chunk_count: 0,
  document_count: 0,
  indexed_count: 0,
  changed_count: 0,
  pending_count: 0,
  failed_count: 0,
  current_job: null,
};

const DEFAULT_LOGS = {
  summary: {
    path: "",
    exists: 0,
    size_bytes: 0,
    line_count: 0,
  },
  filters: {},
  lines: [],
};

const DEFAULT_LOG_FILTERS = {
  limit: "200",
  level: "",
  keyword: "",
  start_time: "",
  end_time: "",
};

const DEFAULT_SETTINGS_FORM = {
  LLM_PROVIDER: "openai",
  EMBEDDING_PROVIDER: "openai",
  LLM_MODEL: "",
  EMBEDDING_MODEL: "",
  LLM_API_BASE: "",
  EMBEDDING_API_BASE: "",
  LLM_API_KEY: "",
  EMBEDDING_API_KEY: "",
  CHUNK_SIZE: "1000",
  CHUNK_OVERLAP: "200",
  TOP_K: "4",
  MAX_HISTORY_TURNS: "8",
  NO_ANSWER_MIN_SCORE: "0.22",
  LLM_TEMPERATURE: "0.1",
  LLM_TIMEOUT: "60",
  LLM_MAX_TOKENS: "2048",
  CHROMA_COLLECTION_NAME: "aurora-knowledge",
  LOG_LEVEL: "INFO",
  API_HOST: "127.0.0.1",
  API_PORT: "8000",
  CORS_ORIGINS: "*",
};

const DEFAULT_GRAPH = {
  nodes: [],
  edges: [],
  summary: {},
};

const STORAGE_KEYS = {
  runtime: "aurora.runtime-config",
  sessions: "aurora.chat-sessions",
  activeSession: "aurora.active-session",
};

const DEFAULT_SETTINGS_TEST = {
  loading: false,
  report: null,
};

const TERMINAL_JOB_STATUSES = ["completed", "completed_with_errors", "failed", "cancelled"];

function readStoredJson(key, fallback) {
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

function writeStoredJson(key, value) {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Ignore storage errors.
  }
}

function createId() {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return `id-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function createSession(title = "新会话") {
  const now = new Date().toISOString();
  return { id: createId(), title, createdAt: now, updatedAt: now, messages: [] };
}

function createMessage(role, content, extra = {}) {
  return {
    id: createId(),
    role,
    content,
    citations: [],
    meta: null,
    streaming: false,
    createdAt: new Date().toISOString(),
    ...extra,
  };
}

function mapSettingsToForm(data = {}) {
  return {
    LLM_PROVIDER: data.llm_provider ?? "openai",
    EMBEDDING_PROVIDER: data.embedding_provider ?? "openai",
    LLM_MODEL: data.llm_model ?? "",
    EMBEDDING_MODEL: data.embedding_model ?? "",
    LLM_API_BASE: data.llm_api_base ?? "",
    EMBEDDING_API_BASE: data.embedding_api_base ?? "",
    LLM_API_KEY: "",
    EMBEDDING_API_KEY: "",
    CHUNK_SIZE: String(data.chunk_size ?? "1000"),
    CHUNK_OVERLAP: String(data.chunk_overlap ?? "200"),
    TOP_K: String(data.top_k ?? "4"),
    MAX_HISTORY_TURNS: String(data.max_history_turns ?? "8"),
    NO_ANSWER_MIN_SCORE: String(data.no_answer_min_score ?? "0.22"),
    LLM_TEMPERATURE: String(data.llm_temperature ?? "0.1"),
    LLM_TIMEOUT: String(data.llm_timeout ?? "60"),
    LLM_MAX_TOKENS: String(data.llm_max_tokens ?? "2048"),
    CHROMA_COLLECTION_NAME: data.collection_name ?? "",
    LOG_LEVEL: data.log_level ?? "INFO",
    API_HOST: data.api_host ?? "127.0.0.1",
    API_PORT: String(data.api_port ?? "8000"),
    CORS_ORIGINS: data.cors_origins ?? "*",
  };
}

function makeSettingsPayload(form) {
  const payload = { ...form };
  if (!String(payload.LLM_API_KEY || "").trim()) {
    delete payload.LLM_API_KEY;
  }
  if (!String(payload.EMBEDDING_API_KEY || "").trim()) {
    delete payload.EMBEDDING_API_KEY;
  }
  return payload;
}

function formatBytes(value) {
  const size = Number(value || 0);
  if (!Number.isFinite(size) || size <= 0) {
    return "0 B";
  }
  const units = ["B", "KB", "MB", "GB", "TB"];
  let unitIndex = 0;
  let nextValue = size;
  while (nextValue >= 1024 && unitIndex < units.length - 1) {
    nextValue /= 1024;
    unitIndex += 1;
  }
  return `${nextValue.toFixed(nextValue >= 10 || unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
}

function formatNumber(value) {
  return new Intl.NumberFormat("zh-CN").format(Number(value || 0));
}

function formatDuration(value) {
  const amount = Number(value || 0);
  if (!Number.isFinite(amount) || amount <= 0) {
    return "--";
  }
  if (amount < 1000) {
    return `${Math.round(amount)} ms`;
  }
  return `${(amount / 1000).toFixed(2)} s`;
}

function formatDate(value) {
  if (!value) {
    return "--";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return date.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function getFieldOptionValue(option) {
  return typeof option === "string" ? option : option.value;
}

function getFieldOptionLabel(option) {
  return typeof option === "string" ? option : option.label;
}

function translateNodeType(nodeType) {
  if (nodeType === "root") return "根节点";
  if (nodeType === "category") return "主题";
  if (nodeType === "file_type") return "文件类型";
  if (nodeType === "document") return "文档";
  return nodeType || "--";
}

function ProviderMark({ badge }) {
  return <span className="provider-mark" aria-hidden="true">{badge}</span>;
}

function SectionIcon({ kind }) {
  if (kind === "overview") {
    return (
      <svg className="section-icon" viewBox="0 0 24 24" aria-hidden="true">
        <rect x="3" y="3" width="7" height="7" rx="2" fill="currentColor" />
        <rect x="14" y="3" width="7" height="7" rx="2" fill="currentColor" />
        <rect x="3" y="14" width="7" height="7" rx="2" fill="currentColor" />
        <rect x="14" y="14" width="7" height="7" rx="2" fill="currentColor" />
      </svg>
    );
  }
  if (kind === "knowledge") {
    return (
      <svg className="section-icon" viewBox="0 0 24 24" aria-hidden="true">
        <path d="M6 4.5h8.5L18 8v11.5H6z" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
        <path d="M14.5 4.5V8H18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
        <path d="M9 12h6M9 15h6" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      </svg>
    );
  }
  if (kind === "chat") {
    return (
      <svg className="section-icon" viewBox="0 0 24 24" aria-hidden="true">
        <path d="M4 6.5A2.5 2.5 0 0 1 6.5 4H17.5A2.5 2.5 0 0 1 20 6.5V12.5A2.5 2.5 0 0 1 17.5 15H10l-4 4v-4.3A2.5 2.5 0 0 1 4 12.5z" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
        <path d="M8 8.5h8M8 11.5h5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      </svg>
    );
  }
  if (kind === "graph") {
    return (
      <svg className="section-icon" viewBox="0 0 24 24" aria-hidden="true">
        <circle cx="6" cy="7" r="2.5" fill="currentColor" />
        <circle cx="18" cy="7" r="2.5" fill="currentColor" />
        <circle cx="12" cy="17" r="2.5" fill="currentColor" />
        <path d="M8.2 8.3l2.8 6.1M15.8 8.3l-2.8 6.1M8.5 7h7" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      </svg>
    );
  }
  if (kind === "settings") {
    return (
      <svg className="section-icon" viewBox="0 0 24 24" aria-hidden="true">
        <path d="M5 7h7M16 7h3M10 7a2 2 0 1 1 0 .01M5 17h3M12 17h7M14 17a2 2 0 1 1 0 .01M5 12h12M19 12h0" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      </svg>
    );
  }
  if (kind === "info") {
    return (
      <svg className="section-icon" viewBox="0 0 24 24" aria-hidden="true">
        <circle cx="12" cy="12" r="8" fill="none" stroke="currentColor" strokeWidth="1.8" />
        <path d="M12 10v5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
        <circle cx="12" cy="7.4" r="1.1" fill="currentColor" />
      </svg>
    );
  }
  if (kind === "logs") {
    return (
      <svg className="section-icon" viewBox="0 0 24 24" aria-hidden="true">
        <path d="M6 5h12v14H6z" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
        <path d="M9 9h6M9 12h6M9 15h4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      </svg>
    );
  }
  return (
    <svg className="section-icon" viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="7" fill="none" stroke="currentColor" strokeWidth="1.8" />
      <path d="M12 8v4l2.5 2.5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

function normalizeDateTimeInput(value) {
  if (!value) {
    return "";
  }
  return String(value).replace(" ", "T").slice(0, 16);
}

function truncateText(value, maxLength = 20) {
  const text = String(value || "");
  if (text.length <= maxLength) {
    return text;
  }
  return `${text.slice(0, maxLength)}...`;
}

function makeSessionTitle(question) {
  const clean = String(question || "").replace(/\s+/g, " ").trim();
  if (!clean) {
    return "新会话";
  }
  return truncateText(clean, 18);
}

function getErrorMessage(error) {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return String(error || "请求失败");
}

function getStatusTone(value) {
  return value ? "success" : "warning";
}

function Panel({
  kicker,
  title,
  description,
  actions,
  children,
  className = "",
  onDescriptionClick,
  descriptionButtonLabel = "",
}) {
  return (
    <section className={`panel ${className}`.trim()}>
      {(kicker || title || description || actions) && (
        <div className="panel__header">
          <div className="panel__header-content">
            {kicker ? <p className="panel__kicker">{kicker}</p> : null}
            {title ? <h2 className="panel__title">{title}</h2> : null}
            {description && !onDescriptionClick ? <p className="panel__description">{description}</p> : null}
          </div>
          {actions || onDescriptionClick ? (
            <div className="panel__actions">
              {onDescriptionClick ? (
                <IconButton
                  icon="info"
                  label={descriptionButtonLabel || `${title || kicker || "模块"}说明`}
                  onClick={onDescriptionClick}
                />
              ) : null}
              {actions}
            </div>
          ) : null}
        </div>
      )}
      {children}
    </section>
  );
}

function SectionHeading({
  eyebrow,
  title,
  description,
  actions,
  icon,
  onDescriptionClick,
  descriptionButtonLabel = "",
}) {
  return (
    <div className="section-heading">
      <div className="section-heading__copy">
        <div className="section-heading__lead">
          {icon ? (
            <div className="section-heading__icon">
              <SectionIcon kind={icon} />
            </div>
          ) : null}
          <div>
            {eyebrow ? <p className="section-heading__eyebrow">{eyebrow}</p> : null}
            <h1 className="section-heading__title">{title}</h1>
          </div>
        </div>
        {description && !onDescriptionClick ? <p className="section-heading__description">{description}</p> : null}
      </div>
      {actions || onDescriptionClick ? (
        <div className="section-heading__actions">
          {onDescriptionClick ? (
            <IconButton
              icon="info"
              label={descriptionButtonLabel || `${title || eyebrow || "分区"}说明`}
              onClick={onDescriptionClick}
            />
          ) : null}
          {actions}
        </div>
      ) : null}
    </div>
  );
}

function Badge({ children, tone = "accent" }) {
  return <span className={`badge is-${tone}`}>{children}</span>;
}

function StatCard({ label, value, detail, valueClassName = "", valueTitle = "" }) {
  return (
    <div className="stat-card">
      <p className="stat-card__label">{label}</p>
      <p className={`stat-card__value ${valueClassName}`.trim()} title={valueTitle || String(value || "")}>
        {value}
      </p>
      {detail ? <p className="stat-card__detail">{detail}</p> : null}
    </div>
  );
}

function CompactMetric({ label, value, detail = "", valueTitle = "" }) {
  return (
    <div className="compact-metric">
      <span className="compact-metric__label">{label}</span>
      <strong className="compact-metric__value" title={valueTitle || String(value || "")}>
        {value}
      </strong>
      {detail ? <span className="compact-metric__detail">{detail}</span> : null}
    </div>
  );
}

function Field({ label, hint, error, children }) {
  return (
    <label className="field">
      <span className="field__label">{label}</span>
      {children}
      {error ? <p className="field__error">{error}</p> : null}
      {!error && hint ? <p className="field__hint">{hint}</p> : null}
    </label>
  );
}

function EmptyState({ title, description, action }) {
  return (
    <div className="empty-state">
      <div>
        <h3 className="empty-state__title">{title}</h3>
        <p className="empty-state__description">{description}</p>
        {action ? <div className="toolbar" style={{ justifyContent: "center", marginTop: 14 }}>{action}</div> : null}
      </div>
    </div>
  );
}

function UtilityLauncher({ icon, label, hint, onClick, compact = false, iconOnly = false }) {
  return (
    <button
      className={`utility-launcher ${compact ? "is-compact" : ""} ${iconOnly ? "is-icon-only" : ""}`.trim()}
      type="button"
      onClick={onClick}
      aria-label={hint ? `${label}：${hint}` : label}
      title={hint ? `${label} · ${hint}` : label}
    >
      <span className="utility-launcher__icon">
        <SectionIcon kind={icon} />
      </span>
      {!iconOnly ? (
        <span className="utility-launcher__copy">
          <strong>{label}</strong>
          {hint ? <span>{hint}</span> : null}
        </span>
      ) : null}
    </button>
  );
}

function IconButton({ icon, label, onClick }) {
  return (
    <button className="icon-button" type="button" onClick={onClick} aria-label={label} title={label}>
      <SectionIcon kind={icon} />
    </button>
  );
}

function FloatingWindow({ title, subtitle, onClose, children, wide = false }) {
  return (
    <div className="floating-window-backdrop" onClick={onClose} role="presentation">
      <section
        className={`floating-window ${wide ? "is-wide" : ""}`.trim()}
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <header className="floating-window__header">
          <div className="floating-window__heading">
            <p className="floating-window__eyebrow">快捷窗口</p>
            <h2 className="floating-window__title">{title}</h2>
            {subtitle ? <p className="floating-window__subtitle">{subtitle}</p> : null}
          </div>
          <button className="floating-window__close" type="button" onClick={onClose} aria-label="关闭窗口">
            ×
          </button>
        </header>
        <div className="floating-window__body">{children}</div>
      </section>
    </div>
  );
}

function GraphPreview({ graph }) {
  const containerRef = useRef(null);
  const canvasRef = useRef(null);
  const animationRef = useRef(0);
  const hoveredNodeIdRef = useRef("");
  const layoutRef = useRef({ nodes: [], draw: null });
  const [hoveredNode, setHoveredNode] = useState(null);

  const root = graph.nodes.find((node) => node.node_type === "root");
  const categories = graph.nodes.filter((node) => node.node_type === "category").slice(0, 8);
  const fileTypes = graph.nodes.filter((node) => node.node_type === "file_type").slice(0, 8);
  const documents = [...graph.nodes]
    .filter((node) => node.node_type === "document")
    .sort((left, right) => right.size - left.size)
    .slice(0, 14);

  const visibleNodes = [root, ...categories, ...fileTypes, ...documents].filter(Boolean);
  if (!visibleNodes.length) {
    return <EmptyState title="还没有图谱节点" description="上传文档并重建知识库后，这里会显示图谱概览。" />;
  }

  const visibleNodeIds = new Set(visibleNodes.map((node) => node.id));
  const visibleEdges = graph.edges.filter(
    (edge) => visibleNodeIds.has(edge.source) && visibleNodeIds.has(edge.target)
  );

  useEffect(() => {
    hoveredNodeIdRef.current = "";
    setHoveredNode(null);
  }, [graph]);

  useEffect(() => {
    const container = containerRef.current;
    const canvas = canvasRef.current;
    if (!container || !canvas) {
      return undefined;
    }

    const context = canvas.getContext("2d");
    if (!context) {
      return undefined;
    }

    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const connectionCount = new Map();
    visibleEdges.forEach((edge) => {
      connectionCount.set(edge.source, (connectionCount.get(edge.source) || 0) + 1);
      connectionCount.set(edge.target, (connectionCount.get(edge.target) || 0) + 1);
    });

    const getNodeColor = (nodeType) => {
      if (nodeType === "root") return "#14a6a8";
      if (nodeType === "category") return "#3fb57e";
      if (nodeType === "file_type") return "#63bfd3";
      return "#0d6971";
    };

    const scheduleFrame = (callback) => {
      if (!animationRef.current) {
        animationRef.current = window.requestAnimationFrame(callback);
      }
    };

    let nodes = [];
    let edges = [];
    let frameCount = 0;
    let stableFrameCount = 0;

    const buildNodes = (width, height) => {
      const groups = {
        root: visibleNodes.filter((node) => node.node_type === "root"),
        category: visibleNodes.filter((node) => node.node_type === "category"),
        file_type: visibleNodes.filter((node) => node.node_type === "file_type"),
        document: visibleNodes.filter((node) => node.node_type === "document"),
      };

      const placements = new Map();
      const placeRow = (items, xRatio, yRatio, spreadRatio) => {
        if (!items.length) {
          return;
        }
        items.forEach((item, index) => {
          const lane = items.length === 1 ? 0.5 : index / (items.length - 1);
          const spread = (lane - 0.5) * width * spreadRatio;
          placements.set(item.id, {
            x: width * xRatio + spread,
            y: height * yRatio + Math.sin(index * 0.7) * 12,
          });
        });
      };

      placeRow(groups.root, 0.5, 0.17, 0.05);
      placeRow(groups.category, 0.32, 0.4, 0.4);
      placeRow(groups.file_type, 0.7, 0.42, 0.34);
      placeRow(groups.document, 0.5, 0.75, 0.7);

      return visibleNodes.map((node, index) => {
        const anchor = placements.get(node.id) || {
          x: width * (0.2 + ((index % 5) * 0.15)),
          y: height * (0.2 + (Math.floor(index / 5) * 0.16)),
        };
        const radius = Math.max(8, Math.min(18, Number(node.size || 8) * 1.2));
        const jitterX = ((index % 3) - 1) * 18;
        const jitterY = ((index % 4) - 1.5) * 14;

        return {
          ...node,
          radius,
          x: anchor.x + jitterX,
          y: anchor.y + jitterY,
          vx: 0,
          vy: 0,
          anchorX: anchor.x,
          anchorY: anchor.y,
          linkCount: connectionCount.get(node.id) || 0,
        };
      });
    };

    const drawScene = () => {
      const width = canvas.width / dpr;
      const height = canvas.height / dpr;
      const hoveredId = hoveredNodeIdRef.current;

      context.clearRect(0, 0, width, height);

      context.save();
      context.strokeStyle = "rgba(19, 168, 166, 0.08)";
      context.lineWidth = 1;
      for (let x = 24; x < width; x += 48) {
        context.beginPath();
        context.moveTo(x, 0);
        context.lineTo(x, height);
        context.stroke();
      }
      for (let y = 24; y < height; y += 48) {
        context.beginPath();
        context.moveTo(0, y);
        context.lineTo(width, y);
        context.stroke();
      }
      context.restore();

      edges.forEach((edge) => {
        const isActive = hoveredId && (edge.source.id === hoveredId || edge.target.id === hoveredId);
        context.beginPath();
        context.moveTo(edge.source.x, edge.source.y);
        context.lineTo(edge.target.x, edge.target.y);
        context.strokeStyle = isActive ? "rgba(19, 168, 166, 0.52)" : "rgba(19, 168, 166, 0.18)";
        context.lineWidth = isActive ? 2 : 1.1;
        context.stroke();
      });

      nodes.forEach((node) => {
        const isActive = hoveredId === node.id;
        context.save();
        context.beginPath();
        context.fillStyle = getNodeColor(node.node_type);
        context.globalAlpha = node.node_type === "document" ? 0.84 : 0.95;
        context.arc(node.x, node.y, node.radius, 0, Math.PI * 2);
        context.fill();

        context.lineWidth = isActive ? 4 : 2;
        context.strokeStyle = isActive ? "rgba(255,255,255,0.95)" : "rgba(255,255,255,0.72)";
        context.stroke();
        context.restore();
      });

      nodes.forEach((node) => {
        const shouldLabel = node.node_type !== "document" || hoveredId === node.id || node.linkCount >= 3;
        if (!shouldLabel) {
          return;
        }

        context.save();
        context.fillStyle = "#20545b";
        context.font = node.node_type === "document"
          ? '12px "Microsoft YaHei UI", "Microsoft YaHei", sans-serif'
          : '600 12px "Microsoft YaHei UI", "Microsoft YaHei", sans-serif';
        context.textAlign = "center";
        context.textBaseline = "top";
        context.fillText(truncateText(node.label, node.node_type === "document" ? 10 : 12), node.x, node.y + node.radius + 8);
        context.restore();
      });
    };

    const configureCanvas = () => {
      const width = Math.max(320, Math.round(container.clientWidth));
      const height = Math.max(420, Math.round(container.clientHeight || 460));
      canvas.width = width * dpr;
      canvas.height = height * dpr;
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      context.setTransform(dpr, 0, 0, dpr, 0, 0);

      nodes = buildNodes(width, height);
      const nodeMap = new Map(nodes.map((node) => [node.id, node]));
      edges = visibleEdges
        .map((edge) => ({
          ...edge,
          source: nodeMap.get(edge.source),
          target: nodeMap.get(edge.target),
        }))
        .filter((edge) => edge.source && edge.target);

      layoutRef.current = { nodes, draw: drawScene };
      drawScene();
    };

    const runSimulation = () => {
      animationRef.current = 0;
      frameCount += 1;
      const width = canvas.width / dpr;
      const height = canvas.height / dpr;
      const padding = 36;
      let energy = 0;

      for (let index = 0; index < nodes.length; index += 1) {
        const source = nodes[index];
        for (let targetIndex = index + 1; targetIndex < nodes.length; targetIndex += 1) {
          const target = nodes[targetIndex];
          let dx = target.x - source.x;
          let dy = target.y - source.y;
          let distance = Math.hypot(dx, dy) || 1;

          if (distance < 1) {
            dx = 0.5;
            dy = 0.5;
            distance = 1;
          }

          const repulsion = 2200 / (distance * distance);
          const forceX = (dx / distance) * repulsion;
          const forceY = (dy / distance) * repulsion;

          source.vx -= forceX;
          source.vy -= forceY;
          target.vx += forceX;
          target.vy += forceY;
        }
      }

      edges.forEach((edge) => {
        const dx = edge.target.x - edge.source.x;
        const dy = edge.target.y - edge.source.y;
        const distance = Math.hypot(dx, dy) || 1;
        const preferredDistance = edge.target.node_type === "document" ? 90 : 110;
        const stretch = distance - preferredDistance;
        const spring = stretch * 0.0025;
        const forceX = (dx / distance) * spring;
        const forceY = (dy / distance) * spring;

        edge.source.vx += forceX;
        edge.source.vy += forceY;
        edge.target.vx -= forceX;
        edge.target.vy -= forceY;
      });

      nodes.forEach((node) => {
        const anchorPull = node.node_type === "root" ? 0.032 : node.node_type === "document" ? 0.013 : 0.02;
        node.vx += (node.anchorX - node.x) * anchorPull;
        node.vy += (node.anchorY - node.y) * anchorPull;

        node.vx *= node.node_type === "root" ? 0.78 : 0.86;
        node.vy *= node.node_type === "root" ? 0.78 : 0.86;

        node.x += node.vx;
        node.y += node.vy;

        if (node.x < padding) {
          node.x = padding;
          node.vx *= -0.35;
        }
        if (node.x > width - padding) {
          node.x = width - padding;
          node.vx *= -0.35;
        }
        if (node.y < padding) {
          node.y = padding;
          node.vy *= -0.35;
        }
        if (node.y > height - padding) {
          node.y = height - padding;
          node.vy *= -0.35;
        }

        energy += Math.abs(node.vx) + Math.abs(node.vy);
      });

      drawScene();

      if (energy < 0.6) {
        stableFrameCount += 1;
      } else {
        stableFrameCount = 0;
      }

      if (frameCount < 220 && stableFrameCount < 16) {
        scheduleFrame(runSimulation);
      }
    };

    configureCanvas();
    scheduleFrame(runSimulation);

    const handleResize = () => {
      frameCount = 0;
      stableFrameCount = 0;
      configureCanvas();
      scheduleFrame(runSimulation);
    };

    let resizeObserver = null;
    if (typeof ResizeObserver !== "undefined") {
      resizeObserver = new ResizeObserver(handleResize);
      resizeObserver.observe(container);
    } else {
      window.addEventListener("resize", handleResize);
    }

    return () => {
      if (animationRef.current) {
        window.cancelAnimationFrame(animationRef.current);
        animationRef.current = 0;
      }
      if (resizeObserver) {
        resizeObserver.disconnect();
      } else {
        window.removeEventListener("resize", handleResize);
      }
    };
  }, [graph]);

  const handlePointerMove = (event) => {
    const canvas = canvasRef.current;
    if (!canvas) {
      return;
    }

    const bounds = canvas.getBoundingClientRect();
    const pointerX = event.clientX - bounds.left;
    const pointerY = event.clientY - bounds.top;
    const hitNode = [...layoutRef.current.nodes]
      .reverse()
      .find((node) => Math.hypot(pointerX - node.x, pointerY - node.y) <= node.radius + 6) || null;

    const nextHoveredId = hitNode?.id || "";
    if (nextHoveredId === hoveredNodeIdRef.current) {
      return;
    }

    hoveredNodeIdRef.current = nextHoveredId;
    canvas.style.cursor = hitNode ? "pointer" : "default";
    setHoveredNode(
      hitNode
        ? {
            id: hitNode.id,
            label: hitNode.label,
            type: translateNodeType(hitNode.node_type),
            linkCount: hitNode.linkCount,
            size: hitNode.size,
          }
        : null
    );
    layoutRef.current.draw?.();
  };

  const handlePointerLeave = () => {
    const canvas = canvasRef.current;
    if (canvas) {
      canvas.style.cursor = "default";
    }
    hoveredNodeIdRef.current = "";
    setHoveredNode(null);
    layoutRef.current.draw?.();
  };

  return (
    <div className="graph-preview">
      <div className="graph-canvas" ref={containerRef}>
        <canvas
          ref={canvasRef}
          className="graph-canvas__surface"
          role="img"
          aria-label="动态知识图谱预览"
          onMouseMove={handlePointerMove}
          onMouseLeave={handlePointerLeave}
        />
      </div>
      <div className={`graph-hover-card ${hoveredNode ? "is-active" : "is-idle"}`}>
        {hoveredNode ? (
          <>
            <div className="graph-hover-card__title-row">
              <strong>{hoveredNode.label}</strong>
              <span className="metric-chip">{hoveredNode.type}</span>
            </div>
            <div className="graph-hover-card__meta">
              <span className="metric-chip">关联 {hoveredNode.linkCount}</span>
              <span className="metric-chip">权重 {formatNumber(hoveredNode.size || 0)}</span>
            </div>
          </>
        ) : (
          <>
            <strong>悬停节点查看详情</strong>
            <p className="muted-text">图谱会在刷新后进行一段轻量布局动画，稳定后自动停下，避免持续占用性能。</p>
          </>
        )}
      </div>
    </div>
  );
}

export default function App() {
  const [activeSection, setActiveSection] = useState("overview");
  const [activeOverlay, setActiveOverlay] = useState("");
  const [runtimeConfig, setRuntimeConfig] = useState(() => ({
    ...DEFAULT_RUNTIME_CONFIG,
    ...readStoredJson(STORAGE_KEYS.runtime, DEFAULT_RUNTIME_CONFIG),
  }));
  const [overview, setOverview] = useState(DEFAULT_OVERVIEW);
  const [kbStatus, setKbStatus] = useState(DEFAULT_KB_STATUS);
  const [documents, setDocuments] = useState([]);
  const [graph, setGraph] = useState(DEFAULT_GRAPH);
  const [settingsForm, setSettingsForm] = useState(DEFAULT_SETTINGS_FORM);
  const [settingsErrors, setSettingsErrors] = useState({});
  const [settingsTestState, setSettingsTestState] = useState(DEFAULT_SETTINGS_TEST);
  const [logsState, setLogsState] = useState(DEFAULT_LOGS);
  const [logsFilters, setLogsFilters] = useState(DEFAULT_LOG_FILTERS);
  const [selectedDocumentPath, setSelectedDocumentPath] = useState("");
  const [selectedDocumentPaths, setSelectedDocumentPaths] = useState([]);
  const [renameDraft, setRenameDraft] = useState("");
  const [documentThemeDraft, setDocumentThemeDraft] = useState("");
  const [documentTagsDraft, setDocumentTagsDraft] = useState("");
  const [documentSearch, setDocumentSearch] = useState("");
  const [documentStatusFilter, setDocumentStatusFilter] = useState("");
  const [documentThemeFilter, setDocumentThemeFilter] = useState("");
  const deferredDocumentSearch = useDeferredValue(documentSearch);
  const [uploadFiles, setUploadFiles] = useState([]);
  const [previewState, setPreviewState] = useState({
    path: "",
    content: "",
    loading: false,
    error: "",
  });
  const [systemMessage, setSystemMessage] = useState("");
  const [runtimeMessage, setRuntimeMessage] = useState("");
  const [knowledgeMessage, setKnowledgeMessage] = useState("");
  const [graphMessage, setGraphMessage] = useState("");
  const [settingsMessage, setSettingsMessage] = useState("");
  const [logsMessage, setLogsMessage] = useState("");
  const [chatMessage, setChatMessage] = useState("");
  const [overviewLoading, setOverviewLoading] = useState(false);
  const [knowledgeLoading, setKnowledgeLoading] = useState(false);
  const [graphLoading, setGraphLoading] = useState(false);
  const [settingsLoading, setSettingsLoading] = useState(false);
  const [logsLoading, setLogsLoading] = useState(false);
  const [metadataSaving, setMetadataSaving] = useState(false);
  const [chatBusy, setChatBusy] = useState(false);
  const [chatInput, setChatInput] = useState("");
  const [chatTopK, setChatTopK] = useState("4");
  const [sessions, setSessions] = useState(() => {
    const storedSessions = readStoredJson(STORAGE_KEYS.sessions, []);
    return Array.isArray(storedSessions) && storedSessions.length
      ? storedSessions
      : [createSession("欢迎会话")];
  });
  const [activeSessionId, setActiveSessionId] = useState(() =>
    readStoredJson(STORAGE_KEYS.activeSession, "")
  );

  const previewPathRef = useRef("");
  const chatAbortRef = useRef(null);
  const chatScrollRef = useRef(null);
  const uploadInputRef = useRef(null);
  const sessionPersistTimerRef = useRef(0);
  const streamFrameRef = useRef(0);
  const jobPollTimerRef = useRef(0);
  const streamDraftRef = useRef({
    sessionId: "",
    messageId: "",
    buffer: "",
  });

  const activeSession =
    sessions.find((session) => session.id === activeSessionId) ?? sessions[0] ?? null;
  const activeMessages = activeSession?.messages ?? [];

  const filteredDocuments = documents.filter((item) => {
    const keyword = deferredDocumentSearch.trim().toLowerCase();
    const matchesKeyword = !keyword
      || [item.name, item.extension, item.path, item.theme, ...(item.tags || []), inferCategory(item.name)].some((value) =>
        String(value || "").toLowerCase().includes(keyword)
      );
    const matchesStatus = !documentStatusFilter || item.status === documentStatusFilter;
    const matchesTheme = !documentThemeFilter || item.theme === documentThemeFilter;
    return matchesKeyword && matchesStatus && matchesTheme;
  });

  const selectedDocument =
    documents.find((item) => item.path === selectedDocumentPath) ?? null;

  const documentThemes = Array.from(
    new Set(
      documents
        .map((item) => String(item.theme || "").trim())
        .filter(Boolean)
    )
  ).sort((left, right) => left.localeCompare(right, "zh-CN"));

  const recentDocuments = [...documents]
    .sort((left, right) => String(right.updated_at).localeCompare(String(left.updated_at)))
    .slice(0, 6);

  const categoryCounts = [];
  const categoryMap = new Map();
  documents.forEach((item) => {
    const category = item.theme || inferCategory(item.name);
    categoryMap.set(category, (categoryMap.get(category) || 0) + 1);
  });
  categoryMap.forEach((count, label) => {
    categoryCounts.push({ label, count });
  });
  categoryCounts.sort((left, right) => right.count - left.count);

  const extensionCounts = [];
  const extensionMap = new Map();
  documents.forEach((item) => {
    const extension = String(item.extension || "").toUpperCase() || "OTHER";
    extensionMap.set(extension, (extensionMap.get(extension) || 0) + 1);
  });
  extensionMap.forEach((count, label) => {
    extensionCounts.push({ label, count });
  });
  extensionCounts.sort((left, right) => right.count - left.count);

  const graphHighlights = [...graph.nodes]
    .filter((node) => node.node_type !== "root")
    .sort((left, right) => right.size - left.size)
    .slice(0, 8);

  const lastAssistantMessage = [...activeMessages]
    .reverse()
    .find((message) => message.role === "assistant" && message.content);

  const allVisibleDocumentsSelected =
    filteredDocuments.length > 0 &&
    filteredDocuments.every((item) => selectedDocumentPaths.includes(item.path));

  useEffect(() => {
    writeStoredJson(STORAGE_KEYS.runtime, runtimeConfig);
  }, [runtimeConfig]);

  useEffect(() => {
    window.clearTimeout(sessionPersistTimerRef.current);
    sessionPersistTimerRef.current = window.setTimeout(() => {
      writeStoredJson(STORAGE_KEYS.sessions, sessions);
    }, 240);

    return () => {
      window.clearTimeout(sessionPersistTimerRef.current);
    };
  }, [sessions]);

  useEffect(() => {
    writeStoredJson(STORAGE_KEYS.activeSession, activeSessionId);
  }, [activeSessionId]);

  useEffect(() => {
    if (!sessions.length) {
      const fallback = createSession("欢迎会话");
      setSessions([fallback]);
      setActiveSessionId(fallback.id);
      return;
    }

    if (!sessions.some((session) => session.id === activeSessionId)) {
      setActiveSessionId(sessions[0].id);
    }
  }, [sessions, activeSessionId]);

  useEffect(() => {
    const node = chatScrollRef.current;
    if (node) {
      node.scrollTop = node.scrollHeight;
    }
  }, [activeSessionId, activeMessages]);

  useEffect(() => {
    setDocumentThemeDraft(selectedDocument?.theme || "");
    setDocumentTagsDraft(stringifyTags(selectedDocument?.tags || []));
  }, [selectedDocument]);

  useEffect(() => {
    Promise.all([
      refreshOverviewData(),
      refreshKnowledgeData(),
      refreshGraphData(),
      refreshSettingsData(),
      refreshLogsData(DEFAULT_LOG_FILTERS),
    ]);

    return () => {
      chatAbortRef.current?.abort();
      window.clearTimeout(sessionPersistTimerRef.current);
      window.clearTimeout(jobPollTimerRef.current);
      if (streamFrameRef.current) {
        window.cancelAnimationFrame(streamFrameRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (!activeOverlay) {
      return undefined;
    }

    const previousOverflow = document.body.style.overflow;
    const handleKeyDown = (event) => {
      if (event.key === "Escape") {
        setActiveOverlay("");
      }
    };

    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", handleKeyDown);

    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [activeOverlay]);

  function openNoteOverlay({ title, subtitle = "", paragraphs = [] }) {
    setActiveOverlay({
      type: "note",
      title,
      subtitle,
      paragraphs,
    });
  }

  function updateSession(sessionId, updater) {
    startTransition(() => {
      setSessions((currentSessions) =>
        currentSessions.map((session) => {
          if (session.id !== sessionId) {
            return session;
          }
          const nextSession = updater(session);
          return {
            ...nextSession,
            updatedAt: new Date().toISOString(),
          };
        })
      );
    });
  }

  function updateMessage(sessionId, messageId, updater) {
    updateSession(sessionId, (session) => ({
      ...session,
      messages: session.messages.map((message) =>
        message.id === messageId ? updater(message) : message
      ),
    }));
  }

  function resetStreamDraft() {
    streamDraftRef.current = {
      sessionId: "",
      messageId: "",
      buffer: "",
    };
    if (streamFrameRef.current) {
      window.cancelAnimationFrame(streamFrameRef.current);
      streamFrameRef.current = 0;
    }
  }

  function flushStreamDraft() {
    const draft = streamDraftRef.current;
    if (!draft.sessionId || !draft.messageId || !draft.buffer) {
      if (streamFrameRef.current) {
        window.cancelAnimationFrame(streamFrameRef.current);
        streamFrameRef.current = 0;
      }
      return;
    }

    const content = draft.buffer;
    draft.buffer = "";
    streamFrameRef.current = 0;

    updateMessage(draft.sessionId, draft.messageId, (message) => ({
      ...message,
      content: `${message.content}${content}`,
    }));
  }

  function queueStreamDelta(sessionId, messageId, chunk) {
    if (!chunk) {
      return;
    }

    const draft = streamDraftRef.current;
    if (
      draft.sessionId &&
      (draft.sessionId !== sessionId || draft.messageId !== messageId)
    ) {
      flushStreamDraft();
    }

    draft.sessionId = sessionId;
    draft.messageId = messageId;
    draft.buffer += chunk;

    if (!streamFrameRef.current) {
      streamFrameRef.current = window.requestAnimationFrame(() => {
        flushStreamDraft();
      });
    }
  }

  async function loadDocumentPreview(path) {
    if (!path) {
      previewPathRef.current = "";
      setPreviewState({ path: "", content: "", loading: false, error: "" });
      return;
    }

    previewPathRef.current = path;
    setPreviewState({ path, content: "", loading: true, error: "" });

    try {
      const data = await getDocumentPreview(path);
      if (previewPathRef.current !== path) {
        return;
      }
      setPreviewState({
        path,
        content: data.preview || "",
        loading: false,
        error: "",
      });
    } catch (error) {
      if (previewPathRef.current !== path) {
        return;
      }
      setPreviewState({
        path,
        content: "",
        loading: false,
        error: getErrorMessage(error),
      });
    }
  }

  async function refreshOverviewData() {
    setOverviewLoading(true);
    try {
      const [nextOverview, nextStatus] = await Promise.all([
        getOverview(runtimeConfig),
        getKnowledgeStatus(runtimeConfig),
      ]);
      setOverview(nextOverview);
      setKbStatus(nextStatus);
      if (nextStatus.current_job && !TERMINAL_JOB_STATUSES.includes(nextStatus.current_job.status)) {
        scheduleKnowledgeJobPolling();
      } else {
        stopKnowledgeJobPolling();
      }
      setSystemMessage("");
    } catch (error) {
      setSystemMessage(getErrorMessage(error));
    } finally {
      setOverviewLoading(false);
    }
  }

  async function refreshKnowledgeData(options = {}) {
    const { keepSelection = true, preferredPath = "" } = options;
    setKnowledgeLoading(true);

    try {
      const nextDocuments = await getDocuments();
      const nextPaths = new Set(nextDocuments.map((item) => item.path));
      const currentSelection =
        preferredPath && nextPaths.has(preferredPath)
          ? preferredPath
          : keepSelection && nextPaths.has(selectedDocumentPath)
            ? selectedDocumentPath
            : nextDocuments[0]?.path || "";

      setDocuments(nextDocuments);
      setSelectedDocumentPaths((current) => current.filter((path) => nextPaths.has(path)));
      setSelectedDocumentPath(currentSelection);
      setRenameDraft(nextDocuments.find((item) => item.path === currentSelection)?.name || "");
      setKnowledgeMessage("");

      if (currentSelection) {
        await loadDocumentPreview(currentSelection);
      } else {
        await loadDocumentPreview("");
      }
    } catch (error) {
      setKnowledgeMessage(getErrorMessage(error));
    } finally {
      setKnowledgeLoading(false);
    }
  }

  function stopKnowledgeJobPolling() {
    window.clearTimeout(jobPollTimerRef.current);
    jobPollTimerRef.current = 0;
  }

  function scheduleKnowledgeJobPolling() {
    stopKnowledgeJobPolling();
    jobPollTimerRef.current = window.setTimeout(() => {
      refreshKnowledgeJob();
    }, 1800);
  }

  async function refreshKnowledgeJob() {
    try {
      const nextJob = await getCurrentKnowledgeJob();
      setKbStatus((current) => ({
        ...current,
        current_job: nextJob,
      }));

      if (nextJob && !TERMINAL_JOB_STATUSES.includes(nextJob.status)) {
        scheduleKnowledgeJobPolling();
        return;
      }

      stopKnowledgeJobPolling();
      if (nextJob && TERMINAL_JOB_STATUSES.includes(nextJob.status)) {
        await Promise.all([
          refreshOverviewData(),
          refreshKnowledgeData({ keepSelection: true }),
          refreshGraphData(),
        ]);
      }
    } catch (error) {
      stopKnowledgeJobPolling();
      setKnowledgeMessage(getErrorMessage(error));
    }
  }

  async function refreshGraphData() {
    setGraphLoading(true);
    try {
      const nextGraph = await getKnowledgeGraph();
      setGraph(nextGraph);
      setGraphMessage("");
    } catch (error) {
      setGraphMessage(getErrorMessage(error));
    } finally {
      setGraphLoading(false);
    }
  }

  async function refreshSettingsData() {
    setSettingsLoading(true);
    try {
      const nextSettings = await getSettings();
      setSettingsForm(mapSettingsToForm(nextSettings));
      setSettingsErrors({});
    } catch (error) {
      setSettingsMessage(getErrorMessage(error));
    } finally {
      setSettingsLoading(false);
    }
  }

  async function refreshLogsData(nextFilters = logsFilters) {
    setLogsLoading(true);
    try {
      const normalizedFilters = {
        ...nextFilters,
        limit: String(nextFilters.limit || "200"),
      };
      const nextLogs = await getLogs(normalizedFilters);
      setLogsState(nextLogs);
      setLogsFilters(normalizedFilters);
      setLogsMessage("");
    } catch (error) {
      setLogsMessage(getErrorMessage(error));
    } finally {
      setLogsLoading(false);
    }
  }

  function handleSwitchSection(sectionId) {
    startTransition(() => {
      setActiveSection(sectionId);
    });
  }

  function handleRuntimeChange(key, value) {
    setRuntimeConfig((current) => ({ ...current, [key]: value }));
  }

  function handleClearUploadFiles() {
    setUploadFiles([]);
    if (uploadInputRef.current) {
      uploadInputRef.current.value = "";
    }
  }

  async function handleApplyRuntimeConfig() {
    await refreshOverviewData();
    setRuntimeMessage("运行时请求头已应用。");
  }

  async function handleResetRuntimeConfig() {
    setRuntimeConfig(DEFAULT_RUNTIME_CONFIG);
    setRuntimeMessage("运行时请求头已清空。");
    await refreshOverviewData();
  }

  async function handleSelectDocument(path) {
    setSelectedDocumentPath(path);
    setRenameDraft(documents.find((item) => item.path === path)?.name || "");
    await loadDocumentPreview(path);
  }

  function handleToggleDocument(path) {
    setSelectedDocumentPaths((current) =>
      current.includes(path)
        ? current.filter((item) => item !== path)
        : [...current, path]
    );
  }

  function handleToggleAllVisibleDocuments() {
    const visiblePaths = filteredDocuments.map((item) => item.path);
    if (!visiblePaths.length) {
      return;
    }

    setSelectedDocumentPaths((current) => {
      if (visiblePaths.every((path) => current.includes(path))) {
        return current.filter((path) => !visiblePaths.includes(path));
      }
      return Array.from(new Set([...current, ...visiblePaths]));
    });
  }

  async function handleRenameDocument() {
    if (!selectedDocumentPath || !renameDraft.trim()) {
      setKnowledgeMessage("请先选择一个文档，并输入新的文件名。");
      return;
    }

    try {
      const result = await renameDocument(selectedDocumentPath, renameDraft.trim());
      setKnowledgeMessage("文档已重命名。");
      await Promise.all([
        refreshKnowledgeData({ keepSelection: false, preferredPath: result.new_path }),
        refreshOverviewData(),
        refreshGraphData(),
      ]);
    } catch (error) {
      setKnowledgeMessage(getErrorMessage(error));
    }
  }

  async function handleDeleteDocuments() {
    const paths = selectedDocumentPaths.length
      ? selectedDocumentPaths
      : selectedDocumentPath
        ? [selectedDocumentPath]
        : [];

    if (!paths.length) {
      setKnowledgeMessage("请先选择要删除的文档。");
      return;
    }

    if (!window.confirm(`确认删除 ${paths.length} 份文档吗？`)) {
      return;
    }

    try {
      await removeDocuments(paths);
      setKnowledgeMessage(`已删除 ${paths.length} 份文档。`);
      setSelectedDocumentPaths([]);
      await Promise.all([
        refreshKnowledgeData({ keepSelection: false }),
        refreshOverviewData(),
        refreshGraphData(),
      ]);
    } catch (error) {
      setKnowledgeMessage(getErrorMessage(error));
    }
  }

  async function handleUploadDocuments() {
    if (!uploadFiles.length) {
      setKnowledgeMessage("请先选择要上传的文件。");
      return;
    }

    try {
      const result = await uploadDocumentFiles(uploadFiles);
      setKnowledgeMessage(`已上传 ${result.saved_count} 个文件。`);
      handleClearUploadFiles();
      await Promise.all([
        refreshKnowledgeData({ keepSelection: false }),
        refreshOverviewData(),
        refreshGraphData(),
      ]);
    } catch (error) {
      setKnowledgeMessage(getErrorMessage(error));
    }
  }

  async function handleRebuildKnowledgeBase() {
    try {
      const job = await rebuildKnowledgeBase(runtimeConfig);
      setKbStatus((current) => ({ ...current, current_job: job }));
      setKnowledgeMessage("知识库重建任务已启动。");
      scheduleKnowledgeJobPolling();
    } catch (error) {
      setKnowledgeMessage(getErrorMessage(error));
    }
  }

  async function handleCancelKnowledgeBaseJob() {
    const jobId = kbStatus.current_job?.job_id;
    if (!jobId) {
      return;
    }

    try {
      const job = await cancelKnowledgeJob(jobId);
      setKbStatus((current) => ({ ...current, current_job: job }));
      setKnowledgeMessage("已发送取消请求，系统会在安全节点停止任务。");
      scheduleKnowledgeJobPolling();
    } catch (error) {
      setKnowledgeMessage(getErrorMessage(error));
    }
  }

  async function handleSaveDocumentMetadata(targetPaths = []) {
    const paths = targetPaths.length
      ? targetPaths
      : selectedDocumentPaths.length
        ? selectedDocumentPaths
        : selectedDocumentPath
          ? [selectedDocumentPath]
          : [];

    if (!paths.length) {
      setKnowledgeMessage("请先选择至少一个文档，再保存主题或标签。");
      return;
    }

    setMetadataSaving(true);
    try {
      await updateDocumentMetadata(paths, {
        theme: documentThemeDraft.trim(),
        tags: parseTagsInput(documentTagsDraft),
      });
      setKnowledgeMessage(`已更新 ${paths.length} 份文档的主题与标签。`);
      await Promise.all([
        refreshKnowledgeData({ keepSelection: true }),
        refreshGraphData(),
      ]);
    } catch (error) {
      setKnowledgeMessage(getErrorMessage(error));
    } finally {
      setMetadataSaving(false);
    }
  }

  function handleSettingsChange(key, value) {
    setSettingsForm((current) => ({ ...current, [key]: value }));
  }

  function handleApplyProviderPreset(mode, presetKey) {
    const preset = PROVIDER_PRESETS[presetKey];
    if (!preset) {
      return;
    }

    const nextPreset = preset[mode];
    if (!nextPreset) {
      return;
    }

    if (mode === "llm") {
      setSettingsForm((current) => ({
        ...current,
        LLM_PROVIDER: nextPreset.provider,
        LLM_MODEL: nextPreset.model,
        LLM_API_BASE: nextPreset.apiBase,
      }));
      setSettingsMessage(`${preset.label} 的 LLM 预设已填入，请补充密钥后保存。`);
    } else {
      setSettingsForm((current) => ({
        ...current,
        EMBEDDING_PROVIDER: nextPreset.provider,
        EMBEDDING_MODEL: nextPreset.model,
        EMBEDDING_API_BASE: nextPreset.apiBase,
      }));
      setSettingsMessage(`${preset.label} 的 Embedding 预设已填入，请补充密钥后保存。`);
    }

    setSettingsErrors((current) => {
      const next = { ...current };
      if (mode === "llm") {
        delete next.LLM_PROVIDER;
        delete next.LLM_MODEL;
        delete next.LLM_API_BASE;
      } else {
        delete next.EMBEDDING_PROVIDER;
        delete next.EMBEDDING_MODEL;
        delete next.EMBEDDING_API_BASE;
      }
      return next;
    });
  }

  async function handleSaveSettings() {
    setSettingsLoading(true);
    setSettingsMessage("");
    setSettingsErrors({});

    try {
      await saveSettings(makeSettingsPayload(settingsForm));
      await refreshSettingsData();
      setSettingsMessage("配置已保存到 .env。");
    } catch (error) {
      const details = error && typeof error === "object" ? error.details : null;
      if (details && typeof details === "object" && !Array.isArray(details)) {
        setSettingsErrors(details);
      }
      setSettingsMessage(getErrorMessage(error));
    } finally {
      setSettingsLoading(false);
    }
  }

  async function handleTestSettings() {
    setSettingsTestState({ loading: true, report: null });
    setSettingsMessage("");

    try {
      const report = await testSettings(makeSettingsPayload(settingsForm));
      setSettingsTestState({ loading: false, report });
      setSettingsMessage(report.llm?.ok && report.embedding?.ok ? "连通性测试通过。" : "连通性测试已完成，请查看结果。");
    } catch (error) {
      setSettingsTestState({ loading: false, report: null });
      setSettingsMessage(getErrorMessage(error));
    }
  }

  async function handleSearchLogs() {
    await refreshLogsData(logsFilters);
  }

  async function handleClearLogs() {
    if (!window.confirm("确认清空日志文件吗？")) {
      return;
    }

    try {
      await clearLogs();
      setLogsMessage("日志文件已清空。");
      await refreshLogsData({
        ...logsFilters,
        limit: String(logsFilters.limit || "200"),
      });
    } catch (error) {
      setLogsMessage(getErrorMessage(error));
    }
  }

  function handleCreateSession() {
    const nextSession = createSession("新会话");
    startTransition(() => {
      setSessions((current) => [nextSession, ...current]);
      setActiveSessionId(nextSession.id);
      setChatInput("");
      setChatMessage("");
    });
  }

  function handleDeleteSession(sessionId) {
    if (chatBusy && sessionId === activeSessionId) {
      setChatMessage("请先停止当前生成，再删除这个会话。");
      return;
    }

    if (!window.confirm("确认删除这个会话吗？")) {
      return;
    }

    startTransition(() => {
      setSessions((currentSessions) => {
        const nextSessions = currentSessions.filter((session) => session.id !== sessionId);
        if (nextSessions.length) {
          return nextSessions;
        }
        return [createSession("新会话")];
      });
    });
  }

  function handleClearCurrentSession() {
    if (!activeSession) {
      return;
    }
    if (chatBusy) {
      setChatMessage("请先停止当前生成，再清空会话。");
      return;
    }
    if (!window.confirm("确认清空当前会话的所有消息吗？")) {
      return;
    }

    updateSession(activeSession.id, (session) => ({
      ...session,
      title: "新会话",
      messages: [],
    }));
  }

  async function handleSendMessage() {
    if (!activeSession || chatBusy) {
      return;
    }

    const question = chatInput.trim();
    if (!question) {
      setChatMessage("请输入问题后再发送。");
      return;
    }

    const sessionId = activeSession.id;
    const userMessage = createMessage("user", question);
    const assistantMessage = createMessage("assistant", "", { streaming: true });
    const history = activeSession.messages.map((message) => ({
      role: message.role,
      content: message.content,
    }));

    setChatInput("");
    setChatBusy(true);
    setChatMessage("");

    updateSession(sessionId, (session) => ({
      ...session,
      title: session.messages.length ? session.title : makeSessionTitle(question),
      messages: [...session.messages, userMessage, assistantMessage],
    }));

    const controller = new AbortController();
    chatAbortRef.current = controller;

    try {
      await streamChat(
        {
          question,
          top_k: Number(chatTopK) || 4,
          chat_history: history,
        },
        runtimeConfig,
        {
          onMeta(event) {
            updateMessage(sessionId, assistantMessage.id, (message) => ({
              ...message,
              meta: {
                ...(message.meta || {}),
                retrieved_count: event.retrieved_count,
                retrieval_ms: event.retrieval_ms,
                rewritten_question: event.rewritten_question,
                retrieval_query: event.retrieval_query,
                confidence: event.confidence,
              },
            }));
          },
          onDelta(event) {
            queueStreamDelta(sessionId, assistantMessage.id, event.content || "");
          },
          onDone(event) {
            flushStreamDraft();
            updateMessage(sessionId, assistantMessage.id, (message) => ({
              ...message,
              streaming: false,
              content: event.answer || message.content,
              citations: event.citations || [],
              meta: {
                retrieved_count: event.retrieved_count,
                retrieval_ms: event.retrieval_ms,
                generation_ms: event.generation_ms,
                total_ms: event.total_ms,
                rewritten_question: event.rewritten_question,
                retrieval_query: event.retrieval_query,
                confidence: event.confidence,
              },
            }));
          },
          onError(event) {
            flushStreamDraft();
            updateMessage(sessionId, assistantMessage.id, (message) => ({
              ...message,
              streaming: false,
              content: event.message || "流式请求失败。",
            }));
          },
        },
        controller.signal
      );
    } catch (error) {
      if (error?.name === "AbortError") {
        flushStreamDraft();
        updateMessage(sessionId, assistantMessage.id, (message) => ({
          ...message,
          streaming: false,
          content: message.content || "已手动停止本次生成。",
        }));
        setChatMessage("当前生成已停止。");
      } else {
        flushStreamDraft();
        updateMessage(sessionId, assistantMessage.id, (message) => ({
          ...message,
          streaming: false,
          content: message.content || getErrorMessage(error),
        }));
        setChatMessage(getErrorMessage(error));
      }
    } finally {
      chatAbortRef.current = null;
      setChatBusy(false);
      resetStreamDraft();
    }
  }

  function handleStopMessage() {
    chatAbortRef.current?.abort();
  }

  function handleUsePrompt(prompt) {
    handleSwitchSection("chat");
    setChatInput(prompt);
    setActiveOverlay("");
  }

  const demoMode = !overview.llm_api_ready || !overview.embedding_api_ready;

  const navStatuses = {
    overview: {
      label: overview.knowledge_base_ready ? "已就绪" : "待检查",
      tone: getStatusTone(overview.knowledge_base_ready),
    },
    knowledge: {
      label: kbStatus.current_job && !TERMINAL_JOB_STATUSES.includes(kbStatus.current_job.status)
        ? "进行中"
        : `${kbStatus.changed_count + kbStatus.pending_count} 待更`,
      tone: kbStatus.current_job && !TERMINAL_JOB_STATUSES.includes(kbStatus.current_job.status)
        ? "accent"
        : (kbStatus.changed_count + kbStatus.pending_count || kbStatus.failed_count) ? "warning" : "success",
    },
    chat: {
      label: chatBusy ? "生成中" : `${sessions.length} 个`,
      tone: chatBusy ? "accent" : "success",
    },
    graph: {
      label: `${graph.nodes.length} 节点`,
      tone: graph.nodes.length ? "success" : "warning",
    },
    settings: {
      label: "配置",
      tone: "accent",
    },
    logs: {
      label: `${logsState.summary?.line_count || 0} 行`,
      tone: logsState.summary?.line_count ? "success" : "warning",
    },
  };

  const previewWindowSummary = previewState.loading
    ? "正在准备全文预览。"
    : previewState.error
      ? previewState.error
      : previewState.content
        ? "正文已加载完成，建议在弹窗里查看。"
        : "选择文档后，可在弹窗中查看完整内容。";

  function renderOverlayWindow() {
    if (!activeOverlay) {
      return null;
    }

    if (typeof activeOverlay === "object" && activeOverlay.type === "note") {
      return (
        <FloatingWindow
          title={activeOverlay.title}
          subtitle={activeOverlay.subtitle}
          onClose={() => setActiveOverlay("")}
        >
          <div className="floating-window__stack">
            {activeOverlay.paragraphs.map((paragraph, index) => (
              <div className="floating-window__note" key={`${activeOverlay.title}-${index}`}>
                <p>{paragraph}</p>
              </div>
            ))}
          </div>
        </FloatingWindow>
      );
    }

    if (activeOverlay === "about") {
      return (
        <FloatingWindow
          title="工作台说明"
          subtitle="把说明收进窗口，主界面只保留必要状态。"
          onClose={() => setActiveOverlay("")}
        >
          <div className="floating-window__stack">
            <div className="floating-window__note">
              <strong>{demoMode ? "当前为本地演示模式" : "当前为完整模型模式"}</strong>
              <p>
                {demoMode
                  ? "未配置完整模型时，Aurora 会使用本地索引和抽取式回答，适合试用、联调和验收。"
                  : "当前已接入完整模型与 Embedding，可直接体验正式检索增强问答流程。"}
              </p>
            </div>
            <div className="floating-window__grid">
              <div className="floating-window__metric">
                <span>知识库</span>
                <strong>{kbStatus.ready ? "已就绪" : "待重建"}</strong>
              </div>
              <div className="floating-window__metric">
                <span>文档数</span>
                <strong>{formatNumber(documents.length)}</strong>
              </div>
              <div className="floating-window__metric">
                <span>切片数</span>
                <strong>{formatNumber(kbStatus.chunk_count)}</strong>
              </div>
              <div className="floating-window__metric">
                <span>会话数</span>
                <strong>{formatNumber(sessions.length)}</strong>
              </div>
            </div>
            <div className="floating-window__note">
              <strong>推荐顺序</strong>
              <p>先看文档，再重建知识库，最后用对话页验证结果。</p>
            </div>
            <div className="floating-window__tagblock">
              <strong>适合做什么</strong>
              <div className="floating-window__taglist">
                {WORKBENCH_SCENARIOS.map((item) => (
                  <span className="floating-window__tag" key={item}>
                    {item}
                  </span>
                ))}
              </div>
            </div>
          </div>
        </FloatingWindow>
      );
    }

    if (activeOverlay === "runtime") {
      return (
        <FloatingWindow
          title="运行时请求头"
          subtitle="只对当前请求生效，适合临时切模型或联调。"
          onClose={() => setActiveOverlay("")}
        >
          <div className="floating-window__stack">
            <div className="runtime-grid">
              <Field label="LLM 密钥">
                <input
                  className="input"
                  type="password"
                  value={runtimeConfig.llmApiKey}
                  onChange={(event) => handleRuntimeChange("llmApiKey", event.target.value)}
                  placeholder="仅本次请求生效"
                />
              </Field>
              <Field label="LLM 接口地址">
                <input
                  className="input"
                  type="text"
                  value={runtimeConfig.llmApiBase}
                  onChange={(event) => handleRuntimeChange("llmApiBase", event.target.value)}
                  placeholder="https://your-llm.example.com/v1"
                />
              </Field>
            </div>

            <div className="checkbox-row">
              <label className="checkbox-pill">
                <input
                  checked={runtimeConfig.useSameEmbeddingKey}
                  onChange={(event) => handleRuntimeChange("useSameEmbeddingKey", event.target.checked)}
                  type="checkbox"
                />
                Embedding 复用 LLM 密钥
              </label>
              <label className="checkbox-pill">
                <input
                  checked={runtimeConfig.useSameEmbeddingBase}
                  onChange={(event) => handleRuntimeChange("useSameEmbeddingBase", event.target.checked)}
                  type="checkbox"
                />
                Embedding 复用 LLM 地址
              </label>
            </div>

            {!runtimeConfig.useSameEmbeddingKey || !runtimeConfig.useSameEmbeddingBase ? (
              <div className="runtime-grid">
                {!runtimeConfig.useSameEmbeddingKey ? (
                  <Field label="Embedding 密钥">
                    <input
                      className="input"
                      type="password"
                      value={runtimeConfig.embeddingApiKey}
                      onChange={(event) => handleRuntimeChange("embeddingApiKey", event.target.value)}
                      placeholder="可选覆盖值"
                    />
                  </Field>
                ) : null}
                {!runtimeConfig.useSameEmbeddingBase ? (
                  <Field label="Embedding 接口地址">
                    <input
                      className="input"
                      type="text"
                      value={runtimeConfig.embeddingApiBase}
                      onChange={(event) => handleRuntimeChange("embeddingApiBase", event.target.value)}
                      placeholder="https://your-embedding.example.com/v1"
                    />
                  </Field>
                ) : null}
              </div>
            ) : null}

            <div className="toolbar">
              <button className="button" type="button" onClick={handleApplyRuntimeConfig}>
                应用
              </button>
              <button className="ghost-button" type="button" onClick={handleResetRuntimeConfig}>
                重置
              </button>
            </div>

            {runtimeMessage ? <p className="notice">{runtimeMessage}</p> : null}
          </div>
        </FloatingWindow>
      );
    }

    if (activeOverlay === "prompts") {
      return (
        <FloatingWindow
          title="问题起手式"
          subtitle="用更轻的方式提供示例问题，不再长期占住侧栏。"
          onClose={() => setActiveOverlay("")}
        >
          <div className="floating-window__stack">
            <div className="prompt-list prompt-list--window">
              {QUICK_PROMPTS.map((prompt) => (
                <button className="prompt-chip" key={prompt} type="button" onClick={() => handleUsePrompt(prompt)}>
                  {prompt}
                </button>
              ))}
            </div>
            <p className="muted-text">点击任意问题后会自动跳转到对话页，并填入输入框。</p>
          </div>
        </FloatingWindow>
      );
    }

    if (activeOverlay === "preview") {
      return (
        <FloatingWindow
          title={selectedDocument?.name || "文档预览"}
          subtitle="在独立窗口中查看正文，避免主界面被长文本压住。"
          onClose={() => setActiveOverlay("")}
          wide
        >
          <div className="floating-window__stack">
            {selectedDocument ? (
              <div className="preview-summary preview-summary--window">
                <span className="metric-chip">{String(selectedDocument.extension || "file").toUpperCase()}</span>
                <span className={`status-pill is-${selectedDocument.status}`}>{selectedDocument.status}</span>
                <strong className="preview-summary__name" title={selectedDocument.name}>
                  {selectedDocument.name}
                </strong>
              </div>
            ) : null}
            {previewState.loading ? (
              <div className="preview-box preview-box--muted">正在加载预览...</div>
            ) : previewState.error ? (
              <div className="preview-box preview-box--muted">{previewState.error}</div>
            ) : previewState.content ? (
              <div className="preview-box preview-box--content preview-box--window">{previewState.content}</div>
            ) : (
              <div className="preview-box preview-box--muted">从左侧选择文档后，这里会显示预览内容。</div>
            )}
          </div>
        </FloatingWindow>
      );
    }

    return null;
  }

  function renderOverviewSection() {
    const maxCategoryCount = Math.max(1, ...categoryCounts.map((item) => item.count));
    const maxExtensionCount = Math.max(1, ...extensionCounts.map((item) => item.count));

    return (
      <div className="section-stack">
        <SectionHeading
          icon="overview"
          eyebrow="总览"
          title="系统总览"
          description="快速查看知识库状态、文档规模和运行准备情况。"
          onDescriptionClick={() =>
            openNoteOverlay({
              title: "系统总览说明",
              subtitle: "把首屏说明收进弹窗，只保留当前最需要的状态与操作。",
              paragraphs: [
                "这里集中展示知识库是否可用、文档规模、模型准备状态和近期可执行动作，适合每次进入系统先做一次健康检查。",
              ],
            })
          }
          descriptionButtonLabel="查看系统总览说明"
          actions={
            <>
              <Badge tone={getStatusTone(overview.llm_api_ready)}>
                LLM {overview.llm_api_ready ? "已配置" : "未配置"}
              </Badge>
              <Badge tone={getStatusTone(overview.embedding_api_ready)}>
                Embedding {overview.embedding_api_ready ? "已配置" : "未配置"}
              </Badge>
              {kbStatus.current_job ? (
                <Badge tone={TERMINAL_JOB_STATUSES.includes(kbStatus.current_job.status) ? "success" : "accent"}>
                  任务 {kbStatus.current_job.status}
                </Badge>
              ) : null}
              <button className="ghost-button" type="button" onClick={refreshOverviewData}>
                {overviewLoading ? "刷新中..." : "刷新状态"}
              </button>
            </>
          }
        />

        {systemMessage ? <p className="notice is-error">{systemMessage}</p> : null}
        {runtimeMessage ? <p className="notice">{runtimeMessage}</p> : null}

        <div className="overview-snapshot">
          <CompactMetric label="源文档" value={formatNumber(overview.source_file_count)} detail="data 目录" />
          <CompactMetric label="切片" value={formatNumber(overview.chunk_count)} detail="索引片段" />
          <CompactMetric label="已入库" value={formatNumber(overview.indexed_file_count)} detail="同步完成" />
          <CompactMetric
            label="待更新"
            value={formatNumber(overview.changed_file_count + overview.pending_file_count)}
            detail={`Changed ${overview.changed_file_count} / Pending ${overview.pending_file_count}`}
          />
          <CompactMetric label="失败" value={formatNumber(overview.failed_file_count)} detail="待重试" />
          <CompactMetric label="日志" value={formatNumber(logsState.summary?.line_count || 0)} detail="app.log" />
        </div>

        <div className="split-layout">
          <Panel
            kicker="覆盖"
            title="主题分布"
            description="根据文件名推断知识主题，帮助快速判断当前资料覆盖面。"
            onDescriptionClick={() =>
              openNoteOverlay({
                title: "主题分布说明",
                subtitle: "快速判断知识资料覆盖面。",
                paragraphs: [
                  "这里会按文档主题做轻量聚合，帮助你判断当前上传的资料是不是已经覆盖目标测试场景。",
                ],
              })
            }
            descriptionButtonLabel="查看主题分布说明"
          >
            {categoryCounts.length ? (
              <div className="bar-list">
                {categoryCounts.slice(0, 8).map((item) => (
                  <div className="bar-row" key={item.label}>
                    <span className="bar-row__label">{item.label}</span>
                    <div className="bar-row__track">
                      <div className="bar-row__fill" style={{ width: `${(item.count / maxCategoryCount) * 100}%` }} />
                    </div>
                    <span className="bar-row__value">{item.count}</span>
                  </div>
                ))}
              </div>
            ) : (
              <EmptyState
                title="还没有源文档"
                description="先上传知识资料，这里的主题分布才会逐步形成。"
                action={
                  <button className="button" type="button" onClick={() => handleSwitchSection("knowledge")}>
                    前往知识库
                  </button>
                }
              />
            )}
          </Panel>

          <Panel
            kicker="格式"
            title="文件类型"
            description="用轻量方式展示当前知识库主要由哪些文件类型构成。"
            onDescriptionClick={() =>
              openNoteOverlay({
                title: "文件类型说明",
                subtitle: "看当前知识库由哪些资料格式组成。",
                paragraphs: [
                  "这里会按扩展名统计文档构成，方便快速确认 PDF、Markdown、脚本、表格等资料是否已经补齐。",
                ],
              })
            }
            descriptionButtonLabel="查看文件类型说明"
          >
            {extensionCounts.length ? (
              <div className="bar-list">
                {extensionCounts.slice(0, 8).map((item) => (
                  <div className="bar-row" key={item.label}>
                    <span className="bar-row__label">{item.label}</span>
                    <div className="bar-row__track">
                      <div className="bar-row__fill" style={{ width: `${(item.count / maxExtensionCount) * 100}%` }} />
                    </div>
                    <span className="bar-row__value">{item.count}</span>
                  </div>
                ))}
              </div>
            ) : (
              <EmptyState title="暂无格式统计" description="上传文档后，这里会自动汇总文件类型占比。" />
            )}
          </Panel>
        </div>

        <div className="split-layout">
          <Panel
            kicker="运行状态"
            title="系统快照"
            description="快速查看当前模型提供方和工作目录信息。"
            onDescriptionClick={() =>
              openNoteOverlay({
                title: "系统快照说明",
                subtitle: "环境与目录信息的快速核对区。",
                paragraphs: [
                  "这里用于确认当前接入的模型提供方，以及数据目录、索引目录、日志目录是否指向正确位置，适合排查环境配置问题。",
                ],
              })
            }
            descriptionButtonLabel="查看系统快照说明"
          >
            <div className="key-value-list">
              <div className="key-value"><span>版本</span><strong>{overview.app_version}</strong></div>
              <div className="key-value"><span>LLM 提供方</span><strong>{overview.llm_provider}</strong></div>
              <div className="key-value"><span>Embedding 提供方</span><strong>{overview.embedding_provider}</strong></div>
              <div className="key-value"><span>数据目录</span><strong>{overview.data_dir || "--"}</strong></div>
              <div className="key-value"><span>索引目录</span><strong>{overview.db_dir || "--"}</strong></div>
              <div className="key-value"><span>日志目录</span><strong>{overview.logs_dir || "--"}</strong></div>
            </div>
          </Panel>

          <Panel
            kicker="流程"
            title="推荐顺序"
            description="按这个顺序操作，会更顺畅地完成一次知识库问答验证。"
            onDescriptionClick={() =>
              openNoteOverlay({
                title: "推荐顺序说明",
                subtitle: "给首次试跑提供一条最短路径。",
                paragraphs: [
                  "推荐先确认资料，再临时联调模型参数，随后重建知识库，最后到对话页核对回答质量和引用来源。",
                ],
              })
            }
            descriptionButtonLabel="查看推荐顺序说明"
          >
            <div className="stack">
              <div className="key-value"><span>1.</span><strong>先检查已有资料，或上传新的测试文档。</strong></div>
              <div className="key-value"><span>2.</span><strong>临时联调用运行时请求头，长期配置放到设置页保存。</strong></div>
              <div className="key-value"><span>3.</span><strong>重建知识库后，到对话页验证回答质量与引用来源。</strong></div>
            </div>
            <div className="toolbar" style={{ marginTop: 16 }}>
              <button className="button" type="button" onClick={() => handleSwitchSection("knowledge")}>
                管理文档
              </button>
              <button className="ghost-button" type="button" onClick={() => handleSwitchSection("chat")}>
                进入对话
              </button>
            </div>
          </Panel>
        </div>

        <Panel kicker="近期" title="最近文档" description="最近更新的资料，方便快速确认内容是否已经进入项目。">
          {recentDocuments.length ? (
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>文件名</th>
                    <th>主题</th>
                    <th>类型</th>
                    <th>大小</th>
                    <th>更新时间</th>
                  </tr>
                </thead>
                <tbody>
                  {recentDocuments.map((item) => (
                    <tr key={item.path}>
                      <td>{item.name}</td>
                      <td>{item.theme || inferCategory(item.name)}</td>
                      <td>{String(item.extension || "").toUpperCase()}</td>
                      <td>{formatBytes(item.size_bytes)}</td>
                      <td>{formatDate(item.updated_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState title="暂无文档" description="先去知识库上传文件，这里的列表就会开始积累。" />
          )}
        </Panel>
      </div>
    );
  }

  function renderKnowledgeSection() {
    const currentJob = kbStatus.current_job;
    const jobActive = currentJob && !TERMINAL_JOB_STATUSES.includes(currentJob.status);

    return (
      <div className="section-stack">
        <SectionHeading
          icon="knowledge"
          eyebrow="知识库"
          title="知识库管理"
          description="上传源文件、维护主题与标签、观察文档状态，并把最新资料重新编入知识索引。"
          onDescriptionClick={() =>
            openNoteOverlay({
              title: "知识库管理说明",
              subtitle: "把大段介绍收起，首屏优先展示状态与操作按钮。",
              paragraphs: [
                "这里主要负责文档上传、筛选、重建索引、元数据维护和正文预览，是知识资料整理与入库的主工作区。",
              ],
            })
          }
          descriptionButtonLabel="查看知识库管理说明"
          actions={
            <>
              <Badge tone={getStatusTone(kbStatus.ready)}>
                {kbStatus.ready ? "索引已就绪" : "等待重建"}
              </Badge>
              {currentJob ? (
                <Badge tone={jobActive ? "accent" : currentJob.status === "completed_with_errors" ? "warning" : "success"}>
                  {currentJob.status}
                </Badge>
              ) : null}
              <button className="ghost-button" type="button" onClick={() => refreshKnowledgeData()}>
                {knowledgeLoading ? "刷新中..." : "刷新"}
              </button>
              {jobActive ? (
                <button className="danger-button" type="button" onClick={handleCancelKnowledgeBaseJob}>
                  取消任务
                </button>
              ) : (
                <button className="button" type="button" onClick={handleRebuildKnowledgeBase}>
                  开始重建
                </button>
              )}
            </>
          }
        />

        {knowledgeMessage ? <p className="notice">{knowledgeMessage}</p> : null}

        {currentJob ? (
          <Panel kicker="任务" title="知识库重建进度" description="异步任务会持续同步文档、切片和向量写入状态。">
            <div className="stack">
              <div className="key-value-list">
                <div className="key-value"><span>阶段</span><strong>{currentJob.stage || "--"}</strong></div>
                <div className="key-value"><span>状态</span><strong>{currentJob.status || "--"}</strong></div>
                <div className="key-value"><span>文档进度</span><strong>{formatNumber(currentJob.processed_documents || 0)} / {formatNumber(currentJob.total_documents || 0)}</strong></div>
                <div className="key-value"><span>切片进度</span><strong>{formatNumber(currentJob.processed_chunks || 0)} / {formatNumber(currentJob.total_chunks || 0)}</strong></div>
              </div>
              <div className="progress-bar">
                <div className="progress-bar__fill" style={{ width: formatPercent(currentJob.progress || 0) }} />
              </div>
              <div className="toolbar">
                <span className="metric-chip">进度 {formatPercent(currentJob.progress || 0)}</span>
                {currentJob.started_at ? <span className="metric-chip">开始 {formatDate(currentJob.started_at)}</span> : null}
                {currentJob.finished_at ? <span className="metric-chip">结束 {formatDate(currentJob.finished_at)}</span> : null}
              </div>
              <p className="muted-text">{currentJob.message || "等待任务状态更新。"}</p>
              {currentJob.error ? <p className="notice is-error">{currentJob.error}</p> : null}
            </div>
          </Panel>
        ) : null}

        <Panel
          kicker="状态"
          title="当前知识库快照"
          description="在改动文档之前，先快速确认索引状态与当前选中项。"
          className="panel--dense"
          onDescriptionClick={() =>
            openNoteOverlay({
              title: "当前知识库快照说明",
              subtitle: "把摘要压缩成更轻的状态条，不再占用过高首屏空间。",
              paragraphs: [
                "这里用于快速确认文档规模、切片数量、索引同步状态，以及当前正在编辑或预览的文档。",
              ],
            })
          }
          descriptionButtonLabel="查看知识库快照说明"
        >
          <div className="knowledge-snapshot">
            <CompactMetric label="文档数" value={formatNumber(documents.length)} />
            <CompactMetric label="切片数" value={formatNumber(kbStatus.chunk_count)} />
            <CompactMetric label="已入库" value={formatNumber(kbStatus.indexed_count)} />
            <CompactMetric
              label="待更新"
              value={formatNumber(kbStatus.changed_count + kbStatus.pending_count)}
              detail={`Changed ${kbStatus.changed_count} / Pending ${kbStatus.pending_count}`}
            />
            <CompactMetric label="失败" value={formatNumber(kbStatus.failed_count)} />

            <div className="knowledge-snapshot__selected">
              <div className="knowledge-snapshot__selected-head">
                <span className="knowledge-snapshot__selected-label">当前选中</span>
                {selectedDocument ? (
                  <div className="knowledge-snapshot__selected-meta">
                    <span className={`status-pill is-${selectedDocument.status}`}>{selectedDocument.status}</span>
                    <span className="metric-chip">{String(selectedDocument.extension || "file").toUpperCase()}</span>
                  </div>
                ) : (
                  <span className="metric-chip">未选择</span>
                )}
              </div>
              <strong className="knowledge-snapshot__selected-name" title={selectedDocument?.name || "--"}>
                {selectedDocument ? selectedDocument.name : "点击下方文档开始预览"}
              </strong>
              <p className="knowledge-snapshot__selected-note">
                {selectedDocument ? "用于预览、重命名、主题标签维护。" : "选中文档后，这里会显示当前操作对象。"}
              </p>
            </div>
          </div>
        </Panel>

        <div className="split-layout">
          <Panel
            kicker="文档区"
            title="源文档列表"
            description="支持筛选、批量选择、上传和删除，适合集中处理知识资料。"
            actions={
              <div className="selection-summary">
                <Badge tone="accent">已选 {selectedDocumentPaths.length} 个</Badge>
                <button className="ghost-button" type="button" onClick={handleToggleAllVisibleDocuments}>
                  {allVisibleDocumentsSelected ? "取消当前筛选项" : "全选当前筛选项"}
                </button>
              </div>
            }
          >
            <div className="stack">
              <div className="document-toolbar-grid">
                <Field label="搜索文档">
                  <input
                    className="input"
                    type="text"
                    value={documentSearch}
                    onChange={(event) => setDocumentSearch(event.target.value)}
                    placeholder="按文件名、路径、类型或推断主题筛选"
                  />
                </Field>

                <Field label="状态筛选">
                  <select
                    className="select"
                    value={documentStatusFilter}
                    onChange={(event) => setDocumentStatusFilter(event.target.value)}
                  >
                    <option value="">全部状态</option>
                    <option value="indexed">已入库</option>
                    <option value="changed">待更新</option>
                    <option value="pending">未入库</option>
                    <option value="failed">失败</option>
                  </select>
                </Field>

                <Field label="主题筛选">
                  <select
                    className="select"
                    value={documentThemeFilter}
                    onChange={(event) => setDocumentThemeFilter(event.target.value)}
                  >
                    <option value="">全部主题</option>
                    {documentThemes.map((theme) => (
                      <option key={theme} value={theme}>
                        {theme}
                      </option>
                    ))}
                  </select>
                </Field>

                <div className="field document-upload-field">
                  <div className="document-upload-field__head">
                    <span className="field__label">上传文件</span>
                    <Badge tone="accent">
                      {uploadFiles.length ? `待上传 ${uploadFiles.length} 个` : "未选择文件"}
                    </Badge>
                  </div>
                  <input
                    ref={uploadInputRef}
                    className="upload-picker__input"
                    type="file"
                    multiple
                    onChange={(event) => setUploadFiles(Array.from(event.target.files || []))}
                  />
                  <div className="upload-picker">
                    <button
                      className="ghost-button upload-picker__trigger"
                      type="button"
                      onClick={() => uploadInputRef.current?.click()}
                    >
                      <span className="upload-picker__icon">
                        <SectionIcon kind="knowledge" />
                      </span>
                      选择文件
                    </button>
                    {uploadFiles.length ? (
                      <button className="ghost-button" type="button" onClick={handleClearUploadFiles}>
                        清空
                      </button>
                    ) : null}
                  </div>
                  <p className="field__hint">支持一次选择多个文件，文件名会在下方清单中显示。</p>
                  <div className={`upload-file-list ${uploadFiles.length ? "" : "is-empty"}`.trim()}>
                    {uploadFiles.length ? (
                      uploadFiles.map((file) => (
                        <span className="upload-file-chip" key={`${file.name}-${file.size}-${file.lastModified}`}>
                          {file.name}
                        </span>
                      ))
                    ) : (
                      <span className="upload-file-placeholder">等待选择一个或多个源文件</span>
                    )}
                  </div>
                </div>
              </div>

              <div className="document-actions">
                <button className="button" type="button" disabled={!uploadFiles.length} onClick={handleUploadDocuments}>
                  上传文件 {uploadFiles.length ? `(${uploadFiles.length})` : ""}
                </button>
                <button className="ghost-button" type="button" onClick={handleDeleteDocuments}>
                  删除所选
                </button>
                <button className="ghost-button" type="button" disabled={metadataSaving} onClick={() => handleSaveDocumentMetadata(selectedDocumentPaths)}>
                  批量保存主题/标签
                </button>
              </div>

              {filteredDocuments.length ? (
                <div className="table-wrap">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>选择</th>
                        <th>文件名</th>
                        <th>状态</th>
                        <th>主题</th>
                        <th>标签</th>
                        <th>类型</th>
                        <th>引用</th>
                        <th>大小</th>
                        <th>更新时间</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredDocuments.map((item) => (
                        <tr
                          key={item.path}
                          className={item.path === selectedDocumentPath ? "is-selected-row" : ""}
                        >
                          <td>
                            <input
                              checked={selectedDocumentPaths.includes(item.path)}
                              onChange={() => handleToggleDocument(item.path)}
                              type="checkbox"
                            />
                          </td>
                          <td>
                            <button className="data-row-button" type="button" onClick={() => handleSelectDocument(item.path)}>
                              {item.name}
                            </button>
                          </td>
                          <td><span className={`status-pill is-${item.status}`}>{item.status}</span></td>
                          <td>{item.theme || inferCategory(item.name)}</td>
                          <td>{item.tags?.length ? item.tags.join(", ") : "--"}</td>
                          <td>{String(item.extension || "").toUpperCase()}</td>
                          <td>{formatNumber(item.citation_count || 0)}</td>
                          <td>{formatBytes(item.size_bytes)}</td>
                          <td>{formatDate(item.updated_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <EmptyState title="没有匹配的文档" description="调整筛选条件，或者上传新的资料。" />
              )}
            </div>
          </Panel>

          <Panel
            kicker="预览"
            title="文档预览与元数据"
            description="右侧只保留摘要与编辑操作，正文改为弹窗查看。"
            actions={
              <button
                className="ghost-button"
                type="button"
                disabled={!selectedDocument}
                onClick={() => setActiveOverlay("preview")}
              >
                打开预览窗口
              </button>
            }
          >
            <div className="stack">
              {selectedDocument ? (
                <div className="preview-summary">
                  <span className="metric-chip">{String(selectedDocument.extension || "file").toUpperCase()}</span>
                  <span className={`status-pill is-${selectedDocument.status}`}>{selectedDocument.status}</span>
                  <strong className="preview-summary__name" title={selectedDocument.name}>
                    {selectedDocument.name}
                  </strong>
                </div>
              ) : null}
              <Field label="重命名" hint="建议尽量保留原始扩展名。">
                <input
                  className="input"
                  type="text"
                  value={renameDraft}
                  onChange={(event) => setRenameDraft(event.target.value)}
                  disabled={!selectedDocument}
                  placeholder="请先选择一个文档"
                />
              </Field>
              <button className="secondary-button" type="button" disabled={!selectedDocument} onClick={handleRenameDocument}>
                重命名当前文件
              </button>
              <Field label="主题" hint="会影响图谱归类与知识库管理筛选。">
                <input
                  className="input"
                  type="text"
                  value={documentThemeDraft}
                  onChange={(event) => setDocumentThemeDraft(event.target.value)}
                  disabled={!selectedDocument}
                  placeholder="例如：Python Testing"
                />
              </Field>
              <Field label="标签" hint="使用英文逗号分隔，适合标记平台、模块或问题类型。">
                <input
                  className="input"
                  type="text"
                  value={documentTagsDraft}
                  onChange={(event) => setDocumentTagsDraft(event.target.value)}
                  disabled={!selectedDocument}
                  placeholder="adb, android, 排障"
                />
              </Field>
              <div className="toolbar">
                <button className="button" type="button" disabled={!selectedDocument || metadataSaving} onClick={() => handleSaveDocumentMetadata()}>
                  {metadataSaving ? "保存中..." : "保存当前文档元数据"}
                </button>
                {selectedDocumentPaths.length > 1 ? (
                  <button className="ghost-button" type="button" disabled={metadataSaving} onClick={() => handleSaveDocumentMetadata(selectedDocumentPaths)}>
                    应用到已选 {selectedDocumentPaths.length} 个文档
                  </button>
                ) : null}
              </div>
              {selectedDocument ? (
                <div className="key-value-list">
                  <div className="key-value"><span>当前主题</span><strong>{selectedDocument.theme || "--"}</strong></div>
                  <div className="key-value"><span>当前标签</span><strong>{selectedDocument.tags?.length ? selectedDocument.tags.join(", ") : "--"}</strong></div>
                  <div className="key-value"><span>引用次数</span><strong>{formatNumber(selectedDocument.citation_count || 0)}</strong></div>
                  <div className="key-value"><span>最近入库</span><strong>{selectedDocument.last_indexed_at ? formatDate(selectedDocument.last_indexed_at) : "--"}</strong></div>
                </div>
              ) : null}
              {selectedDocument?.last_error ? <p className="notice is-error">{selectedDocument.last_error}</p> : null}
              <div className="subtle-divider" />
              <div className="preview-launcher-card">
                <div className="preview-launcher-card__copy">
                  <strong>正文预览</strong>
                  <p>{previewWindowSummary}</p>
                </div>
                <button
                  className="button preview-launcher-card__button"
                  type="button"
                  disabled={!selectedDocument}
                  onClick={() => setActiveOverlay("preview")}
                >
                  查看全文
                </button>
              </div>
            </div>
          </Panel>
        </div>
      </div>
    );
  }

  function renderChatSection() {
    const citationCount = lastAssistantMessage?.citations?.length || 0;
    const sessionSummary = activeSession
      ? `${activeMessages.length} 条消息 · 最近更新 ${formatDate(activeSession.updatedAt)}`
      : "当前还没有可用会话。";
    const sessionDescription = sessions.length > 1
      ? `当前共 ${sessions.length} 个会话，可切换不同主题继续追问。`
      : "先从一个问题开始，后续追问都会沉淀在当前会话里。";

    return (
      <div className="section-stack">
        <SectionHeading
          icon="chat"
          eyebrow="对话"
          title="对话工作台"
          description="按会话组织问答过程，保留引用来源与耗时，适合持续追问。"
          actions={
            <>
              <Field label="召回数量">
                <input
                  className="input"
                  type="number"
                  min="1"
                  max="20"
                  value={chatTopK}
                  onChange={(event) => setChatTopK(event.target.value)}
                />
              </Field>
              <button className="ghost-button" type="button" disabled={chatBusy} onClick={handleCreateSession}>
                新建会话
              </button>
            </>
          }
        />

        {chatMessage ? <p className="notice">{chatMessage}</p> : null}

        <Panel kicker="对话台" title="流式对话工作区" description="问题逐字返回，引用与耗时会跟随答案一起保留下来。">
          <div className="session-layout">
            <aside className="session-rail">
              <div className="session-rail__header">
                <div>
                  <p className="session-rail__eyebrow">会话列表</p>
                  <h3 className="session-rail__title">把不同主题的验证过程分开保存</h3>
                  <p className="session-rail__description">{sessionDescription}</p>
                </div>
                <div className="session-rail__actions">
                  <button className="button" type="button" disabled={chatBusy} onClick={handleCreateSession}>
                    新建会话
                  </button>
                  <button className="ghost-button" type="button" disabled={!activeSession} onClick={handleClearCurrentSession}>
                    清空当前会话
                  </button>
                </div>
              </div>

              <div className="session-list">
                {sessions.map((session) => (
                  <div key={session.id} className={`session-card ${session.id === activeSession?.id ? "is-active" : ""}`}>
                    <button className="data-row-button" type="button" onClick={() => setActiveSessionId(session.id)}>
                      <p className="session-card__title">{session.title}</p>
                      <p className="session-card__meta">
                        {session.messages.length} 条消息 · {formatDate(session.updatedAt)}
                      </p>
                    </button>
                    <div className="session-card__footer">
                      <button
                        className="ghost-button"
                        type="button"
                        disabled={chatBusy && session.id === activeSession?.id}
                        onClick={() => handleDeleteSession(session.id)}
                      >
                        删除会话
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </aside>

            <div className="chat-shell">
              <div className="chat-shell__top">
                <div className="chat-summary">
                  <p className="chat-summary__eyebrow">当前会话</p>
                  <h3 className="chat-summary__title">{activeSession?.title || "未命名会话"}</h3>
                  <p className="chat-summary__description">{sessionSummary}</p>
                </div>
                <div className="chat-summary__meta">
                  <span className="metric-chip">召回 {chatTopK || 0} 条</span>
                  <span className="metric-chip">{citationCount ? `最近引用 ${citationCount} 条` : "等待提问"}</span>
                </div>
              </div>

              <div className="chat-stage">
                <div className="chat-stream" ref={chatScrollRef}>
                  {activeMessages.length ? (
                    <div className="chat-list">
                      {activeMessages.map((message) => (
                        <article
                          className={`chat-bubble ${message.role === "user" ? "is-user" : "is-assistant"}`}
                          key={message.id}
                        >
                          <div className="chat-bubble__header">
                            <div className="chat-bubble__identity">
                              <span className="chat-bubble__role">{message.role === "user" ? "你" : "Aurora 助手"}</span>
                              <span className="chat-bubble__time">{formatDate(message.createdAt)}</span>
                            </div>
                            {message.streaming ? <Badge tone="accent">生成中</Badge> : null}
                          </div>
                          <div className="chat-bubble__content">
                            {message.content || (message.streaming ? "正在生成回答..." : "")}
                          </div>
                          {message.meta ? (
                            <div className="chat-bubble__meta">
                              {message.meta.retrieved_count ? <span className="metric-chip">命中 {message.meta.retrieved_count}</span> : null}
                              {message.meta.retrieval_ms ? <span className="metric-chip">检索 {formatDuration(message.meta.retrieval_ms)}</span> : null}
                              {message.meta.generation_ms ? <span className="metric-chip">生成 {formatDuration(message.meta.generation_ms)}</span> : null}
                              {message.meta.total_ms ? <span className="metric-chip">总耗时 {formatDuration(message.meta.total_ms)}</span> : null}
                              {message.meta.confidence ? <span className="metric-chip">置信度 {formatConfidence(message.meta.confidence)}</span> : null}
                              {message.meta.rewritten_question ? <span className="metric-chip">已改写检索</span> : null}
                            </div>
                          ) : null}
                          {message.meta?.rewritten_question ? (
                            <div className="chat-bubble__meta-block">
                              <strong>检索改写</strong>
                              <p>{message.meta.rewritten_question}</p>
                            </div>
                          ) : null}
                          {message.meta?.retrieval_query ? (
                            <div className="chat-bubble__meta-block">
                              <strong>检索 Query</strong>
                              <p>{message.meta.retrieval_query}</p>
                            </div>
                          ) : null}
                          {message.citations?.length ? (
                            <div className="citation-list">
                              {message.citations.map((citation, index) => (
                                <div className="citation-card" key={`${message.id}-${index}`}>
                                  <div className="citation-card__head">
                                    <strong>{citation.file_name}</strong>
                                    <span className="metric-chip">Score {formatConfidence(citation.score)}</span>
                                  </div>
                                  <div className="citation-card__meta">
                                    {citation.theme ? <span className="metric-chip">{citation.theme}</span> : null}
                                    {citation.tags?.length ? <span className="metric-chip">{citation.tags.join(", ")}</span> : null}
                                  </div>
                                  <p>{citation.snippet}</p>
                                  {citation.full_text ? (
                                    <details className="citation-card__details">
                                      <summary>展开原始片段</summary>
                                      <div className="citation-card__full">{citation.full_text}</div>
                                    </details>
                                  ) : null}
                                </div>
                              ))}
                            </div>
                          ) : null}
                        </article>
                      ))}
                    </div>
                  ) : (
                    <EmptyState title="先开始一次问答" description="可以点击推荐问题，也可以直接输入你自己的测试场景问题。" />
                  )}
                </div>
              </div>

              {citationCount ? (
                <div className="source-strip">
                  <p className="source-strip__label">最近引用</p>
                  <div className="pill-list">
                    {lastAssistantMessage.citations.slice(0, 5).map((citation, index) => (
                      <span className="metric-chip" key={`${citation.file_name}-${index}`}>
                        {truncateText(citation.file_name, 18)}
                      </span>
                    ))}
                  </div>
                </div>
              ) : null}

              <div className="composer">
                <div className="composer__header">
                  <div>
                    <p className="composer__eyebrow">提问区</p>
                    <h3 className="composer__title">继续追问，或直接发起新的测试问题</h3>
                  </div>
                  <p className="muted-text">回车发送，Shift + Enter 换行</p>
                </div>

                {!activeMessages.length ? (
                  <div className="composer__prompts">
                    <p className="composer__hint">可以先从这些问题开始：</p>
                    <div className="prompt-list">
                      {QUICK_PROMPTS.map((prompt) => (
                        <button className="prompt-chip" key={prompt} type="button" onClick={() => setChatInput(prompt)}>
                          {prompt}
                        </button>
                      ))}
                    </div>
                  </div>
                ) : null}

                <textarea
                  className="textarea"
                  rows={5}
                  value={chatInput}
                  placeholder="输入问题后按回车发送，Shift + Enter 换行。"
                  onChange={(event) => setChatInput(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && !event.shiftKey) {
                      event.preventDefault();
                      handleSendMessage();
                    }
                  }}
                />
                <div className="composer__footer">
                  <p className="muted-text">当前问答会沿用左侧的运行时请求头，但不会改写 .env。</p>
                  <div className="toolbar">
                    {chatBusy ? (
                      <button className="danger-button" type="button" onClick={handleStopMessage}>
                        停止生成
                      </button>
                    ) : null}
                    <button className="button" type="button" disabled={chatBusy} onClick={handleSendMessage}>
                      {chatBusy ? "生成中..." : "发送问题"}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </Panel>
      </div>
    );
  }

  function renderGraphSection() {
    return (
      <div className="section-stack">
        <SectionHeading
          icon="graph"
          eyebrow="图谱"
          title="动态知识图谱"
          description="实时布局当前文档、主题和文件类型，悬停即可查看节点信息。"
          actions={
            <>
              <Badge tone={graph.nodes.length ? "success" : "warning"}>
                {graph.nodes.length ? `${graph.nodes.length} 个节点` : "暂无节点"}
              </Badge>
              <button className="ghost-button" type="button" onClick={refreshGraphData}>
                {graphLoading ? "刷新中..." : "刷新图谱"}
              </button>
            </>
          }
        />

        {graphMessage ? <p className="notice is-error">{graphMessage}</p> : null}

        <Panel kicker="结构" title="图谱概览" description="重点节点和关系数量一目了然。">
          <div className="graph-card">
            <div className="stack">
              <GraphPreview graph={graph} />
              <div className="graph-legend">
                <span className="legend-chip"><span className="legend-dot" style={{ background: "#14a6a8" }} />根节点</span>
                <span className="legend-chip"><span className="legend-dot" style={{ background: "#3fb57e" }} />主题</span>
                <span className="legend-chip"><span className="legend-dot" style={{ background: "#63bfd3" }} />文件类型</span>
                <span className="legend-chip"><span className="legend-dot" style={{ background: "#0d6971" }} />文档</span>
              </div>
            </div>

            <div className="stack">
              <div className="stats-grid">
                <StatCard label="文档节点" value={formatNumber(graph.summary?.document_count || 0)} />
                <StatCard label="主题数量" value={formatNumber(graph.summary?.category_count || 0)} />
                <StatCard label="文件类型" value={formatNumber(graph.summary?.file_type_count || 0)} />
                <StatCard label="关系数量" value={formatNumber(graph.summary?.edge_count || 0)} />
              </div>

              <Panel kicker="重点" title="关键节点" description="按节点尺寸排序，快速看到最突出的内容。">
                {graphHighlights.length ? (
                  <div className="key-value-list">
                    {graphHighlights.map((node) => (
                      <div className="key-value" key={node.id}>
                        <span>{translateNodeType(node.node_type)}</span>
                        <strong>{node.label}</strong>
                      </div>
                    ))}
                  </div>
                ) : (
                  <EmptyState title="暂无重点节点" description="上传文件并重建索引后，这里会显示更有代表性的节点。" />
                )}
              </Panel>
            </div>
          </div>
        </Panel>
      </div>
    );
  }

  function renderSettingsSection() {
    return (
      <div className="section-stack">
        <SectionHeading
          icon="settings"
          eyebrow="设置"
          title="配置中心"
          description="把长期参数保存到 .env，并统一检查模型与服务配置。"
          actions={
            <>
              <button className="ghost-button" type="button" disabled={settingsLoading || settingsTestState.loading} onClick={handleTestSettings}>
                {settingsTestState.loading ? "测试中..." : "测试连通性"}
              </button>
              <button className="button" type="button" disabled={settingsLoading} onClick={handleSaveSettings}>
                {settingsLoading ? "保存中..." : "保存到 .env"}
              </button>
            </>
          }
        />

        {settingsMessage ? (
          <p className={`notice ${Object.keys(settingsErrors).length ? "is-error" : ""}`}>{settingsMessage}</p>
        ) : null}

        <Panel
          kicker="快捷预设"
          title="模型厂商辅助填写"
          description="点击下方图标按钮，可自动填入推荐的提供方、模型名与接口地址，后续只需要补密钥即可。"
        >
          <div className="provider-presets-grid">
            <div className="provider-preset-group">
              <div className="provider-preset-group__header">
                <p className="panel__kicker">LLM 预设</p>
                <p className="muted-text">适合快速切换聊天模型厂商。</p>
              </div>
              <div className="provider-preset-list">
                {LLM_PRESET_KEYS.map((presetKey) => {
                  const preset = PROVIDER_PRESETS[presetKey];
                  return (
                    <button
                      className="provider-preset"
                      key={`llm-${preset.key}`}
                      type="button"
                      onClick={() => handleApplyProviderPreset("llm", preset.key)}
                    >
                      <ProviderMark badge={preset.badge} />
                      <span className="provider-preset__copy">
                        <strong>{preset.label}</strong>
                        <span>{preset.description}</span>
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>

            <div className="provider-preset-group">
              <div className="provider-preset-group__header">
                <p className="panel__kicker">Embedding 预设</p>
                <p className="muted-text">常用向量模型也可以通过图标快速带入。</p>
              </div>
              <div className="provider-preset-list">
                {EMBEDDING_PRESET_KEYS.map((presetKey) => {
                  const preset = PROVIDER_PRESETS[presetKey];
                  return (
                    <button
                      className="provider-preset"
                      key={`embedding-${preset.key}`}
                      type="button"
                      onClick={() => handleApplyProviderPreset("embedding", preset.key)}
                    >
                      <ProviderMark badge={preset.badge} />
                      <span className="provider-preset__copy">
                        <strong>{preset.label}</strong>
                        <span>{preset.description}</span>
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          </div>
        </Panel>

        {settingsTestState.report ? (
          <Panel kicker="联通性" title="配置测试结果" description="保存前先验证 LLM 与 Embedding 是否真的可用。">
            <div className="stats-grid">
              <StatCard
                label="LLM"
                value={settingsTestState.report.llm?.ok ? "通过" : "失败"}
                detail={`${Math.round(settingsTestState.report.llm?.latency_ms || 0)} ms`}
              />
              <StatCard
                label="Embedding"
                value={settingsTestState.report.embedding?.ok ? "通过" : "失败"}
                detail={`${Math.round(settingsTestState.report.embedding?.latency_ms || 0)} ms`}
              />
              <StatCard
                label="检测时间"
                value={settingsTestState.report.checked_at || "--"}
                valueClassName="is-compact"
              />
            </div>
            <div className="stack" style={{ marginTop: 16 }}>
              <div className={`notice ${settingsTestState.report.llm?.ok ? "" : "is-error"}`}>{settingsTestState.report.llm?.message}</div>
              <div className={`notice ${settingsTestState.report.embedding?.ok ? "" : "is-error"}`}>{settingsTestState.report.embedding?.message}</div>
            </div>
          </Panel>
        ) : null}

        <div className="settings-sections">
          {SETTINGS_SECTIONS.map((section) => (
            <Panel key={section.title} kicker="配置" title={section.title} description={section.description}>
              <div className="two-column">
                {section.fields.map((field) => (
                  <Field key={field.key} label={field.label} hint={field.hint} error={settingsErrors[field.key]}>
                    {field.type === "select" ? (
                      <select
                        className="select"
                        value={settingsForm[field.key]}
                        onChange={(event) => handleSettingsChange(field.key, event.target.value)}
                      >
                        {field.options.map((option) => (
                          <option key={getFieldOptionValue(option)} value={getFieldOptionValue(option)}>
                            {getFieldOptionLabel(option)}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <input
                        className="input"
                        type={field.type}
                        step={field.step}
                        placeholder={field.placeholder}
                        value={settingsForm[field.key]}
                        onChange={(event) => handleSettingsChange(field.key, event.target.value)}
                      />
                    )}
                  </Field>
                ))}
              </div>
            </Panel>
          ))}
        </div>
      </div>
    );
  }

  function renderLogsSection() {
    return (
      <div className="section-stack">
        <SectionHeading
          icon="logs"
          eyebrow="日志"
          title="日志检索"
          description="快速筛选最近运行输出。"
          actions={
            <>
              <button className="ghost-button" type="button" onClick={handleSearchLogs}>
                {logsLoading ? "加载中..." : "刷新日志"}
              </button>
              <button className="danger-button" type="button" onClick={handleClearLogs}>
                清空日志
              </button>
            </>
          }
        />

        {logsMessage ? <p className="notice">{logsMessage}</p> : null}

        <Panel
          kicker="筛选与概况"
          title="日志查询"
          description="把筛选条件和文件概况放在一起，减少纵向占位。"
          className="panel--dense"
        >
          <div className="logs-query-grid">
            <Field label="级别">
              <select
                className="select"
                value={logsFilters.level}
                onChange={(event) => setLogsFilters((current) => ({ ...current, level: event.target.value }))}
              >
                <option value="">全部</option>
                <option value="DEBUG">DEBUG</option>
                <option value="INFO">INFO</option>
                <option value="WARNING">WARNING</option>
                <option value="ERROR">ERROR</option>
              </select>
            </Field>
            <Field label="关键字">
              <input
                className="input"
                type="text"
                value={logsFilters.keyword}
                onChange={(event) => setLogsFilters((current) => ({ ...current, keyword: event.target.value }))}
                placeholder="chat、rebuild、error"
              />
            </Field>
            <Field label="数量上限">
              <input
                className="input"
                type="number"
                min="1"
                max="1000"
                value={logsFilters.limit}
                onChange={(event) => setLogsFilters((current) => ({ ...current, limit: event.target.value }))}
              />
            </Field>
            <Field label="开始时间">
              <input
                className="input"
                type="datetime-local"
                value={normalizeDateTimeInput(logsFilters.start_time)}
                onChange={(event) => setLogsFilters((current) => ({ ...current, start_time: event.target.value }))}
              />
            </Field>
            <Field label="结束时间">
              <input
                className="input"
                type="datetime-local"
                value={normalizeDateTimeInput(logsFilters.end_time)}
                onChange={(event) => setLogsFilters((current) => ({ ...current, end_time: event.target.value }))}
              />
            </Field>
          </div>

          <div className="logs-inline-summary">
            <CompactMetric label="存在" value={logsState.summary?.exists ? "是" : "否"} />
            <CompactMetric label="大小" value={formatBytes(logsState.summary?.size_bytes || 0)} />
            <CompactMetric label="行数" value={formatNumber(logsState.summary?.line_count || 0)} />
            <div className="logs-inline-path" title={logsState.summary?.path || "--"}>
              <span className="logs-inline-path__label">文件路径</span>
              <strong className="logs-inline-path__value">{logsState.summary?.path || "--"}</strong>
            </div>
          </div>
        </Panel>

        <Panel kicker="输出" title="原始日志" description="固定高度，可在面板内滚动查看。">
          {logsState.lines?.length ? (
            <div className="scroll-panel scroll-panel--logs">
              <div className="log-output">{logsState.lines.join("")}</div>
            </div>
          ) : (
            <EmptyState title="当前没有命中日志" description="可以调整筛选条件，或者等待新的后端输出。" />
          )}
        </Panel>
      </div>
    );
  }

  let sectionContent = renderOverviewSection();
  if (activeSection === "knowledge") sectionContent = renderKnowledgeSection();
  if (activeSection === "chat") sectionContent = renderChatSection();
  if (activeSection === "graph") sectionContent = renderGraphSection();
  if (activeSection === "settings") sectionContent = renderSettingsSection();
  if (activeSection === "logs") sectionContent = renderLogsSection();

  return (
    <div className="app-shell">
      <div className="ambient-orb ambient-orb--one" />
      <div className="ambient-orb ambient-orb--two" />

      <div className="app-frame">
        <header className="hero">
          <div className="hero__content">
            <div className="hero__topline">
              <div className="hero__lead">
                <div className="hero__brand-mark">
                  <SectionIcon kind="overview" />
                </div>
                <div>
                  <p className="hero__eyebrow">Aurora 控制台</p>
                  <h1 className="hero__title">软件测试知识工作台</h1>
                </div>
              </div>

              <div className="hero__toolbelt">
                <UtilityLauncher
                  icon="overview"
                  label="说明"
                  hint="工作台定位"
                  compact
                  iconOnly
                  onClick={() => setActiveOverlay("about")}
                />
                <UtilityLauncher
                  icon="settings"
                  label="请求头"
                  hint="临时联调"
                  compact
                  iconOnly
                  onClick={() => setActiveOverlay("runtime")}
                />
                <UtilityLauncher
                  icon="chat"
                  label="起手式"
                  hint="示例问题"
                  compact
                  iconOnly
                  onClick={() => setActiveOverlay("prompts")}
                />
              </div>
            </div>

            <div className="hero__statusline">
              <span className={`hero__mode-pill ${demoMode ? "is-demo" : "is-ready"}`}>
                {demoMode ? "本地演示模式" : "完整模型模式"}
              </span>
              <button className="hero__status-trigger" type="button" onClick={() => setActiveOverlay("about")}>
                <SectionIcon kind="info" />
                <span>{demoMode ? "查看演示模式说明" : "查看当前模式说明"}</span>
              </button>
            </div>

            <div className="hero__summary-rail">
              {WORKBENCH_SCENARIOS.map((item) => (
                <span className="hero__summary-chip" key={item}>
                  {item}
                </span>
              ))}
            </div>
          </div>

          <div className="hero__stats">
            <div className="mini-stat"><p className="mini-stat__label">版本</p><p className="mini-stat__value">{overview.app_version}</p></div>
            <div className="mini-stat"><p className="mini-stat__label">知识库状态</p><p className="mini-stat__value">{kbStatus.ready ? "已就绪" : "待重建"}</p></div>
            <div className="mini-stat"><p className="mini-stat__label">文档数</p><p className="mini-stat__value">{formatNumber(documents.length)}</p></div>
            <div className="mini-stat"><p className="mini-stat__label">会话数</p><p className="mini-stat__value">{formatNumber(sessions.length)}</p></div>
          </div>
        </header>

        <div className="workspace">
          <aside className="sidebar">
            <div className="sidebar-card">
              <div className="sidebar-card__head">
                <h2 className="sidebar-card__title">导航</h2>
                <div className="sidebar-card__head-actions">
                  <IconButton icon="info" label="查看工作台说明" onClick={() => setActiveOverlay("about")} />
                  <span className="sidebar-card__pill">快捷</span>
                </div>
              </div>
              <div className="nav-list">
                {NAV_ITEMS.map((item) => (
                  <button
                    key={item.id}
                    className={`nav-item ${activeSection === item.id ? "is-active" : ""}`}
                    type="button"
                    onClick={() => handleSwitchSection(item.id)}
                  >
                    <span>
                      <span className="nav-item__title">{item.label}</span>
                      <span className="nav-item__hint">{item.hint}</span>
                    </span>
                    <span className={`nav-item__status is-${navStatuses[item.id].tone}`}>
                      {navStatuses[item.id].label}
                    </span>
                  </button>
                ))}
              </div>
              <div className="sidebar-utility-strip">
                <UtilityLauncher
                  icon="settings"
                  label="运行时请求头"
                  hint="弹窗编辑"
                  iconOnly
                  onClick={() => setActiveOverlay("runtime")}
                />
                <UtilityLauncher
                  icon="chat"
                  label="问题起手式"
                  hint="弹窗选择"
                  iconOnly
                  onClick={() => setActiveOverlay("prompts")}
                />
                <UtilityLauncher
                  icon="overview"
                  label="模式说明"
                  hint="状态与用法"
                  iconOnly
                  onClick={() => setActiveOverlay("about")}
                />
              </div>
            </div>
          </aside>

          <main className="content">{sectionContent}</main>
        </div>
      </div>

      {renderOverlayWindow()}
    </div>
  );
}
