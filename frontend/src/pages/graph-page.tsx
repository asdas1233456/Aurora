import { startTransition, useEffect, useMemo, useState } from "react";

import { useQuery } from "@tanstack/react-query";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { Background, Controls, MiniMap, ReactFlow, type Edge, type Node } from "@xyflow/react";
import { ChartNetwork, ChevronRight, Filter, Layers3, Orbit, RefreshCw, Sparkles } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { getGraph } from "@/api/client";
import { EmptyState } from "@/components/feedback/empty-state";
import { AuroraGraphNode, type AuroraGraphNodeData } from "@/components/graph/aurora-graph-node";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { TitleInfoIcon } from "@/components/ui/title-info-icon";
import { formatNumber } from "@/lib/format";
import { clamp, cn } from "@/lib/utils";
import { useAppStore } from "@/store/app-store";
import type { GraphEdgePayload, GraphNodePayload } from "@/types/api";

const GRAPH_PALETTES = [
  {
    accent: "#0f766e",
    surface: "linear-gradient(160deg, rgba(255,255,255,0.96), rgba(223,246,243,0.92) 56%, rgba(208,236,236,0.94) 100%)",
    glow: "rgba(15,118,110,0.14)",
  },
  {
    accent: "#0f8b8d",
    surface: "linear-gradient(160deg, rgba(255,255,255,0.96), rgba(221,246,246,0.92) 56%, rgba(201,236,236,0.94) 100%)",
    glow: "rgba(15,139,141,0.14)",
  },
  {
    accent: "#0284c7",
    surface: "linear-gradient(160deg, rgba(255,255,255,0.96), rgba(228,244,253,0.92) 56%, rgba(208,234,250,0.94) 100%)",
    glow: "rgba(2,132,199,0.14)",
  },
  {
    accent: "#14b8a6",
    surface: "linear-gradient(160deg, rgba(255,255,255,0.96), rgba(227,249,246,0.92) 56%, rgba(205,239,235,0.94) 100%)",
    glow: "rgba(20,184,166,0.14)",
  },
];

const NODE_TYPE_LABELS: Record<string, string> = {
  root: "Root",
  category: "Theme",
  file_type: "Type",
  document: "Doc",
};

const NODE_TYPE_ORDER: Record<string, number> = {
  root: 0,
  category: 1,
  file_type: 2,
  document: 3,
};

const DOCUMENT_COLLAPSE_THRESHOLD = 18;
const MAX_CONTEXT_DOCUMENTS = 14;
const ROOT_ANCHOR = { x: 220, y: 340 };

type GraphDensity = "overview" | "document";

type DocumentRelation = {
  categoryId: string | null;
  typeId: string | null;
};

type FlowEdgeInput = {
  source: string;
  target: string;
  label: string;
  weight: number;
  kind: "raw" | "aggregate";
};

type NodeLinkMap = {
  edgesByNode: Map<string, GraphEdgePayload[]>;
  docsByConnector: Map<string, string[]>;
  connectorsByDoc: Map<string, string[]>;
  relationByDocument: Map<string, DocumentRelation>;
  overviewEdges: FlowEdgeInput[];
};

