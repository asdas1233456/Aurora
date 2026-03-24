const STORAGE_KEY = "ai-kb-agent-runtime-config";

export function getRuntimeConfigStorage() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

export function saveRuntimeConfigStorage(value) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
}

export function clearRuntimeConfigStorage() {
  localStorage.removeItem(STORAGE_KEY);
}

export function getRuntimeHeaders() {
  const config = getRuntimeConfigStorage();
  const headers = {};

  if (config.llmApiKey) {
    headers["X-LLM-API-Key"] = config.llmApiKey;
  }

  if (config.useSameEmbeddingKey) {
    headers["X-Use-Same-Embedding-Key"] = "true";
  } else if (config.embeddingApiKey) {
    headers["X-Embedding-API-Key"] = config.embeddingApiKey;
  }

  if (config.llmApiBase) {
    headers["X-LLM-API-Base"] = config.llmApiBase;
  }

  if (config.useSameEmbeddingBase) {
    headers["X-Use-Same-Embedding-Base"] = "true";
  } else if (config.embeddingApiBase) {
    headers["X-Embedding-API-Base"] = config.embeddingApiBase;
  }

  return headers;
}
