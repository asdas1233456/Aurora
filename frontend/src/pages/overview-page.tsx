import { useMemo } from "react";

import { useQuery } from "@tanstack/react-query";
import { motion, useReducedMotion } from "framer-motion";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Bot,
  CheckCircle2,
  Clock3,
  Database,
  FileClock,
  Files,
  Gauge,
  GitBranch,
  Layers3,
  LineChart,
  ListChecks,
  LoaderCircle,
  Network,
  ShieldCheck,
  TimerReset,
  UploadCloud,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { Link } from "react-router-dom";

import { getWorkspaceBootstrap, listChatSessions } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { TitleInfoIcon } from "@/components/ui/title-info-icon";
import { formatConfidence, formatDateTime, formatDuration, formatNumber } from "@/lib/format";
import { cn, shortText } from "@/lib/utils";
import type { ChatSessionListItem, DocumentSummary } from "@/types/api";


type Tone = "good" | "warn" | "danger" | "neutral";

interface TrendPoint {
  label: string;
  value: number;
  lowConfidence: number;
}

interface LatencySegment {
  label: string;
  value: number;
  tone: Tone;
}

const KPI_CARDS: Array<{
  key: "source_file_count" | "chunk_count" | "indexed_file_count" | "pending_file_count";
  label: string;
  detail: string;
  icon: LucideIcon;
}> = [
  { key: "source_file_count", label: "文档资产", detail: "纳入知识库的源文件", icon: Files },
  { key: "chunk_count", label: "索引切片", detail: "可被检索的知识片段", icon: Layers3 },
  { key: "indexed_file_count", label: "已索引", detail: "可参与问答的文档", icon: ShieldCheck },
  { key: "pending_file_count", label: "待处理", detail: "等待同步或重建索引", icon: FileClock },
];

const PIPELINE_STEPS = [
  { key: "upload", label: "上传", icon: UploadCloud },
  { key: "parse", label: "解析", icon: ListChecks },
  { key: "chunk", label: "切片", icon: Layers3 },
  { key: "embed", label: "向量化", icon: Network },
  { key: "index", label: "索引", icon: Database },
] as const;

