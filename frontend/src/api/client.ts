import { parseSseChunk } from "@/lib/stream";
import type {
  ChatMessagesResponse,
  ChatRequestPayload,
  ChatSessionsResponse,
  ChatStreamEvent,
  DocumentPreview,
  DocumentSummary,
  GraphPayload,
  KnowledgeBaseJob,
  KnowledgeStatusPayload,
  LogsPayload,
  RuntimeHelpPayload,
  SettingsPayload,
  SettingsTestPayload,
  StreamHandlers,
  WorkspaceBootstrap,
} from "@/types/api";


const API_PREFIX = "/api/v1";

export class ApiError extends Error {
  details: unknown;

  constructor(message: string, details: unknown = null) {
    super(message);
    this.name = "ApiError";
    this.details = details;
  }
}

function createQueryString(params: Record<string, string | number | undefined | null>) {
  const searchParams = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === null || value === undefined || value === "") {
      return;
    }
    searchParams.set(key, String(value));
  });
  const query = searchParams.toString();
  return query ? `?${query}` : "";
}

async function toApiError(response: Response) {
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  const detail = typeof payload === "object" && payload !== null && "detail" in payload
    ? (payload as { detail: unknown }).detail
    : payload;
  if (typeof detail === "string" && detail.trim()) {
    return new ApiError(detail.trim(), payload);
  }
  if (typeof detail === "object" && detail !== null) {
    const record = detail as Record<string, unknown>;
    return new ApiError(String(record.message ?? response.statusText), record);
  }
  return new ApiError(`${response.status} ${response.statusText}`.trim(), payload);
}

async function request<T>(path: string, init?: RequestInit) {
  const response = await fetch(`${API_PREFIX}${path}`, init);
  if (!response.ok) {
    throw await toApiError(response);
  }
  return response.json() as Promise<T>;
}

export function getWorkspaceBootstrap() {
  return request<WorkspaceBootstrap>("/system/bootstrap");
}

export function getKnowledgeStatus() {
  return request<KnowledgeStatusPayload>("/knowledge-base/status");
}

export function getDocuments() {
  return request<DocumentSummary[]>("/documents");
}

export function getDocumentPreview(documentId: string) {
  return request<DocumentPreview>(`/documents/preview${createQueryString({ document_id: documentId })}`);
}

export function uploadDocuments(files: File[]) {
  const formData = new FormData();
  files.forEach((file) => formData.append("files", file));
  return request<{ saved_count: number; saved_files: string[] }>("/documents/upload", {
    method: "POST",
    body: formData,
  });
}

export function renameDocument(documentId: string, newName: string) {
  return request<{
    document_id: string;
    new_name: string;
    old_relative_path: string;
    new_relative_path: string;
  }>("/documents/rename", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ document_id: documentId, new_name: newName }),
  });
}

export function updateDocumentMetadata(documentIds: string[], updates: { theme?: string; tags?: string[] }) {
  return request<DocumentSummary[]>("/documents/metadata", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ document_ids: documentIds, ...updates }),
  });
}

export function deleteDocuments(documentIds: string[]) {
  return request<{ deleted_count: number; deleted_ids: string[]; missing_ids: string[] }>("/documents", {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ document_ids: documentIds }),
  });
}

export function rebuildKnowledgeBase(mode: "sync" | "scan" | "reset") {
  return request<KnowledgeBaseJob>("/knowledge-base/rebuild", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode }),
  });
}

export function getGraph(filters: { theme?: string; type?: string }) {
  return request<GraphPayload>(`/graph${createQueryString(filters)}`);
}

export function getSettings() {
  return request<SettingsPayload>("/settings");
}

export function saveSettings(values: Record<string, unknown>) {
  return request<{ message: string }>("/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ values }),
  });
}

export function testSettings(values: Record<string, unknown>) {
  return request<SettingsTestPayload>("/settings/test", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ values }),
  });
}

export function getRuntimeHelp() {
  return request<RuntimeHelpPayload>("/runtime/config");
}

export function getLogs(filters: Record<string, string | number>) {
  return request<LogsPayload>(`/logs${createQueryString(filters)}`);
}

export function clearLogs() {
  return request<{ message: string }>("/logs", { method: "DELETE" });
}

export function listChatSessions(params: { query?: string; status?: string; limit?: number }) {
  return request<ChatSessionsResponse>(`/chat/sessions${createQueryString(params)}`);
}

export function getChatSessionMessages(sessionId: string) {
  return request<ChatMessagesResponse>(`/chat/sessions/${sessionId}/messages`);
}

export function renameChatSession(sessionId: string, title: string) {
  return request<{ session: ChatMessagesResponse["session"] }>(`/chat/sessions/${sessionId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
}

function dispatchEvent(event: ChatStreamEvent, handlers: StreamHandlers) {
  if (event.type === "meta") {
    handlers.onMeta?.(event);
    return;
  }
  if (event.type === "delta") {
    handlers.onDelta?.(event);
    return;
  }
  if (event.type === "done") {
    handlers.onDone?.(event);
    return;
  }
  handlers.onError?.(event);
}

export async function streamChat(
  payload: ChatRequestPayload,
  handlers: StreamHandlers,
  signal?: AbortSignal,
) {
  const response = await fetch(`${API_PREFIX}/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify(payload),
    signal,
  });

  if (!response.ok) {
    throw await toApiError(response);
  }

  const reader = response.body?.getReader();
  if (!reader) {
    throw new ApiError("当前环境不支持流式响应。");
  }

  const decoder = new TextDecoder();
  let buffer = "";
  let finalEvent: ChatStreamEvent | null = null;

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
    const parsed = parseSseChunk(buffer);
    buffer = parsed.remainder;

    parsed.events.forEach((entry) => {
      if (!entry.data) {
        return;
      }
      const event = JSON.parse(entry.data) as ChatStreamEvent;
      finalEvent = event;
      dispatchEvent(event, handlers);
    });

    if (done) {
      break;
    }
  }

  return finalEvent;
}
