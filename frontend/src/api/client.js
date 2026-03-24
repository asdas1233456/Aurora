import { getRuntimeHeaders } from "./runtimeConfig";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "";

async function request(path, options = {}) {
  const headers = {
    ...getRuntimeHeaders(),
    ...(options.headers || {}),
  };

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed: ${response.status}`);
  }

  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return response.json();
  }

  return response.text();
}

export function getOverview() {
  return request("/api/v1/system/overview");
}

export function getDocuments() {
  return request("/api/v1/documents");
}

export function getDocumentPreview(path) {
  return request(`/api/v1/documents/preview?path=${encodeURIComponent(path)}`);
}

export async function uploadDocuments(files) {
  const formData = new FormData();
  files.forEach((file) => formData.append("files", file));
  return request("/api/v1/documents/upload", {
    method: "POST",
    body: formData,
  });
}

export function getKnowledgeBaseStatus() {
  return request("/api/v1/knowledge-base/status");
}

export function rebuildKnowledgeBase() {
  return request("/api/v1/knowledge-base/rebuild", {
    method: "POST",
  });
}

export function askQuestion(payload) {
  return request("/api/v1/chat/ask", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
}

export async function streamQuestion(payload, handlers = {}) {
  const response = await fetch(`${API_BASE}/api/v1/chat/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...getRuntimeHeaders(),
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok || !response.body) {
    const text = await response.text();
    throw new Error(text || `Stream request failed: ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (!line.trim()) {
        continue;
      }
      const payload = JSON.parse(line);
      if (payload.type === "meta" && handlers.onMeta) {
        handlers.onMeta(payload);
      }
      if (payload.type === "delta" && handlers.onDelta) {
        handlers.onDelta(payload);
      }
      if (payload.type === "done" && handlers.onDone) {
        handlers.onDone(payload);
      }
      if (payload.type === "error" && handlers.onError) {
        handlers.onError(payload);
      }
    }
  }
}

export function getLogs(limit = 120) {
  return request(`/api/v1/logs?limit=${limit}`);
}

export function clearLogs() {
  return request("/api/v1/logs", {
    method: "DELETE",
  });
}

export function getSettings() {
  return request("/api/v1/settings");
}

export function updateSettings(values) {
  return request("/api/v1/settings", {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ values }),
  });
}

export function getHealth() {
  return request("/health");
}
