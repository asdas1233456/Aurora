import { describe, expect, it } from "vitest";

import { parseSseChunk, parseSseFrame } from "@/lib/stream";


describe("parseSseFrame", () => {
  it("extracts event and data", () => {
    expect(
      parseSseFrame("event: meta\ndata: {\"type\":\"meta\"}"),
    ).toEqual({
      event: "meta",
      data: "{\"type\":\"meta\"}",
    });
  });

  it("returns null for blank frames", () => {
    expect(parseSseFrame("")).toBeNull();
  });
});

describe("parseSseChunk", () => {
  it("splits full frames and preserves the trailing partial chunk", () => {
    const parsed = parseSseChunk("event: delta\ndata: one\n\nevent: done\ndata: two");

    expect(parsed.events).toEqual([
      {
        event: "delta",
        data: "one",
      },
    ]);
    expect(parsed.remainder).toBe("event: done\ndata: two");
  });
});