export function OverviewPage() {
  const reducedMotion = useReducedMotion();
  const workspaceQuery = useQuery({
    queryKey: ["workspace-bootstrap"],
    queryFn: getWorkspaceBootstrap,
  });
  const sessionsQuery = useQuery({
    queryKey: ["chat-sessions", "overview-dashboard"],
    queryFn: () => listChatSessions({ limit: 50 }),
  });

  const payload = workspaceQuery.data;
  const sessions = sessionsQuery.data?.items ?? [];

  const dashboard = useMemo(() => {
    if (!payload) {
      return null;
    }
    const overview = payload.overview;
    const status = payload.knowledge_status;
    const totalDocuments = Math.max(overview.source_file_count, status.document_count, 0);
    const indexedDocuments = Math.max(overview.indexed_file_count, status.indexed_count, 0);
    const pendingDocuments = overview.pending_file_count + overview.changed_file_count;
    const failedDocuments = overview.failed_file_count + status.failed_count;
    const indexProgress = totalDocuments === 0 ? 0 : indexedDocuments / totalDocuments;
    const answerStats = createAnswerStats(sessions);

    return {
      overview,
      status,
      totalDocuments,
      indexedDocuments,
      pendingDocuments,
      failedDocuments,
      indexProgress,
      activeJobProgress: status.current_job?.progress ?? overview.active_job_progress ?? indexProgress,
      answerStats,
      pipeline: createPipelineState({
        totalDocuments,
        indexedDocuments,
        chunkCount: overview.chunk_count,
        pendingDocuments,
        failedDocuments,
        embeddingReady: overview.embedding_api_ready,
        knowledgeReady: overview.knowledge_base_ready,
        activeJobStatus: overview.active_job_status,
      }),
      actionItems: createActionItems({
        failedDocuments,
        pendingDocuments,
        llmReady: overview.llm_api_ready,
        embeddingReady: overview.embedding_api_ready,
        lowConfidenceCount: answerStats.lowConfidenceTotal,
      }),
      topCategories: readTopCategories(payload.graph.summary.top_categories),
      recentDocuments: [...payload.documents]
        .sort((left, right) => getTime(right.updated_at) - getTime(left.updated_at))
        .slice(0, 6),
    };
  }, [payload, sessions]);

  if (!payload || !dashboard) {
    return (
      <section className="glass-panel flex min-h-[56dvh] items-center justify-center rounded-[28px]">
        <LoaderCircle className="h-6 w-6 animate-spin text-teal-700" />
      </section>
    );
  }

  return (
    <section className="space-y-4" data-testid="overview-dashboard">
      <motion.div
        className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]"
        initial={reducedMotion ? undefined : { opacity: 0, y: 10 }}
        animate={reducedMotion ? undefined : { opacity: 1, y: 0 }}
        transition={reducedMotion ? undefined : { duration: 0.2, ease: "easeOut" }}
      >
        <Card className="glass-panel overflow-hidden">
          <CardHeader className="pb-3">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
              <div className="max-w-3xl">
                <CardTitle className="flex items-center gap-2 text-2xl text-slate-950">
                  Aurora 运行态势
                  <TitleInfoIcon label="Aurora 运行态势说明">
                    一屏查看系统健康、知识库索引、问答质量和上线前需要处理的事项。
                  </TitleInfoIcon>
                </CardTitle>
              </div>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:min-w-[500px]">
                <StatusPill label="知识库" value={dashboard.overview.knowledge_base_ready ? "可用" : "不可用"} tone={dashboard.overview.knowledge_base_ready ? "good" : "danger"} />
                <StatusPill label="LLM" value={dashboard.overview.llm_api_ready ? dashboard.overview.llm_provider : "未就绪"} tone={dashboard.overview.llm_api_ready ? "good" : "warn"} />
                <StatusPill label="Embedding" value={dashboard.overview.embedding_api_ready ? dashboard.overview.embedding_provider : "未就绪"} tone={dashboard.overview.embedding_api_ready ? "good" : "warn"} />
                <StatusPill label="部署" value={dashboard.overview.deployment_mode} tone="neutral" />
              </div>
            </div>
          </CardHeader>
          <CardContent>
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              {KPI_CARDS.map((item, index) => {
                const Icon = item.icon;
                const value = dashboard.overview[item.key];
                const isAttention = item.key === "pending_file_count" && Number(value) > 0;
                return (
                  <motion.div
                    key={item.key}
                    className={cn("surface-tile rounded-[20px] p-3", isAttention && "border-amber-200 bg-amber-50/70")}
                    initial={reducedMotion ? undefined : { opacity: 0, y: 8 }}
                    animate={reducedMotion ? undefined : { opacity: 1, y: 0 }}
                    transition={reducedMotion ? undefined : { delay: index * 0.035, duration: 0.18 }}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="rounded-2xl bg-teal-50 p-2.5 text-teal-700 ring-1 ring-teal-100">
                        <Icon className="h-4 w-4" />
                      </div>
                      <Badge variant={isAttention ? "status" : "outline"}>
                        {item.key === "indexed_file_count" ? `${Math.round(dashboard.indexProgress * 100)}%` : item.key === "pending_file_count" ? "队列" : "实时"}
                      </Badge>
                    </div>
                    <p className="mt-3 text-[1.65rem] font-semibold leading-none text-slate-950">{formatNumber(value)}</p>
                    <p className="mt-2 text-sm font-semibold text-slate-900">{item.label}</p>
                    <p className="mt-1 text-xs leading-5 text-slate-600">{item.detail}</p>
                  </motion.div>
                );
              })}
            </div>
          </CardContent>
        </Card>

        <Card className="glass-panel" data-testid="overview-action-items">
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between gap-3">
              <div>
                <CardTitle className="flex items-center gap-2 text-lg">
                  待处理事项
                  <TitleInfoIcon label="待处理事项说明">上线前优先清理这些阻塞点。</TitleInfoIcon>
                </CardTitle>
              </div>
              <Badge variant={dashboard.actionItems.length ? "status" : "soft"}>{dashboard.actionItems.length || "Clear"}</Badge>
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            {dashboard.actionItems.length === 0 ? (
              <div className="surface-tile rounded-[22px] p-4">
                <div className="flex items-center gap-3">
                  <CheckCircle2 className="h-5 w-5 text-teal-700" />
                  <div>
                    <p className="text-sm font-semibold text-slate-900">当前无阻塞事项</p>
                    <p className="mt-1 text-xs leading-5 text-slate-600">知识库和流程状态稳定，可以进入核心验收。</p>
                  </div>
                </div>
              </div>
            ) : (
              dashboard.actionItems.map((item) => <ActionItem key={item.label} {...item} />)
            )}
          </CardContent>
        </Card>
      </motion.div>

      <div className="grid auto-rows-fr items-stretch gap-4 xl:grid-cols-[minmax(0,1.18fr)_minmax(360px,0.75fr)_340px]">
        <Card className="glass-panel h-full" data-testid="overview-index-card">
          <CardHeader className="pb-2">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <CardTitle className="flex items-center gap-2 text-lg">
                  <Gauge className="h-4 w-4 text-teal-700" />
                  知识库索引健康
                  <TitleInfoIcon label="知识库索引健康说明">上传、解析、切片、向量化和索引的完整流水线状态。</TitleInfoIcon>
                </CardTitle>
              </div>
              <Badge variant="outline">{dashboard.status.current_job?.status || dashboard.overview.active_job_status || "idle"}</Badge>
            </div>
          </CardHeader>
          <CardContent className="grid gap-5 lg:grid-cols-[260px_minmax(0,1fr)]">
            <IndexProgressRing
              value={dashboard.indexProgress}
              jobProgress={dashboard.activeJobProgress}
              indexed={dashboard.indexedDocuments}
              total={dashboard.totalDocuments}
              pending={dashboard.pendingDocuments}
            />
            <div className="space-y-4">
              <div className="rounded-[24px] border border-teal-100 bg-white/86 p-4">
                <div className="mb-4 flex items-center justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-slate-900">索引流水线</p>
                    <p className="mt-1 text-xs text-slate-600">{dashboard.status.current_job?.message || "后台任务空闲，索引状态已稳定。"}</p>
                  </div>
                  <Badge variant="soft">{Math.round(dashboard.activeJobProgress * 100)}%</Badge>
                </div>
                <div className="grid gap-3 md:grid-cols-5">
                  {dashboard.pipeline.map(({ key, ...step }) => <PipelineStep key={key} {...step} />)}
                </div>
              </div>
              <div className="grid gap-3 md:grid-cols-3">
                <MetricTile icon={GitBranch} label="图谱节点" value={formatNumber(payload.graph.nodes.length)} helper={`${formatNumber(payload.graph.edges.length)} 条连接`} />
                <MetricTile icon={Database} label="主题覆盖" value={formatNumber(Number(payload.graph.summary.category_count ?? 0))} helper="按知识主题聚类" />
                <MetricTile icon={Zap} label="引用覆盖" value={formatNumber(Number(payload.graph.summary.citation_covered_document_count ?? 0))} helper="至少被引用过的文档" />
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="glass-panel h-full" data-testid="overview-quality-card">
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-lg">
              <Bot className="h-4 w-4 text-teal-700" />
              问答质量
              <TitleInfoIcon label="问答质量说明">基于最近 {formatNumber(dashboard.answerStats.sampleCount)} 条会话样本。</TitleInfoIcon>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-3 gap-3">
              <MetricTile icon={ShieldCheck} label="平均置信" value={formatConfidence(dashboard.answerStats.averageConfidence)} helper="最近回答" />
              <MetricTile icon={Activity} label="引用命中" value={`${dashboard.answerStats.citationCoverage}%`} helper="有引用回答" />
              <MetricTile icon={TimerReset} label="平均检索" value={formatDuration(dashboard.answerStats.averageRetrievalMs)} helper="SSE 元数据" />
            </div>
            <TrendLineChart points={dashboard.answerStats.trend} />
            <LatencyDistribution segments={dashboard.answerStats.latencySegments} />
          </CardContent>
        </Card>
        <AssetStreamCard documents={dashboard.recentDocuments} categories={dashboard.topCategories} />
      </div>
    </section>
  );
}

