import { useMemo, type ReactNode } from "react";

import { cn } from "@/lib/utils";


type MarkdownBlock =
  | { type: "heading"; key: string; depth: number; text: string }
  | { type: "paragraph"; key: string; text: string }
  | { type: "list"; key: string; ordered: boolean; items: string[] }
  | { type: "quote"; key: string; text: string }
  | { type: "code"; key: string; language: string; text: string }
  | { type: "rule"; key: string };

interface MarkdownPreviewProps {
  value?: string | null;
  fallback?: string;
  className?: string;
}

export function MarkdownPreview({ value, fallback = "暂无预览内容。", className }: MarkdownPreviewProps) {
  const blocks = useMemo(() => parseMarkdownBlocks(value ?? ""), [value]);

  if (!blocks.length) {
    return <p className={cn("text-sm leading-7 text-slate-500", className)}>{fallback}</p>;
  }

  return (
    <div className={cn("space-y-3 text-sm leading-7 text-slate-700", className)}>
      {blocks.map((block) => renderBlock(block))}
    </div>
  );
}

function parseMarkdownBlocks(value: string): MarkdownBlock[] {
  const lines = value.replace(/\r\n/g, "\n").replace(/\r/g, "\n").split("\n");
  const blocks: MarkdownBlock[] = [];
  let paragraphLines: string[] = [];
  let quoteLines: string[] = [];
  let listBlock: { ordered: boolean; items: string[] } | null = null;
  let codeFence: { language: string; lines: string[] } | null = null;

  const nextKey = (type: MarkdownBlock["type"]) => `${type}-${blocks.length}`;

  const flushParagraph = () => {
    if (!paragraphLines.length) {
      return;
    }
    blocks.push({
      type: "paragraph",
      key: nextKey("paragraph"),
      text: paragraphLines.join(" ").trim(),
    });
    paragraphLines = [];
  };

  const flushQuote = () => {
    if (!quoteLines.length) {
      return;
    }
    blocks.push({
      type: "quote",
      key: nextKey("quote"),
      text: quoteLines.join("\n").trim(),
    });
    quoteLines = [];
  };

  const flushList = () => {
    if (!listBlock) {
      return;
    }
    blocks.push({
      type: "list",
      key: nextKey("list"),
      ordered: listBlock.ordered,
      items: listBlock.items,
    });
    listBlock = null;
  };

  const flushOpenBlocks = () => {
    flushParagraph();
    flushQuote();
    flushList();
  };

  lines.forEach((line) => {
    const trimmed = line.trim();

    if (codeFence) {
      if (trimmed.startsWith("```")) {
        blocks.push({
          type: "code",
          key: nextKey("code"),
          language: codeFence.language,
          text: codeFence.lines.join("\n"),
        });
        codeFence = null;
        return;
      }
      codeFence.lines.push(line);
      return;
    }

    const codeFenceMatch = trimmed.match(/^```([a-zA-Z0-9_-]*)/);
    if (codeFenceMatch) {
      flushOpenBlocks();
      codeFence = { language: codeFenceMatch[1] ?? "", lines: [] };
      return;
    }

    if (!trimmed) {
      flushOpenBlocks();
      return;
    }

    if (/^([-*_])\1{2,}$/.test(trimmed)) {
      flushOpenBlocks();
      blocks.push({ type: "rule", key: nextKey("rule") });
      return;
    }

    const headingMatch = trimmed.match(/^(#{1,6})\s+(.+)$/);
    if (headingMatch) {
      flushOpenBlocks();
      blocks.push({
        type: "heading",
        key: nextKey("heading"),
        depth: headingMatch[1].length,
        text: headingMatch[2].trim(),
      });
      return;
    }

    const quoteMatch = trimmed.match(/^>\s?(.*)$/);
    if (quoteMatch) {
      flushParagraph();
      flushList();
      quoteLines.push(quoteMatch[1]);
      return;
    }
    flushQuote();

    const unorderedMatch = trimmed.match(/^[-*+]\s+(.+)$/);
    const orderedMatch = trimmed.match(/^\d+[.)]\s+(.+)$/);
    const listMatch = unorderedMatch ?? orderedMatch;
    if (listMatch) {
      const ordered = Boolean(orderedMatch);
      flushParagraph();
      if (listBlock && listBlock.ordered !== ordered) {
        flushList();
      }
      listBlock ??= { ordered, items: [] };
      listBlock.items.push(listMatch[1].trim());
      return;
    }

    flushList();
    paragraphLines.push(trimmed);
  });

  const openCodeFence = codeFence as { language: string; lines: string[] } | null;
  if (openCodeFence) {
    blocks.push({
      type: "code",
      key: nextKey("code"),
      language: openCodeFence.language,
      text: openCodeFence.lines.join("\n"),
    });
  }
  flushOpenBlocks();

  return blocks.filter((block) => block.type !== "paragraph" || block.text.length > 0);
}

function renderBlock(block: MarkdownBlock) {
  switch (block.type) {
    case "heading":
      return renderHeading(block);
    case "paragraph":
      return (
        <p key={block.key} className="break-words text-slate-700">
          {renderInline(block.text)}
        </p>
      );
    case "list": {
      const ListTag = block.ordered ? "ol" : "ul";
      return (
        <ListTag
          key={block.key}
          className={cn("space-y-1 pl-5 text-slate-700", block.ordered ? "list-decimal" : "list-disc")}
        >
          {block.items.map((item, index) => (
            <li key={`${block.key}-${index}`} className="break-words pl-1">
              {renderInline(item)}
            </li>
          ))}
        </ListTag>
      );
    }
    case "quote":
      return (
        <blockquote key={block.key} className="rounded-lg border-l-4 border-teal-300 bg-teal-50/70 px-4 py-3 text-slate-700">
          {block.text.split("\n").map((line, index) => (
            <p key={`${block.key}-${index}`} className={index > 0 ? "mt-2" : undefined}>
              {renderInline(line)}
            </p>
          ))}
        </blockquote>
      );
    case "code":
      return (
        <pre key={block.key} className="snow-scrollbar overflow-auto rounded-lg bg-slate-950 p-4 text-xs leading-6 text-slate-100">
          <code>{block.text || " "}</code>
        </pre>
      );
    case "rule":
      return <div key={block.key} className="border-t border-teal-100" />;
    default:
      return null;
  }
}

function renderHeading(block: Extract<MarkdownBlock, { type: "heading" }>) {
  const depth = Math.min(Math.max(block.depth, 1), 6);
  const className = cn(
    "break-words font-semibold tracking-normal text-slate-950",
    depth === 1 && "text-xl leading-8",
    depth === 2 && "text-lg leading-7",
    depth === 3 && "text-base leading-7",
    depth >= 4 && "text-sm leading-6",
  );

  if (depth === 1) {
    return (
      <h1 key={block.key} className={className}>
        {renderInline(block.text)}
      </h1>
    );
  }
  if (depth === 2) {
    return (
      <h2 key={block.key} className={className}>
        {renderInline(block.text)}
      </h2>
    );
  }
  if (depth === 3) {
    return (
      <h3 key={block.key} className={className}>
        {renderInline(block.text)}
      </h3>
    );
  }
  return (
    <h4 key={block.key} className={className}>
      {renderInline(block.text)}
    </h4>
  );
}

function renderInline(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const inlinePattern = /(`[^`]+`|\*\*[^*]+\*\*|__[^_]+__|\[[^\]]+\]\((?:https?:\/\/|mailto:)[^)]+\))/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = inlinePattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(text.slice(lastIndex, match.index));
    }

    const token = match[0];
    const key = `inline-${match.index}-${nodes.length}`;
    const linkMatch = token.match(/^\[([^\]]+)\]\(((?:https?:\/\/|mailto:)[^)]+)\)$/);

    if (token.startsWith("`")) {
      nodes.push(
        <code key={key} className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[0.92em] text-slate-900">
          {token.slice(1, -1)}
        </code>,
      );
    } else if (token.startsWith("**") || token.startsWith("__")) {
      nodes.push(
        <strong key={key} className="font-semibold text-slate-950">
          {token.slice(2, -2)}
        </strong>,
      );
    } else if (linkMatch) {
      nodes.push(
        <a
          key={key}
          href={linkMatch[2]}
          target={linkMatch[2].startsWith("http") ? "_blank" : undefined}
          rel={linkMatch[2].startsWith("http") ? "noreferrer" : undefined}
          className="font-medium text-teal-700 underline decoration-teal-300 underline-offset-4 hover:text-teal-900"
        >
          {linkMatch[1]}
        </a>,
      );
    } else {
      nodes.push(token);
    }

    lastIndex = inlinePattern.lastIndex;
  }

  if (lastIndex < text.length) {
    nodes.push(text.slice(lastIndex));
  }

  return nodes;
}
