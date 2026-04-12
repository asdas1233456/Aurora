import { memo } from "react";

import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";

import { cn } from "@/lib/utils";


export type AuroraGraphNodeData = Record<string, unknown> & {
  label: string;
  kind: string;
  nodeType: string;
  accent: string;
  surface: string;
  glow: string;
  description: string;
  secondaryText?: string;
  metric: string;
  badge: string;
};

type AuroraGraphNodeRecord = Node<AuroraGraphNodeData, "aurora">;

export const AuroraGraphNode = memo(function AuroraGraphNode({
  data,
  selected,
}: NodeProps<AuroraGraphNodeRecord>) {
  const nodeData = data;
  const isRoot = nodeData.kind === "root";
  const isCategory = nodeData.kind === "category";
  const isFileType = nodeData.kind === "file_type";
  const isDocument = nodeData.kind === "document";

  return (
    <div
      className={cn(
        "aurora-graph-node relative overflow-hidden border border-white/85 text-left transition-[box-shadow,border-color] duration-150",
        isRoot && "rounded-[26px] px-4 py-4",
        isCategory && "rounded-[22px] px-3.5 py-3",
        isFileType && "rounded-[999px] px-3 py-2.5",
        isDocument && "rounded-[18px] px-3 py-2.5",
        selected
          ? "border-teal-200"
          : "border-white/80",
      )}
      style={{
        background: nodeData.surface,
        boxShadow: selected
          ? `0 10px 22px ${nodeData.glow}, inset 0 1px 0 rgba(255,255,255,0.82)`
          : `0 6px 18px ${nodeData.glow}, inset 0 1px 0 rgba(255,255,255,0.76)`,
      }}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="!h-2 !w-2 !border-0 !bg-white/90"
      />
      <Handle
        type="source"
        position={Position.Right}
        className="!h-2 !w-2 !border-0 !bg-white/90"
      />

      <div
        className={cn(
          "pointer-events-none absolute top-0 opacity-75",
          isRoot ? "inset-x-7 h-12 rounded-b-[999px]" : "inset-x-5 h-10 rounded-b-[999px]",
        )}
        style={{ background: `linear-gradient(180deg, ${nodeData.accent}22, transparent)` }}
      />

      <div className="relative">
        {isRoot ? (
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <div className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: nodeData.accent }} />
              <p className="text-[10px] uppercase tracking-[0.26em] text-slate-500">{nodeData.nodeType}</p>
            </div>
            <p className="text-lg font-semibold leading-6 text-slate-900">{nodeData.label}</p>
            <div className="flex items-center justify-between gap-3 border-t border-white/65 pt-3">
              <span className="text-[10px] uppercase tracking-[0.2em] text-slate-400">{nodeData.badge}</span>
              <span className="text-xs font-medium text-slate-700">{nodeData.metric}</span>
            </div>
          </div>
        ) : isFileType ? (
          <div className="flex items-center gap-2.5">
            <div className="h-2 w-2 rounded-full" style={{ backgroundColor: nodeData.accent }} />
            <div className="min-w-0">
              <p className="text-[10px] uppercase tracking-[0.22em] text-slate-400">{nodeData.badge}</p>
              <p className="truncate text-sm font-semibold uppercase tracking-[0.04em] text-slate-900">{nodeData.label}</p>
            </div>
          </div>
        ) : (
          <>
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="text-[10px] uppercase tracking-[0.24em] text-slate-500">
                  {nodeData.nodeType}
                </p>
                <p className={cn(
                  "mt-1.5 font-semibold text-slate-900",
                  isDocument ? "line-clamp-1 text-[0.88rem] leading-5" : "line-clamp-2 text-[0.95rem] leading-5",
                )}>
                  {nodeData.label}
                </p>
                {nodeData.secondaryText ? (
                  <p className={cn("text-slate-500", isDocument ? "mt-1 text-[10px] truncate" : "mt-1 truncate text-[11px]")}>
                    {nodeData.secondaryText}
                  </p>
                ) : null}
              </div>
              <div
                className="shrink-0 rounded-full px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.18em]"
                style={{
                  backgroundColor: `${nodeData.accent}18`,
                  color: nodeData.accent,
                }}
              >
                {nodeData.badge}
              </div>
            </div>

            <div className={cn(
              "flex items-center justify-between gap-3 border-t border-white/65",
              isDocument ? "mt-2 pt-2" : "mt-3 pt-2.5",
            )}>
              <span className="text-[10px] uppercase tracking-[0.18em] text-slate-400">
                metric
              </span>
              <span className="text-xs font-medium text-slate-700">{nodeData.metric}</span>
            </div>
          </>
        )}
      </div>
    </div>
  );
});