function createAnswerStats(sessions: ChatSessionListItem[]) {
  const assistantSamples = sessions
    .map((item) => item.last_message)
    .filter((message) => message?.role === "assistant");
  const confidenceValues = assistantSamples
    .map((message) => Number(message?.metadata.confidence ?? 0))
    .filter((value) => Number.isFinite(value));
  const retrievalValues = assistantSamples
    .map((message) => Number(message?.metadata.retrieval_ms ?? 0))
    .filter((value) => Number.isFinite(value) && value > 0);
  const citationCount = assistantSamples.filter((message) => (message?.citations.length ?? 0) > 0).length;
  const lowConfidenceTotal = confidenceValues.filter((value) => value > 0 && value < 0.45).length;

  return {
    sampleCount: assistantSamples.length,
    averageConfidence: average(confidenceValues),
    averageRetrievalMs: average(retrievalValues),
    citationCoverage: assistantSamples.length === 0 ? 0 : Math.round((citationCount / assistantSamples.length) * 100),
    lowConfidenceTotal,
    trend: createSevenDayTrend(sessions),
    latencySegments: createLatencySegments(retrievalValues),
  };
}

function createSevenDayTrend(sessions: ChatSessionListItem[]) {
  const today = new Date();
  const formatter = new Intl.DateTimeFormat("zh-CN", { weekday: "short" });
  const days = Array.from({ length: 7 }, (_, index) => {
    const date = new Date(today);
    date.setHours(0, 0, 0, 0);
    date.setDate(date.getDate() - (6 - index));
    return { date, label: formatter.format(date).replace("周", ""), value: 0, lowConfidence: 0 };
  });

  sessions.forEach((item) => {
    const timestamp = getTime(item.session.last_active_at || item.session.created_at);
    const target = days.find((day) => timestamp >= day.date.getTime() && timestamp < day.date.getTime() + 86_400_000);
    if (!target) {
      return;
    }
    target.value += Math.max(1, Math.ceil(item.message_count / 2));
    const confidence = Number(item.last_message?.metadata.confidence ?? 1);
    if (Number.isFinite(confidence) && confidence > 0 && confidence < 0.45) {
      target.lowConfidence += 1;
    }
  });

  return days.map(({ label, value, lowConfidence }) => ({ label, value, lowConfidence }));
}

