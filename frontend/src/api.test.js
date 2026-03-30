import { afterEach, describe, expect, it, vi } from "vitest";

import {
  buildRuntimeHeaders,
  getDocumentPreview,
  getWorkspaceBootstrap,
  rebuildKnowledgeBase,
  removeDocuments,
  renameDocument,
  updateDocumentMetadata,
} from "./api";


afterEach(() => {
  vi.restoreAllMocks();
});

describe("api helpers", () => {
  it("builds runtime headers from overrides", () => {
    expect(
      buildRuntimeHeaders({
        llmApiKey: " llm-key ",
        embeddingApiKey: " embed-key ",
        llmApiBase: " https://llm.example.com/v1 ",
        embeddingApiBase: " https://embed.example.com/v1 ",
        useSameEmbeddingKey: false,
        useSameEmbeddingBase: false,
      })
    ).toEqual({
      "X-LLM-API-Key": "llm-key",
      "X-Embedding-API-Key": "embed-key",
      "X-LLM-API-Base": "https://llm.example.com/v1",
      "X-Embedding-API-Base": "https://embed.example.com/v1",
      "X-Use-Same-Embedding-Key": "false",
      "X-Use-Same-Embedding-Base": "false",
    });
  });

  it("keeps same-embedding flags by default", () => {
    expect(buildRuntimeHeaders({})).toEqual({
      "X-Use-Same-Embedding-Key": "true",
      "X-Use-Same-Embedding-Base": "true",
    });
  });

  it("requests document preview by document_id", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => ({ document_id: "doc-1", preview: "preview" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await getDocumentPreview("doc-1");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/documents/preview?document_id=doc-1",
      expect.objectContaining({ method: "GET" })
    );
  });

  it("requests the combined workspace bootstrap payload", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => ({ overview: {}, knowledge_status: {}, documents: [], graph: {} }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await getWorkspaceBootstrap({ llmApiKey: "demo-key" });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/system/bootstrap",
      expect.objectContaining({
        method: "GET",
        headers: expect.objectContaining({
          "X-LLM-API-Key": "demo-key",
        }),
      })
    );
  });

  it("sends document_id payloads for rename and metadata actions", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => ({}),
    });
    vi.stubGlobal("fetch", fetchMock);

    await renameDocument("doc-9", "renamed.md");
    await updateDocumentMetadata(["doc-9", "doc-10"], { theme: "Regression" });
    await removeDocuments(["doc-9", "doc-10"]);

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/v1/documents/rename",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({ document_id: "doc-9", new_name: "renamed.md" }),
      })
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/v1/documents/metadata",
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({ document_ids: ["doc-9", "doc-10"], theme: "Regression" }),
      })
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "/api/v1/documents",
      expect.objectContaining({
        method: "DELETE",
        body: JSON.stringify({ document_ids: ["doc-9", "doc-10"] }),
      })
    );
  });

  it("sends knowledge-base rebuild mode payloads", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => ({}),
    });
    vi.stubGlobal("fetch", fetchMock);

    await rebuildKnowledgeBase({}, undefined, "reset");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/knowledge-base/rebuild",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ mode: "reset" }),
      })
    );
  });
});
