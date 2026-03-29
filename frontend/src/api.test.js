import { describe, expect, it } from "vitest";

import { buildRuntimeHeaders } from "./api";

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
});
