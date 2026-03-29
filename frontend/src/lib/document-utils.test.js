import { describe, expect, it } from "vitest";

import {
  formatConfidence,
  formatPercent,
  inferCategory,
  parseTagsInput,
  stringifyTags,
} from "./document-utils";

describe("document-utils", () => {
  it("parses unique tags from comma input", () => {
    expect(parseTagsInput("adb, android, adb,  排障 ")).toEqual(["adb", "android", "排障"]);
  });

  it("stringifies tag arrays", () => {
    expect(stringifyTags(["python", "testing"])).toBe("python, testing");
  });

  it("infers category from numbered file names", () => {
    expect(inferCategory("01_python_testing.md")).toBe("Python Testing");
  });

  it("formats percent and confidence values", () => {
    expect(formatPercent(0.487)).toBe("49%");
    expect(formatConfidence(0.487)).toBe("0.49");
    expect(formatConfidence(0)).toBe("--");
  });
});