function createLatencySegments(values: number[]): LatencySegment[] {
  return [
    { label: "<50ms", value: values.filter((value) => value <= 50).length, tone: "good" },
    { label: "50-200ms", value: values.filter((value) => value > 50 && value <= 200).length, tone: "neutral" },
    { label: ">200ms", value: values.filter((value) => value > 200).length, tone: "warn" },
  ];
}

function createPipelineState(input: {
  totalDocuments: number;
  indexedDocuments: number;
  chunkCount: number;
  pendingDocuments: number;
  failedDocuments: number;
  embeddingReady: boolean;
  knowledgeReady: boolean;
  activeJobStatus: string;
}) {
  const working = input.activeJobStatus === "running" || input.activeJobStatus === "pending";
  return PIPELINE_STEPS.map((step) => {
    let tone: Tone = "good";
    let value = "完成";

    if (step.key === "upload") {
      value = `${formatNumber(input.totalDocuments)} 文档`;
      tone = input.totalDocuments > 0 ? "good" : "neutral";
    }
    if (step.key === "parse") {
      value = input.failedDocuments > 0 ? `${formatNumber(input.failedDocuments)} 失败` : "通过";
      tone = input.failedDocuments > 0 ? "danger" : "good";
    }
    if (step.key === "chunk") {
      value = `${formatNumber(input.chunkCount)} 切片`;
      tone = input.chunkCount > 0 ? "good" : "neutral";
    }
    if (step.key === "embed") {
      value = input.embeddingReady ? "在线" : "未配置";
      tone = input.embeddingReady ? "good" : "warn";
    }
    if (step.key === "index") {
      value = working ? "运行中" : `${formatNumber(input.indexedDocuments)} 已索引`;
      tone = input.pendingDocuments > 0 ? "warn" : input.knowledgeReady ? "good" : "danger";
    }

    return { ...step, tone, value };
  });
}

function createActionItems(input: {
  failedDocuments: number;
  pendingDocuments: number;
  llmReady: boolean;
  embeddingReady: boolean;
  lowConfidenceCount: number;
}) {
  const items: Array<{ label: string; detail: string; to: string; tone: Tone; icon: LucideIcon }> = [];
  if (input.failedDocuments > 0) {
    items.push({ label: "处理失败文档", detail: `${formatNumber(input.failedDocuments)} 个文档解析或索引失败`, to: "/knowledge", tone: "danger", icon: AlertTriangle });
  }
  if (input.pendingDocuments > 0) {
    items.push({ label: "同步知识库", detail: `${formatNumber(input.pendingDocuments)} 个文档等待重新索引`, to: "/knowledge", tone: "warn", icon: FileClock });
  }
  if (!input.llmReady) {
    items.push({ label: "配置 LLM", detail: "当前会回退到本地模拟模型", to: "/settings", tone: "warn", icon: Bot });
  }
  if (!input.embeddingReady) {
    items.push({ label: "配置 Embedding", detail: "向量模型未就绪会影响真实检索质量", to: "/settings", tone: "warn", icon: Network });
  }
  if (input.lowConfidenceCount > 0) {
    items.push({ label: "复盘低置信回答", detail: `最近有 ${formatNumber(input.lowConfidenceCount)} 条回答置信度偏低`, to: "/chat", tone: "neutral", icon: Activity });
  }
  return items.slice(0, 5);
}