export function GraphPage() {
  const navigate = useNavigate();
  const reducedMotion = useReducedMotion();
  const setSelectedDocumentId = useAppStore((state) => state.setSelectedDocumentId);
  const themeFilter = useAppStore((state) => state.graphThemeFilter);
  const typeFilter = useAppStore((state) => state.graphTypeFilter);
  const setThemeFilter = useAppStore((state) => state.setGraphThemeFilter);
  const setTypeFilter = useAppStore((state) => state.setGraphTypeFilter);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);
  const [isDraggingNode, setIsDraggingNode] = useState(false);
  const [density, setDensity] = useState<GraphDensity>("overview");

  const graphQuery = useQuery({
    queryKey: ["graph", themeFilter, typeFilter],
    queryFn: () => getGraph({ theme: themeFilter || undefined, type: typeFilter || undefined }),
    staleTime: 30_000,
    placeholderData: (previousData) => previousData,
  });

  const rawNodes = graphQuery.data?.nodes ?? [];
  const rawEdges = graphQuery.data?.edges ?? [];
  const nodeTypes = useMemo(() => ({ aurora: AuroraGraphNode }), []);
  const nodeById = useMemo(() => new Map(rawNodes.map((node) => [node.id, node])), [rawNodes]);
  const linkMaps = useMemo(() => buildNodeLinkMaps(rawNodes, rawEdges, nodeById), [nodeById, rawEdges, rawNodes]);
  const documentNodeCount = useMemo(
    () => rawNodes.filter((node) => node.node_type === "document").length,
    [rawNodes],
  );

  useEffect(() => {
    setDensity(Boolean(themeFilter || typeFilter) || documentNodeCount <= DOCUMENT_COLLAPSE_THRESHOLD ? "document" : "overview");
  }, [documentNodeCount, themeFilter, typeFilter]);

  const showDocuments = density === "document";
  const contextDocumentIds = useMemo(
    () => pickContextDocumentIds(showDocuments, selectedNodeId, rawNodes, nodeById, linkMaps),
    [linkMaps, nodeById, rawNodes, selectedNodeId, showDocuments],
  );

  const visibleNodes = useMemo(() => {
    if (!showDocuments) {
      return rawNodes.filter((node) => node.node_type !== "document");
    }
    return rawNodes.filter((node) => node.node_type !== "document" || contextDocumentIds.has(node.id));
  }, [contextDocumentIds, rawNodes, showDocuments]);

  const visibleNodeIds = useMemo(() => new Set(visibleNodes.map((node) => node.id)), [visibleNodes]);
  const visibleEdges = useMemo(() => {
    if (!showDocuments) {
      return linkMaps.overviewEdges.filter((edge) => visibleNodeIds.has(edge.source) && visibleNodeIds.has(edge.target));
    }
    return rawEdges
      .filter((edge) => visibleNodeIds.has(edge.source) && visibleNodeIds.has(edge.target))
      .map((edge) => ({ ...edge, kind: "raw" as const }));
  }, [linkMaps.overviewEdges, rawEdges, showDocuments, visibleNodeIds]);

  useEffect(() => {
    if (!visibleNodes.length) {
      setSelectedNodeId(null);
      return;
    }
    if (selectedNodeId && !visibleNodeIds.has(selectedNodeId)) {
      setSelectedNodeId(null);
    }
  }, [selectedNodeId, visibleNodeIds, visibleNodes]);

  const selectedNode = selectedNodeId ? nodeById.get(selectedNodeId) ?? null : null;
  const hoveredNode = hoveredNodeId ? nodeById.get(hoveredNodeId) ?? null : null;
  const highlightedNodeIds = useMemo(
    () => buildHighlightedNodeIds(selectedNodeId, visibleEdges),
    [selectedNodeId, visibleEdges],
  );
  const nodes = useMemo(
    () => buildFlowNodes(visibleNodes, visibleEdges, selectedNodeId, linkMaps.relationByDocument),
    [linkMaps.relationByDocument, selectedNodeId, visibleEdges, visibleNodes],
  );
  const edges = useMemo(() => buildFlowEdges(visibleEdges, highlightedNodeIds), [highlightedNodeIds, visibleEdges]);
  const documentHighlights = useMemo(
    () => rawNodes.filter((node) => node.node_type === "document").sort(sortDocuments).slice(0, 8),
    [rawNodes],
  );
  const availableThemes = useMemo(
    () => Array.from(new Set(rawNodes.filter((node) => node.node_type === "category").map((node) => node.label))),
    [rawNodes],
  );
  const availableTypes = useMemo(
    () => Array.from(new Set(rawNodes.filter((node) => node.node_type === "file_type").map((node) => node.label.toLowerCase()))),
    [rawNodes],
  );
  const hiddenDocumentCount = Math.max(0, documentNodeCount - contextDocumentIds.size);
  const graphModeLabel = showDocuments ? "上下文图" : "关系总览";
  const graphModeHint = showDocuments
    ? `当前仅展开与焦点相关的 ${formatNumber(contextDocumentIds.size)} 个文档节点。`
    : `已折叠 ${formatNumber(hiddenDocumentCount)} 个文档节点，先查看主题与类型之间的关系骨架。`;

  return (
    <section className="surface-grid surface-grid-two">
      <div className="space-y-4">
        <Card className="glass-panel">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Filter className="h-4 w-4 text-teal-700" />
              图谱过滤器
              <TitleInfoIcon label="图谱过滤器说明">
                先看主题与类型的关系网，再按需要展开局部文档簇，避免图谱一打开就挤成一团。
              </TitleInfoIcon>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="rounded-[20px] border border-white/70 bg-white/72 p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-xs uppercase tracking-[0.2em] text-slate-400">视图密度</p>
                  <p className="mt-2 text-sm font-medium text-slate-800">{graphModeLabel}</p>
                  <p className="mt-1 text-xs leading-6 text-slate-500">{graphModeHint}</p>
                </div>
                <Button
                  type="button"
                  size="sm"
                  variant={showDocuments ? "secondary" : "outline"}
                  onClick={() => setDensity((current) => current === "document" ? "overview" : "document")}
                >
                  <Layers3 className="h-4 w-4" />
                  {showDocuments ? "收起文档" : "展开文档"}
                </Button>
              </div>
            </div>

            <div className="space-y-2">
              <p className="text-xs uppercase tracking-[0.2em] text-slate-400">主题</p>
              <Select value={themeFilter || "all"} onValueChange={(value) => setThemeFilter(value === "all" ? "" : value)}>
                <SelectTrigger>
                  <SelectValue placeholder="全部主题" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">全部主题</SelectItem>
                  {availableThemes.map((theme) => (
                    <SelectItem key={theme} value={theme}>
                      {theme}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <p className="text-xs uppercase tracking-[0.2em] text-slate-400">类型</p>
              <Select value={typeFilter || "all"} onValueChange={(value) => setTypeFilter(value === "all" ? "" : value)}>
                <SelectTrigger>
                  <SelectValue placeholder="全部类型" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">全部类型</SelectItem>
                  {availableTypes.map((type) => (
                    <SelectItem key={type} value={type}>
                      {type.toUpperCase()}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="grid gap-2 rounded-[20px] border border-white/70 bg-white/72 p-4">
              <div className="flex items-center justify-between">
                <span className="text-sm text-slate-600">当前节点</span>
                <span className="font-mono text-sm text-slate-800">{formatNumber(nodes.length)}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-slate-600">当前连接</span>
                <span className="font-mono text-sm text-slate-800">{formatNumber(edges.length)}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-slate-600">文档总数</span>
                <span className="font-mono text-sm text-slate-800">{formatNumber(documentNodeCount)}</span>
              </div>
            </div>

            <Button variant="secondary" onClick={() => graphQuery.refetch()} data-testid="refresh-graph-button">
              <RefreshCw className="h-4 w-4" />
              重新拉取图谱
            </Button>
          </CardContent>
        </Card>

        <Card className="glass-panel" data-testid="graph-highlight-list">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              高频文档
              <TitleInfoIcon label="高频文档说明">点击任一文档，会切换到上下文图，仅展开它附近的一小簇关系。</TitleInfoIcon>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {documentHighlights.length === 0 ? (
              <EmptyState
                icon={Sparkles}
                title="当前筛选下没有高频文档"
                description="可以放宽筛选条件，或者重新扫描知识库，让图谱长出新的连接。"
                className="px-4 py-6"
                actions={[{ label: "清空筛选", variant: "secondary", onClick: () => { setThemeFilter(""); setTypeFilter(""); } }]}
              />
            ) : documentHighlights.map((node) => {
              const documentId = String(readString(node.meta, "document_id") ?? node.id);
              return (
                <button
                  key={documentId}
                  type="button"
                  data-testid={`graph-highlight-button-${documentId}`}
                  onClick={() => { setDensity("document"); setSelectedNodeId(node.id); }}
                  className={cn(
                    "flex w-full items-center justify-between rounded-[20px] border px-4 py-3 text-left transition",
                    selectedNodeId === node.id
                      ? "border-teal-300 bg-teal-50/92 shadow-[0_14px_30px_rgba(15,118,110,0.08)]"
                      : "border-white/70 bg-white/72 hover:border-cyan-200 hover:bg-white",
                  )}
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-slate-800">{node.label}</p>
                    <p className="truncate text-xs text-slate-500">{readString(node.meta, "relative_path") ?? "暂无路径信息"}</p>
                  </div>
                  <Badge variant="outline">{formatNumber(readNumber(node.meta, "citation_count"))}</Badge>
                </button>
              );
            })}
          </CardContent>
        </Card>
      </div>

      <div className="relative overflow-hidden rounded-[30px] border border-white/70 bg-white/72 shadow-[0_18px_50px_rgba(15,118,110,0.12)]">
        <div className="pointer-events-none absolute inset-0">
          <div className="absolute inset-0 bg-[radial-gradient(circle_at_16%_50%,rgba(15,118,110,0.12),transparent_28%),radial-gradient(circle_at_68%_50%,rgba(2,132,199,0.08),transparent_24%),linear-gradient(180deg,rgba(255,255,255,0.1),rgba(255,255,255,0))]" />
          <div className="absolute left-[4.5rem] top-1/2 h-[26rem] w-[26rem] -translate-y-1/2 rounded-full border border-dashed border-teal-200/55" />
          <div className="absolute left-[18rem] top-1/2 h-[38rem] w-[38rem] -translate-y-1/2 rounded-full border border-dashed border-teal-100/55" />
          <div className="absolute right-[8rem] top-1/2 h-[19rem] w-[19rem] -translate-y-1/2 rounded-full border border-dashed border-cyan-100/65" />
        </div>

        <div className="absolute left-5 top-5 z-10 flex flex-wrap items-center gap-2 rounded-full bg-white/88 px-3 py-2 shadow-[0_10px_26px_rgba(15,118,110,0.08)]">
          <ChartNetwork className="h-4 w-4 text-teal-700" />
          <span className="text-sm font-medium text-slate-800">Knowledge Graph Canvas</span>
          <Badge variant={showDocuments ? "soft" : "outline"}>{graphModeLabel}</Badge>
          {graphQuery.isFetching ? <Badge variant="outline">刷新中</Badge> : null}
        </div>

        {!showDocuments && hiddenDocumentCount > 0 ? (
          <div className="absolute left-5 top-20 z-10 max-w-sm rounded-[20px] border border-white/80 bg-white/84 px-4 py-3 text-sm text-slate-600 shadow-[0_12px_28px_rgba(15,118,110,0.08)]">
            总览模式会把文档叶子折叠成主题与类型之间的汇总连线，所以现在更像一张关系图，而不是一排排文件卡片。
          </div>
        ) : null}

        <AnimatePresence>
          {hoveredNode && !isDraggingNode ? (
            <motion.div
              initial={reducedMotion ? undefined : { opacity: 0, y: 12 }}
              animate={reducedMotion ? undefined : { opacity: 1, y: 0 }}
              exit={reducedMotion ? undefined : { opacity: 0, y: 8 }}
              className="absolute bottom-5 left-5 z-10 w-[280px] rounded-[20px] border border-white/80 bg-white/86 p-4 shadow-[0_16px_35px_rgba(15,118,110,0.1)]"
            >
              <div className="flex items-center gap-2">
                <div className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: getNodePalette(hoveredNode).accent }} />
                <p className="text-xs uppercase tracking-[0.24em] text-slate-400">悬停预览</p>
              </div>
              <p className="mt-3 text-sm font-semibold text-slate-900">{hoveredNode.label}</p>
              <p className="mt-2 text-xs leading-6 text-slate-500">{describeNode(hoveredNode)}</p>
            </motion.div>
          ) : null}
        </AnimatePresence>

        <div className="h-[680px] w-full xl:h-[calc(100dvh-12rem)]">
          {nodes.length === 0 ? (
            <div className="flex h-full items-center justify-center p-6">
              <EmptyState
                icon={Orbit}
                title="没有可渲染的知识节点"
                description="当前筛选下还没有形成关系网。可以先放宽筛选，或者回到知识库同步文档。"
                actions={[{ label: "清空筛选", variant: "secondary", onClick: () => { setThemeFilter(""); setTypeFilter(""); } }]}
              />
            </div>
          ) : (
            <ReactFlow<Node<AuroraGraphNodeData, "aurora">, Edge>
              nodes={nodes}
              edges={edges}
              nodeTypes={nodeTypes}
              fitView
              fitViewOptions={{ padding: showDocuments ? 0.035 : 0.025, duration: reducedMotion ? 0 : 180 }}
              minZoom={0.48}
              maxZoom={1.7}
              nodesDraggable
              nodesConnectable={false}
              nodesFocusable={false}
              edgesFocusable={false}
              elementsSelectable={false}
              elevateNodesOnSelect={false}
              onlyRenderVisibleElements
              panOnScroll
              selectionOnDrag={false}
              proOptions={{ hideAttribution: true }}
              onPaneClick={() => {
                setHoveredNodeId(null);
                setIsDraggingNode(false);
              }}
              onNodeClick={(_, node) => setSelectedNodeId(node.id)}
              onNodeMouseEnter={(_, node) => {
                if (!isDraggingNode) {
                  setHoveredNodeId(node.id);
                }
              }}
              onNodeMouseLeave={() => {
                if (!isDraggingNode) {
                  setHoveredNodeId(null);
                }
              }}
              onNodeDragStart={() => {
                setIsDraggingNode(true);
                setHoveredNodeId(null);
              }}
              onNodeDragStop={(_, node) => {
                setIsDraggingNode(false);
                setSelectedNodeId(node.id);
              }}
            >
              <Background color="rgba(15,118,110,0.08)" gap={28} size={1.1} />
              <MiniMap pannable zoomable nodeColor={(node) => (node.data as AuroraGraphNodeData).accent} maskColor="rgba(241,249,249,0.72)" />
              <Controls fitViewOptions={{ padding: showDocuments ? 0.035 : 0.025 }} />
            </ReactFlow>
          )}
        </div>

        <AnimatePresence>
          {selectedNode ? (
            <motion.aside
              key={selectedNode.id}
              initial={reducedMotion ? undefined : { x: 18, opacity: 0 }}
              animate={reducedMotion ? undefined : { x: 0, opacity: 1 }}
              exit={reducedMotion ? undefined : { x: 18, opacity: 0 }}
              className="absolute right-5 top-5 z-10 w-[320px]"
              data-testid="graph-node-detail-panel"
            >
              <Card className="glass-panel">
                <CardHeader>
                  <Badge variant="outline">{NODE_TYPE_LABELS[selectedNode.node_type] ?? selectedNode.node_type}</Badge>
                  <CardTitle className="flex items-center gap-2">
                    {selectedNode.label}
                    <TitleInfoIcon label="节点说明">
                      {readString(selectedNode.meta, "relative_path") ?? describeNode(selectedNode)}
                    </TitleInfoIcon>
                  </CardTitle>
                  <span className="sr-only">{readString(selectedNode.meta, "relative_path") ?? describeNode(selectedNode)}</span>
                </CardHeader>
                <CardContent className="space-y-3">
                  <MetaTile label="主题" value={readString(selectedNode.meta, "category") ?? selectedNode.label} />
                  <MetaTile label="状态" value={readString(selectedNode.meta, "status") ?? "--"} />
                  <MetaTile label="引用频次" value={formatNumber(readNumber(selectedNode.meta, "citation_count"))} />
                  <MetaTile label="切片数" value={formatNumber(readNumber(selectedNode.meta, "chunk_count"))} />
                  {readString(selectedNode.meta, "document_id") ? (
                    <Button
                      className="w-full"
                      data-testid="graph-primary-action-button"
                      onClick={() => {
                        const documentId = readString(selectedNode.meta, "document_id");
                        if (!documentId) {
                          return;
                        }
                        setSelectedDocumentId(documentId);
                        startTransition(() => navigate("/knowledge"));
                      }}
                    >
                      在知识库打开
                      <ChevronRight className="h-4 w-4" />
                    </Button>
                  ) : null}
                </CardContent>
              </Card>
            </motion.aside>
          ) : null}
        </AnimatePresence>
      </div>
    </section>
  );
}

function MetaTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[18px] border border-white/70 bg-white/72 p-3">
      <p className="text-xs uppercase tracking-[0.16em] text-slate-400">{label}</p>
      <p className="mt-1 text-sm text-slate-700">{value}</p>
    </div>
  );
}

function buildNodeLinkMaps(
  rawNodes: GraphNodePayload[],
  rawEdges: GraphEdgePayload[],
  nodeById: Map<string, GraphNodePayload>,
): NodeLinkMap {
  const edgesByNode = new Map<string, GraphEdgePayload[]>();
  const docsByConnector = new Map<string, string[]>();
  const connectorsByDoc = new Map<string, string[]>();
  const relationByDocument = new Map<string, DocumentRelation>();

  rawNodes
    .filter((node) => node.node_type === "document")
    .forEach((node) => relationByDocument.set(node.id, { categoryId: null, typeId: null }));

  const pushEdge = (nodeId: string, edge: GraphEdgePayload) => {
    const existing = edgesByNode.get(nodeId) ?? [];
    existing.push(edge);
    edgesByNode.set(nodeId, existing);
  };

  rawEdges.forEach((edge) => {
    pushEdge(edge.source, edge);
    pushEdge(edge.target, edge);

    const sourceNode = nodeById.get(edge.source);
    const targetNode = nodeById.get(edge.target);
    if (!sourceNode || !targetNode) {
      return;
    }

    const sourceIsDoc = sourceNode.node_type === "document";
    const targetIsDoc = targetNode.node_type === "document";
    if (sourceIsDoc === targetIsDoc) {
      return;
    }

    const documentId = sourceIsDoc ? edge.source : edge.target;
    const connectorId = sourceIsDoc ? edge.target : edge.source;
    const connectorNode = sourceIsDoc ? targetNode : sourceNode;

    pushUniqueValue(docsByConnector, connectorId, documentId);
    pushUniqueValue(connectorsByDoc, documentId, connectorId);

    const relation = relationByDocument.get(documentId) ?? { categoryId: null, typeId: null };
    if (connectorNode.node_type === "category") {
      relation.categoryId = connectorId;
    }
    if (connectorNode.node_type === "file_type") {
      relation.typeId = connectorId;
    }
    relationByDocument.set(documentId, relation);
  });

  const aggregateCounts = new Map<string, number>();
  relationByDocument.forEach(({ categoryId, typeId }) => {
    if (!categoryId || !typeId) {
      return;
    }
    const aggregateKey = `${categoryId}__${typeId}`;
    aggregateCounts.set(aggregateKey, (aggregateCounts.get(aggregateKey) ?? 0) + 1);
  });

  const overviewEdges: FlowEdgeInput[] = rawEdges
    .filter((edge) => {
      const sourceType = nodeById.get(edge.source)?.node_type;
      const targetType = nodeById.get(edge.target)?.node_type;
      return sourceType !== "document" && targetType !== "document";
    })
    .map((edge) => ({ ...edge, kind: "raw" as const }));

  aggregateCounts.forEach((count, aggregateKey) => {
    const [categoryId, typeId] = aggregateKey.split("__");
    overviewEdges.push({
      source: categoryId,
      target: typeId,
      label: `${count} docs`,
      weight: count,
      kind: "aggregate",
    });
  });

  return { edgesByNode, docsByConnector, connectorsByDoc, relationByDocument, overviewEdges };
}

function pickContextDocumentIds(
  showDocuments: boolean,
  selectedNodeId: string | null,
  rawNodes: GraphNodePayload[],
  nodeById: Map<string, GraphNodePayload>,
  linkMaps: NodeLinkMap,
) {
  const documentNodes = rawNodes.filter((node) => node.node_type === "document");
  if (!showDocuments) {
    return new Set<string>();
  }
  if (documentNodes.length <= DOCUMENT_COLLAPSE_THRESHOLD) {
    return new Set(documentNodes.map((node) => node.id));
  }

  const selectedNode = selectedNodeId ? nodeById.get(selectedNodeId) ?? null : null;
  const connectorIds = new Set<string>();
  const seedDocumentIds = new Set<string>();

  if (selectedNode?.node_type === "document") {
    seedDocumentIds.add(selectedNode.id);
    (linkMaps.connectorsByDoc.get(selectedNode.id) ?? []).forEach((connectorId) => connectorIds.add(connectorId));
  } else if (selectedNode?.node_type === "category" || selectedNode?.node_type === "file_type") {
    connectorIds.add(selectedNode.id);
  }

  if (seedDocumentIds.size === 0 && connectorIds.size === 0) {
    documentNodes.slice().sort(sortDocuments).slice(0, 6).forEach((node) => {
      seedDocumentIds.add(node.id);
      (linkMaps.connectorsByDoc.get(node.id) ?? []).forEach((connectorId) => connectorIds.add(connectorId));
    });
  }

  const candidateIds = new Set<string>(seedDocumentIds);
  connectorIds.forEach((connectorId) => {
    (linkMaps.docsByConnector.get(connectorId) ?? []).forEach((documentId) => candidateIds.add(documentId));
  });

  return new Set(
    Array.from(candidateIds)
      .map((id) => nodeById.get(id))
      .filter((node): node is GraphNodePayload => Boolean(node))
      .sort((left, right) => {
        if (left.id === selectedNodeId) {
          return -1;
        }
        if (right.id === selectedNodeId) {
          return 1;
        }
        return sortDocuments(left, right);
      })
      .slice(0, MAX_CONTEXT_DOCUMENTS)
      .map((node) => node.id),
  );
}

function buildHighlightedNodeIds(selectedNodeId: string | null, visibleEdges: FlowEdgeInput[]) {
  const highlighted = new Set<string>();
  if (!selectedNodeId) {
    return highlighted;
  }

  highlighted.add(selectedNodeId);
  visibleEdges.forEach((edge) => {
    if (edge.source === selectedNodeId || edge.target === selectedNodeId) {
      highlighted.add(edge.source);
      highlighted.add(edge.target);
    }
  });
  return highlighted;
}

function buildFlowNodes(
  sourceNodes: GraphNodePayload[],
  sourceEdges: FlowEdgeInput[],
  selectedNodeId: string | null,
  relationByDocument: Map<string, DocumentRelation>,
) {
  const positions = buildLayoutPositions(sourceNodes, sourceEdges, relationByDocument);
  return sourceNodes.map((node) => {
    const palette = getNodePalette(node);
    return {
      id: node.id,
      type: "aurora",
      position: positions.get(node.id) ?? { x: 0, y: 0 },
      draggable: true,
      selected: selectedNodeId === node.id,
      data: {
        label: node.label,
        kind: node.node_type,
        nodeType: NODE_TYPE_LABELS[node.node_type] ?? node.node_type,
        accent: palette.accent,
        surface: palette.surface,
        glow: palette.glow,
        description: describeNode(node),
        secondaryText: describeSecondary(node),
        metric: describeMetric(node),
        badge: describeBadge(node),
      },
      style: { width: getNodeWidth(node) },
    } satisfies Node<AuroraGraphNodeData, "aurora">;
  });
}

function buildFlowEdges(sourceEdges: FlowEdgeInput[], highlightedNodeIds: Set<string>) {
  return sourceEdges.map((edge) => {
    const highlighted = highlightedNodeIds.size === 0
      || highlightedNodeIds.has(edge.source)
      || highlightedNodeIds.has(edge.target);
    const isAggregate = edge.kind === "aggregate";

    return {
      id: `${edge.kind}:${edge.source}-${edge.target}-${edge.label}`,
      source: edge.source,
      target: edge.target,
      type: isAggregate ? "smoothstep" : "simplebezier",
      label: highlighted && edge.weight > 1 ? edge.label : undefined,
      animated: false,
      style: {
        stroke: highlighted
          ? (isAggregate ? "rgba(15,118,110,0.42)" : "rgba(15,118,110,0.3)")
          : (isAggregate ? "rgba(15,118,110,0.18)" : "rgba(15,118,110,0.14)"),
        strokeWidth: clamp(isAggregate ? 1.4 + edge.weight * 0.28 : 1.05 + edge.weight * 0.12, 1.2, 3.2),
        strokeDasharray: isAggregate ? "6 7" : undefined,
      },
      labelStyle: { fill: "#5f7285", fontSize: 11, fontWeight: 500 },
    } satisfies Edge;
  });
}

function buildLayoutPositions(
  sourceNodes: GraphNodePayload[],
  sourceEdges: FlowEdgeInput[],
  relationByDocument: Map<string, DocumentRelation>,
) {
  const positions = new Map<string, { x: number; y: number }>();
  const rootNodes = sortNodes(sourceNodes.filter((node) => node.node_type === "root"));
  const categoryNodes = sortNodes(sourceNodes.filter((node) => node.node_type === "category"));
  const fileTypeNodes = sortNodes(sourceNodes.filter((node) => node.node_type === "file_type"));
  const documentNodes = sortNodes(sourceNodes.filter((node) => node.node_type === "document"));

  rootNodes.forEach((node, index) => {
    positions.set(node.id, { x: ROOT_ANCHOR.x, y: ROOT_ANCHOR.y + index * 90 });
  });

  buildOrbitPositions(categoryNodes, {
    centerX: 470,
    centerY: ROOT_ANCHOR.y,
    radiusX: 205,
    radiusY: 240,
    ringSize: 18,
    ringGapX: 74,
    ringGapY: 56,
    startAngle: -2.15,
    endAngle: 2.15,
  }).forEach((value, key) => positions.set(key, value));

  buildOrbitPositions(fileTypeNodes, {
    centerX: 950,
    centerY: ROOT_ANCHOR.y,
    radiusX: 110,
    radiusY: 200,
    ringSize: 7,
    ringGapX: 54,
    ringGapY: 38,
    startAngle: -1.35,
    endAngle: 1.35,
  }).forEach((value, key) => positions.set(key, value));

  buildDocumentPositions(documentNodes, sourceEdges, positions, relationByDocument).forEach((value, key) => positions.set(key, value));

  return positions;
}

function buildOrbitPositions(
  nodes: GraphNodePayload[],
  options: {
    centerX: number;
    centerY: number;
    radiusX: number;
    radiusY: number;
    ringSize: number;
    ringGapX: number;
    ringGapY: number;
    startAngle: number;
    endAngle: number;
  },
) {
  const positions = new Map<string, { x: number; y: number }>();
  nodes.forEach((node, index) => {
    const ring = Math.floor(index / options.ringSize);
    const slot = index % options.ringSize;
    const itemsInRing = Math.min(options.ringSize, nodes.length - ring * options.ringSize);
    const progress = itemsInRing <= 1 ? 0.5 : slot / (itemsInRing - 1);
    const angle = options.startAngle + progress * (options.endAngle - options.startAngle) + hashJitter(node.id, 0.08);
    const radiusX = options.radiusX + ring * options.ringGapX;
    const radiusY = options.radiusY + ring * options.ringGapY;
    positions.set(node.id, {
      x: options.centerX + Math.cos(angle) * radiusX,
      y: options.centerY + Math.sin(angle) * radiusY,
    });
  });
  return positions;
}

function buildDocumentPositions(
  documentNodes: GraphNodePayload[],
  edges: FlowEdgeInput[],
  anchorPositions: Map<string, { x: number; y: number }>,
  relationByDocument: Map<string, DocumentRelation>,
) {
  const positions = new Map<string, { x: number; y: number }>();
  const grouped = new Map<string, GraphNodePayload[]>();

  documentNodes.forEach((node) => {
    const relation = relationByDocument.get(node.id) ?? { categoryId: null, typeId: null };
    const groupKey = relation.categoryId ?? relation.typeId ?? "ungrouped";
    const existing = grouped.get(groupKey) ?? [];
    existing.push(node);
    grouped.set(groupKey, existing);
  });

  Array.from(grouped.entries()).forEach(([groupKey, nodesInGroup], groupIndex) => {
    const sampleRelation = relationByDocument.get(nodesInGroup[0].id) ?? { categoryId: null, typeId: null };
    const categoryPosition = sampleRelation.categoryId ? anchorPositions.get(sampleRelation.categoryId) : undefined;
    const typePosition = sampleRelation.typeId ? anchorPositions.get(sampleRelation.typeId) : undefined;
    const anchor = {
      x: categoryPosition && typePosition
        ? categoryPosition.x * 0.58 + typePosition.x * 0.42 + 40
        : categoryPosition
          ? categoryPosition.x + 140
          : typePosition
            ? typePosition.x - 120
            : 760,
      y: categoryPosition && typePosition
        ? categoryPosition.y * 0.56 + typePosition.y * 0.44
        : categoryPosition?.y ?? typePosition?.y ?? (ROOT_ANCHOR.y + groupIndex * 36),
    };

    const outwardAngle = Math.atan2(anchor.y - ROOT_ANCHOR.y, anchor.x - ROOT_ANCHOR.x);
    nodesInGroup.slice().sort(sortDocuments).forEach((node, index) => {
      const ring = Math.floor(index / 4);
      const slot = index % 4;
      const itemsInRing = Math.min(4, nodesInGroup.length - ring * 4);
      const progress = itemsInRing <= 1 ? 0.5 : slot / (itemsInRing - 1);
      const angle = outwardAngle - 0.86 + progress * 1.72 + hashJitter(node.id, 0.14);
      const radiusX = 58 + ring * 36;
      const radiusY = 34 + ring * 24;
      positions.set(node.id, {
        x: anchor.x + Math.cos(angle) * radiusX,
        y: anchor.y + Math.sin(angle) * radiusY,
      });
    });

    if (groupKey === "ungrouped" && nodesInGroup.length === 1) {
      positions.set(nodesInGroup[0].id, { x: 760, y: ROOT_ANCHOR.y + groupIndex * 36 });
    }
  });

  if (documentNodes.length > 0 && edges.length === 0) {
    documentNodes.slice(0, 6).forEach((node, index) => {
      positions.set(node.id, { x: 680 + index * 34, y: ROOT_ANCHOR.y + hashJitter(node.id, 18) });
    });
  }

  return positions;
}

function sortNodes(nodes: GraphNodePayload[]) {
  return [...nodes].sort((left, right) => {
    const leftWeight = readNumber(left.meta, "citation_count") || readNumber(left.meta, "document_count") || left.size;
    const rightWeight = readNumber(right.meta, "citation_count") || readNumber(right.meta, "document_count") || right.size;
    if (leftWeight !== rightWeight) {
      return rightWeight - leftWeight;
    }
    return left.label.localeCompare(right.label);
  });
}

function sortDocuments(left: GraphNodePayload, right: GraphNodePayload) {
  return readNumber(right.meta, "citation_count") - readNumber(left.meta, "citation_count") || left.label.localeCompare(right.label);
}

function getNodeWidth(node: GraphNodePayload) {
  if (node.node_type === "root") {
    return 190;
  }
  if (node.node_type === "document") {
    return clamp(138 + node.size * 0.55, 138, 164);
  }
  if (node.node_type === "file_type") {
    return clamp(128 + node.size * 0.4, 128, 148);
  }
  return clamp(156 + node.size * 0.45, 156, 186);
}

function describeSecondary(node: GraphNodePayload) {
  if (node.node_type === "document") {
    return readString(node.meta, "relative_path") ?? "未提供路径";
  }
  if (node.node_type === "file_type") {
    return `${String(node.label).toUpperCase()} format`;
  }
  if (node.node_type === "category") {
    return `${formatNumber(readNumber(node.meta, "document_count") || node.size)} 份文档`;
  }
  return "知识网络入口";
}

function describeMetric(node: GraphNodePayload) {
  if (node.node_type === "document") {
    return `${formatNumber(readNumber(node.meta, "citation_count"))} 引用`;
  }
  if (node.node_type === "file_type") {
    return `${formatNumber(readNumber(node.meta, "document_count") || node.size)} 文件`;
  }
  if (node.node_type === "category") {
    return `${formatNumber(readNumber(node.meta, "chunk_count") || node.size)} 切片`;
  }
  return `${formatNumber(node.size)} 连接`;
}

function describeBadge(node: GraphNodePayload) {
  if (node.node_type === "category") {
    return "主题";
  }
  if (node.node_type === "file_type") {
    return "类型";
  }
  if (node.node_type === "document") {
    return "文档";
  }
  return "根源";
}

function getNodePalette(node: GraphNodePayload) {
  const seed = readString(node.meta, "category") ?? node.label;
  return GRAPH_PALETTES[(hashValue(seed) + (NODE_TYPE_ORDER[node.node_type] ?? 0)) % GRAPH_PALETTES.length];
}

function describeNode(node: GraphNodePayload) {
  if (node.node_type === "document") {
    return readString(node.meta, "relative_path") ?? "文档节点，承载被引用的知识内容。";
  }
  if (node.node_type === "file_type") {
    return `文件类型节点，聚合同类型的 ${formatNumber(readNumber(node.meta, "document_count") || node.size)} 份文档。`;
  }
  if (node.node_type === "category") {
    return "主题节点，用于串联同一主题下的文档与文件类型。";
  }
  return "根节点，用来汇聚整张知识图谱的主干关系。";
}

function readString(meta: Record<string, unknown>, key: string) {
  const value = meta[key];
  return typeof value === "string" && value.trim() ? value : null;
}

function readNumber(meta: Record<string, unknown>, key: string) {
  const value = meta[key];
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : 0;
  }
  return 0;
}

function pushUniqueValue(map: Map<string, string[]>, key: string, value: string) {
  const existing = map.get(key) ?? [];
  if (!existing.includes(value)) {
    existing.push(value);
    map.set(key, existing);
  }
}

function hashValue(input: string) {
  return Array.from(input).reduce((total, char) => total + char.charCodeAt(0), 0);
}

function hashJitter(input: string, amplitude: number) {
  const seed = hashValue(input);
  const normalized = ((seed % 10_000) / 10_000) * 2 - 1;
  return normalized * amplitude;
}
