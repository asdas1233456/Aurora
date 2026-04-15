import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MarkdownPreview } from "./markdown-preview";


describe("MarkdownPreview", () => {
  it("renders markdown headings and lists without exposing heading markers", () => {
    render(
      <MarkdownPreview
        value={[
          "# 一级标题",
          "",
          "## 二级标题",
          "",
          "正文 **重点** `code`",
          "",
          "- 第一项",
          "- 第二项",
        ].join("\n")}
      />,
    );

    expect(screen.getByRole("heading", { level: 1, name: "一级标题" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "二级标题" })).toBeInTheDocument();
    expect(screen.queryByText("## 二级标题")).not.toBeInTheDocument();
    expect(screen.getByText("重点")).toHaveClass("font-semibold");
    expect(screen.getByRole("list")).toBeInTheDocument();
    expect(screen.getByText("第一项")).toBeInTheDocument();
  });

  it("keeps fenced code as code while rendering surrounding text", () => {
    render(
      <MarkdownPreview
        value={[
          "调试步骤",
          "",
          "```ts",
          "const value = 1;",
          "```",
        ].join("\n")}
      />,
    );

    expect(screen.getByText("调试步骤")).toBeInTheDocument();
    expect(screen.getByText("const value = 1;").tagName).toBe("CODE");
  });
});