function readTopCategories(value: unknown) {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.map((item) => {
    const record = item as Record<string, unknown>;
    return {
      label: String(record.label ?? "未分类"),
      document_count: Number(record.document_count ?? 0),
    };
  });
}

function average(values: number[]) {
  if (values.length === 0) {
    return 0;
  }
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function getTime(value: string | null | undefined) {
  if (!value) {
    return 0;
  }
  const time = new Date(value).getTime();
  return Number.isNaN(time) ? 0 : time;
}

function StatusPill({ label, value, tone }: { label: string; value: string; tone: Tone }) {
  return (
    <div className="rounded-[18px] border border-teal-100 bg-white/88 px-3 py-2">
      <div className="flex items-center gap-2">
        <span className={cn("h-2 w-2 rounded-full", toneClasses[tone].dot)} />
        <span className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-600">{label}</span>
      </div>
      <p className="mt-1 truncate text-sm font-semibold text-slate-950">{value || "--"}</p>
    </div>
  );
}

function IndexProgressRing({ value, jobProgress, indexed, total, pending }: {
  value: number;
  jobProgress: number;
  indexed: number;
  total: number;
  pending: number;
}) {
  const radius = 58;
  const circumference = 2 * Math.PI * radius;
  const progress = Math.max(0, Math.min(1, value));
  const job = Math.max(0, Math.min(1, jobProgress));

  return (
    <div className="surface-tile flex flex-col items-center justify-center rounded-[28px] p-5 text-center">
      <div className="relative">
        <svg viewBox="0 0 150 150" className="h-40 w-40" aria-label="知识库索引进度">
          <circle cx="75" cy="75" r={radius} fill="none" stroke="rgba(15,118,110,0.1)" strokeWidth="12" />
          <circle cx="75" cy="75" r={radius} fill="none" stroke="rgba(15,118,110,0.24)" strokeWidth="12" strokeDasharray={circumference} strokeDashoffset={circumference * (1 - job)} strokeLinecap="round" transform="rotate(-90 75 75)" />
          <circle cx="75" cy="75" r={radius} fill="none" stroke="url(#overview-progress-gradient)" strokeWidth="12" strokeDasharray={circumference} strokeDashoffset={circumference * (1 - progress)} strokeLinecap="round" transform="rotate(-90 75 75)" />
          <defs>
            <linearGradient id="overview-progress-gradient" x1="20" x2="130" y1="20" y2="130">
              <stop offset="0%" stopColor="#0f766e" />
              <stop offset="100%" stopColor="#22d3ee" />
            </linearGradient>
          </defs>
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <p className="text-[2rem] font-semibold leading-none text-slate-950">{Math.round(progress * 100)}%</p>
          <p className="mt-1 text-xs font-semibold text-slate-600">索引完成</p>
        </div>
      </div>
      <div className="mt-3 grid w-full grid-cols-3 gap-2 text-xs">
        <RingStat label="已索引" value={formatNumber(indexed)} />
        <RingStat label="总文档" value={formatNumber(total)} />
        <RingStat label="待处理" value={formatNumber(pending)} />
      </div>
    </div>
  );
}

function RingStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl bg-white/80 px-2 py-2">
      <p className="font-semibold text-slate-950">{value}</p>
      <p className="mt-0.5 text-[11px] text-slate-600">{label}</p>
    </div>
  );
}

function PipelineStep({ label, value, icon: Icon, tone }: {
  label: string;
  value: string;
  icon: LucideIcon;
  tone: Tone;
}) {
  return (
    <div className="rounded-[20px] border border-teal-100 bg-white/82 p-3">
      <div className={cn("mb-3 inline-flex rounded-2xl p-2", toneClasses[tone].soft)}>
        <Icon className="h-4 w-4" />
      </div>
      <p className="text-sm font-semibold text-slate-950">{label}</p>
      <p className="mt-1 text-xs leading-5 text-slate-600">{value}</p>
    </div>
  );
}

