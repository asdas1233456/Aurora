const API_PREFIX = "/api/v1";

export class ApiError extends Error {
  constructor(message, details = null) {
    super(message);
    this.name = "ApiError";
    this.details = details;
  }
}

export function buildRuntimeHeaders(runtimeConfig = {}) {
  const headers = {};

  if (runtimeConfig.llmApiKey?.trim()) {
    headers["X-LLM-API-Key"] = runtimeConfig.llmApiKey.trim();
  }
  if (runtimeConfig.embeddingApiKey?.trim()) {
    headers["X-Embedding-API-Key"] = runtimeConfig.embeddingApiKey.trim();
  }
  if (runtimeConfig.llmApiBase?.trim()) {
    headers["X-LLM-API-Base"] = runtimeConfig.llmApiBase.trim();
  }
  if (runtimeConfig.embeddingApiBase?.trim()) {
    headers["X-Embedding-API-Base"] = runtimeConfig.embeddingApiBase.trim();
  }

  headers["X-Use-Same-Embedding-Key"] = String(runtimeConfig.useSameEmbeddingKey ?? true);
  headers["X-Use-Same-Embedding-Base"] = String(runtimeConfig.useSameEmbeddingBase ?? true);

  return headers;
}

async function toApiError(response) {
  let payload = null;

  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  const detail = payload?.detail ?? payload;
  if (typeof detail === "string" && detail.trim()) {
    return new ApiError(detail.trim());
  }

  if (detail && typeof detail === "object") {
    return new ApiError(
      String(detail.message || payload?.message || response.statusText || "请求失败"),
      detail.errors || detail
    );
  }

  if (typeof payload?.message === "string" && payload.message.trim()) {
    return new ApiError(payload.message.trim());
  }

  return new ApiError(`${response.status} ${response.statusText}`.trim());
}

async function request(path, options = {}) {
  const {
    method = "GET",
    body,
    headers = {},
    runtimeConfig,
    signal,
  } = options;

  const requestHeaders = {
    ...buildRuntimeHeaders(runtimeConfig),
    ...headers,
  };

  let requestBody = body;
  if (requestBody && !(requestBody instanceof FormData) && typeof requestBody !== "string") {
    requestBody = JSON.stringify(requestBody);
    if (!requestHeaders["Content-Type"]) {
      requestHeaders["Content-Type"] = "application/json";
    }
  }

  const response = await fetch(`${API_PREFIX}${path}`, {
    method,
    headers: requestHeaders,
    body: requestBody,
    signal,
  });

  if (!response.ok) {
    throw await toApiError(response);
  }

  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return response.json();
  }

  return response.text();
}

function makeSearchParams(values = {}) {
  const searchParams = new URLSearchParams();

  Object.entries(values).forEach(([key, value]) => {
    if (value === null || value === undefined || value === "") {
      return;
    }
    searchParams.set(key, String(value));
  });

  const query = searchParams.toString();
  return query ? `?${query}` : "";
}

export function getOverview(runtimeConfig, signal) {
  return request("/system/overview", { runtimeConfig, signal });
}

export function getWorkspaceBootstrap(runtimeConfig, signal) {
  return request("/system/bootstrap", { runtimeConfig, signal });
}

export function getKnowledgeStatus(runtimeConfig, signal) {
  return request("/knowledge-base/status", { runtimeConfig, signal });
}

export function getDocuments(signal) {
  return request("/documents", { signal });
}

export function getDocumentPreview(documentId, signal) {
  return request(`/documents/preview${makeSearchParams({ document_id: documentId })}`, { signal });
}

export function uploadDocumentFiles(files, signal) {
  const formData = new FormData();
  files.forEach((file) => {
    formData.append("files", file);
  });

  return request("/documents/upload", {
    method: "POST",
    body: formData,
    signal,
  });
}

export function renameDocument(documentId, newName, signal) {
  return request("/documents/rename", {
    method: "PUT",
    body: {
      document_id: documentId,
      new_name: newName,
    },
    signal,
  });
}

export function updateDocumentMetadata(documentIds, updates = {}, signal) {
  return request("/documents/metadata", {
    method: "PATCH",
    body: {
      document_ids: documentIds,
      ...updates,
    },
    signal,
  });
}

export function removeDocuments(documentIds, signal) {
  return request("/documents", {
    method: "DELETE",
    body: { document_ids: documentIds },
    signal,
  });
}

export function rebuildKnowledgeBase(runtimeConfig, signal, mode = "sync") {
  return request("/knowledge-base/rebuild", {
    method: "POST",
    body: { mode },
    runtimeConfig,
    signal,
  });
}

export function scanKnowledgeBase(runtimeConfig, signal) {
  return request("/knowledge-base/scan", {
    method: "POST",
    runtimeConfig,
    signal,
  });
}

export function resetKnowledgeBase(runtimeConfig, signal) {
  return request("/knowledge-base/reset", {
    method: "POST",
    runtimeConfig,
    signal,
  });
}

export function getCurrentKnowledgeJob(signal) {
  return request("/knowledge-base/jobs/current", { signal });
}

export function cancelKnowledgeJob(jobId, signal) {
  return request(`/knowledge-base/jobs/${jobId}/cancel`, {
    method: "POST",
    signal,
  });
}

export function getKnowledgeGraph(signal) {
  return request("/knowledge-graph", { signal });
}

export function getSettings(signal) {
  return request("/settings", { signal });
}

export function saveSettings(values, signal) {
  return request("/settings", {
    method: "PUT",
    body: { values },
    signal,
  });
}

export function testSettings(values, signal) {
  return request("/settings/test", {
    method: "POST",
    body: { values },
    signal,
  });
}

export function getLogs(filters = {}, signal) {
  return request(`/logs${makeSearchParams(filters)}`, { signal });
}

export function clearLogs(signal) {
  return request("/logs", {
    method: "DELETE",
    signal,
  });
}

function emitStreamEvent(event, handlers) {
  handlers.onEvent?.(event);

  if (event.type === "meta") {
    handlers.onMeta?.(event);
  }
  if (event.type === "delta") {
    handlers.onDelta?.(event);
  }
  if (event.type === "done") {
    handlers.onDone?.(event);
  }
  if (event.type === "error") {
    handlers.onError?.(event);
  }
}

export async function streamChat(payload, runtimeConfig, handlers = {}, signal) {
  const response = await fetch(`${API_PREFIX}/chat/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/x-ndjson",
      ...buildRuntimeHeaders(runtimeConfig),
    },
    body: JSON.stringify(payload),
    signal,
  });

  if (!response.ok) {
    throw await toApiError(response);
  }

  const reader = response.body?.getReader();
  if (!reader) {
    throw new ApiError("当前浏览器环境不支持流式响应。");
  }

  const decoder = new TextDecoder();
  let buffer = "";

  const flushBuffer = (rawChunk) => {
    buffer += rawChunk;
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    lines.forEach((line) => {
      const normalized = line.trim();
      if (!normalized) {
        return;
      }

      try {
        emitStreamEvent(JSON.parse(normalized), handlers);
      } catch {
        // Ignore malformed stream fragments.
      }
    });
  };

  while (true) {
    const { done, value } = await reader.read();
    flushBuffer(decoder.decode(value || new Uint8Array(), { stream: !done }));

    if (done) {
      break;
    }
  }

  if (buffer.trim()) {
    try {
      emitStreamEvent(JSON.parse(buffer.trim()), handlers);
    } catch {
      // Ignore trailing fragments.
    }
  }
}