function MetricTile({ icon: Icon, label, value, helper }: {
  icon: LucideIcon;
  label: string;
  value: string;
  helper: string;
}) {
  return (
    <div className="surface-tile rounded-[18px] p-2.5">
      <div className="flex items-center justify-between gap-3">
        <div className="rounded-2xl bg-teal-50 p-2 text-teal-700">
          <Icon className="h-4 w-4" />
        </div>
        <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-600">{label}</p>
      </div>
      <p className="mt-2.5 text-base font-semibold leading-none text-slate-950">{value}</p>
      <p className="mt-1 text-[11px] leading-4 text-slate-600">{helper}</p>
    </div>
  );
}

function TrendLineChart({ points }: { points: TrendPoint[] }) {
  const max = Math.max(...points.map((point) => point.value), 1);
  const coords = points.map((point, index) => {
    const x = 18 + index * (304 / Math.max(points.length - 1, 1));
    const y = 92 - (point.value / max) * 68;
    return { ...point, x, y };
  });
  const path = coords.map((point, index) => `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`).join(" ");
  const area = `${path} L ${coords.at(-1)?.x ?? 322} 104 L 18 104 Z`;

  return (
    <div className="rounded-[22px] border border-teal-100 bg-white/86 p-2.5" data-testid="overview-chat-trend">
      <div className="mb-2 flex items-center justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-slate-950">最近 7 天问答趋势</p>
          <p className="mt-1 text-xs text-slate-600">小点标记低置信回答，帮助发现知识缺口。</p>
        </div>
        <Badge variant="outline">{formatNumber(points.reduce((sum, point) => sum + point.value, 0))} 轮</Badge>
      </div>
      <svg viewBox="0 0 340 126" className="h-20 w-full" role="img" aria-label="最近七天问答趋势">
        <defs>
          <linearGradient id="trend-area" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="rgba(15,118,110,0.22)" />
            <stop offset="100%" stopColor="rgba(15,118,110,0.02)" />
          </linearGradient>
        </defs>
        {[24, 58, 92].map((y) => <line key={y} x1="18" x2="322" y1={y} y2={y} stroke="rgba(148,163,184,0.22)" />)}
        <path d={area} fill="url(#trend-area)" />
        <path d={path} fill="none" stroke="#0f766e" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
        {coords.map((point) => (
          <g key={point.label}>
            <circle cx={point.x} cy={point.y} r="4" fill="#0f766e" />
            {point.lowConfidence > 0 ? <circle cx={point.x} cy={point.y - 12} r="3.5" fill="#f59e0b" /> : null}
            <text x={point.x} y="121" textAnchor="middle" className="fill-slate-600 text-[10px] font-semibold">
              {point.label}
            </text>
          </g>
        ))}
      </svg>
    </div>
  );
}

function LatencyDistribution({ segments }: { segments: LatencySegment[] }) {
  const total = segments.reduce((sum, segment) => sum + segment.value, 0);

  return (
    <div className="rounded-[22px] border border-teal-100 bg-white/86 p-2.5" data-testid="overview-latency-distribution">
      <div className="mb-2 flex items-center justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-slate-950">检索耗时分布</p>
          <p className="mt-1 text-xs text-slate-600">用最近回答的 retrieval_ms 判断性能稳定性。</p>
        </div>
        <Clock3 className="h-4 w-4 text-teal-700" />
      </div>
      <div className="flex h-3 overflow-hidden rounded-full bg-slate-100">
        {total === 0 ? (
          <div className="h-full w-full bg-slate-200" />
        ) : (
          segments.map((segment) => (
            <div key={segment.label} className={cn("h-full", toneClasses[segment.tone].bar)} style={{ width: `${Math.max(4, (segment.value / total) * 100)}%` }} />
          ))
        )}
      </div>
      <div className="mt-3 grid grid-cols-3 gap-2">
        {segments.map((segment) => (
          <div key={segment.label} className="rounded-2xl bg-white/78 px-3 py-2">
            <p className="text-xs font-semibold text-slate-950">{segment.label}</p>
            <p className="mt-1 text-[11px] text-slate-600">{formatNumber(segment.value)} 次</p>
          </div>
        ))}
      </div>
    </div>
  );
}

function ActionItem({ label, detail, to, tone, icon: Icon }: {
  label: string;
  detail: string;
  to: string;
  tone: Tone;
  icon: LucideIcon;
}) {
  return (
    <Link
      to={to}
      className="group flex items-center justify-between gap-3 rounded-[22px] border border-teal-100 bg-white/86 p-4 transition hover:border-teal-300 hover:bg-white"
    >
      <div className="flex min-w-0 items-start gap-3">
        <div className={cn("rounded-2xl p-2", toneClasses[tone].soft)}>
          <Icon className="h-4 w-4" />
        </div>
        <div className="min-w-0">
          <p className="text-sm font-semibold text-slate-950">{label}</p>
          <p className="mt-1 text-xs leading-5 text-slate-600">{detail}</p>
        </div>
      </div>
      <ArrowRight className="h-4 w-4 shrink-0 text-slate-500 transition group-hover:translate-x-0.5 group-hover:text-teal-700" />
    </Link>
  );
}

function AssetStreamCard({
  documents,
  categories,
}: {
  documents: DocumentSummary[];
  categories: Array<{ label: string; document_count: number }>;
}) {
  const maxCategory = Math.max(...categories.map((entry) => entry.document_count), 1);

  return (
    <Card className="glass-panel h-full" data-testid="overview-asset-stream">
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-lg">
          <LineChart className="h-4 w-4 text-teal-700" />
          知识资产流
          <TitleInfoIcon label="知识资产流说明">最近文档与主题重心放在同一处扫读。</TitleInfoIcon>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="space-y-2">
          {documents.slice(0, 1).map((document) => (
            <RecentDocumentCard key={document.document_id} document={document} />
          ))}
        </div>
        <div className="border-t border-teal-100 pt-3">
          <div className="mb-3 flex items-center justify-between">
            <p className="text-sm font-semibold text-slate-950">主题分布</p>
            <Badge variant="outline">{categories.length}</Badge>
          </div>
          <div className="space-y-2">
            {categories.length === 0 ? (
              <p className="text-sm text-slate-600">当前还没有足够主题数据。</p>
            ) : (
              categories.slice(0, 3).map((item) => (
                <TopicRow key={item.label} label={item.label} value={item.document_count} max={maxCategory} />
              ))
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function RecentDocumentCard({ document }: { document: DocumentSummary }) {
  return (
    <div className="surface-tile rounded-[18px] p-2.5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="break-words text-sm font-semibold leading-5 text-slate-950">{shortText(document.name, 42)}</p>
          <p className="mt-1 break-words text-xs leading-5 text-slate-600">{document.theme || "未分类"}</p>
        </div>
        <Badge variant={document.status === "indexed" ? "soft" : "outline"}>{document.status}</Badge>
      </div>
      <div className="mt-1.5 flex items-center justify-between gap-3 text-xs text-slate-600">
        <span>{shortText(document.relative_path, 30)}</span>
        <span>{formatDateTime(document.updated_at)}</span>
      </div>
    </div>
  );
}

function TopicRow({ label, value, max }: { label: string; value: number; max: number }) {
  const width = Math.max(8, Math.round((value / max) * 100));
  return (
    <div className="rounded-[18px] border border-teal-100 bg-white/86 p-2.5">
      <div className="mb-2 flex items-center justify-between gap-3">
        <p className="truncate text-sm font-semibold text-slate-950">{label}</p>
        <span className="text-sm font-semibold text-teal-800">{formatNumber(value)}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-teal-50">
        <div className="h-full rounded-full bg-gradient-to-r from-teal-700 to-cyan-400" style={{ width: `${width}%` }} />
      </div>
    </div>
  );
}

const toneClasses: Record<Tone, { dot: string; soft: string; bar: string }> = {
  good: {
    dot: "bg-teal-600",
    soft: "bg-teal-50 text-teal-700",
    bar: "bg-teal-700",
  },
  warn: {
    dot: "bg-amber-500",
    soft: "bg-amber-50 text-amber-700",
    bar: "bg-amber-400",
  },
  danger: {
    dot: "bg-rose-500",
    soft: "bg-rose-50 text-rose-700",
    bar: "bg-rose-500",
  },
  neutral: {
    dot: "bg-slate-400",
    soft: "bg-slate-100 text-slate-700",
    bar: "bg-slate-400",
  },
};
