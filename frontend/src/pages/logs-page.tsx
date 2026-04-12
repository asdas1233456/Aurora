import { useDeferredValue, useMemo, useState } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, CheckCircle2, Filter, Loader2, RefreshCw, Trash2 } from "lucide-react";
import { Virtuoso } from "react-virtuoso";

import { clearLogs, getLogs } from "@/api/client";
import {
  AlertDialog,
  AlertDialogActionControl,
  AlertDialogCancelControl,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { TitleInfoIcon } from "@/components/ui/title-info-icon";
import { formatBytes, formatNumber } from "@/lib/format";
import { cn } from "@/lib/utils";


const LOG_LIMIT_OPTIONS = ["100", "300", "500", "1000"] as const;
const DEFAULT_LOG_LIMIT = "300";

export function LogsPage() {
  const queryClient = useQueryClient();
  const [filters, setFilters] = useState({
    level: "",
    keyword: "",
    limit: DEFAULT_LOG_LIMIT,
  });
  const deferredKeyword = useDeferredValue(filters.keyword);
  const safeLimit = LOG_LIMIT_OPTIONS.includes(filters.limit as (typeof LOG_LIMIT_OPTIONS)[number])
    ? filters.limit
    : DEFAULT_LOG_LIMIT;

  const logsQuery = useQuery({
    queryKey: ["logs", filters.level, deferredKeyword, safeLimit],
    queryFn: () =>
      getLogs({
        level: filters.level,
        keyword: deferredKeyword,
        limit: Number(safeLimit),
      }),
  });

  const clearMutation = useMutation({
    mutationFn: clearLogs,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["logs"] });
    },
  });

  const lines = logsQuery.data?.lines ?? [];
  const summary = logsQuery.data?.summary;
  const highlightedKeyword = deferredKeyword.trim();

  const overviewTiles = useMemo(
    () => [
      { label: "日志行数", value: formatNumber(summary?.line_count ?? 0) },
      { label: "文件大小", value: formatBytes(summary?.size_bytes ?? 0) },
      { label: "当前筛选", value: filters.level || "ALL" },
    ],
    [filters.level, summary?.line_count, summary?.size_bytes],
  );

  const terminalStatus = getTerminalStatus({
    isLoading: logsQuery.isLoading,
    isFetching: logsQuery.isFetching,
    isError: logsQuery.isError,
    error: logsQuery.error,
    lineCount: lines.length,
    clearPending: clearMutation.isPending,
    clearError: clearMutation.isError,
    clearSuccess: clearMutation.isSuccess,
    clearErrorValue: clearMutation.error,
  });

  return (
    <section className="grid min-h-[calc(100dvh-9.5rem)] gap-2" data-testid="logs-page">
      <Card className="glass-panel flex min-h-0 flex-col overflow-hidden" data-testid="logs-terminal-card">
        <CardHeader className="space-y-2 px-2 py-2 md:space-y-3 md:px-4 md:py-3">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <CardTitle className="flex items-center gap-2 whitespace-nowrap">
                <Filter className="h-4 w-4 text-teal-700" />
                实时日志流
                <TitleInfoIcon label="实时日志流说明">
                  先看日志主体，再展开低频筛选；刷新和清空状态会即时反馈。
                </TitleInfoIcon>
              </CardTitle>
            </div>
            <StatusPill tone={terminalStatus.tone} message={terminalStatus.message} />
          </div>

          <div className="grid gap-2 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end xl:grid-cols-[minmax(0,1fr)_10rem_9rem_minmax(280px,0.8fr)_auto]">
            <div className="space-y-0 md:space-y-2">
              <Label htmlFor="log-keyword" className="sr-only md:not-sr-only">关键字</Label>
              <Input
                id="log-keyword"
                value={filters.keyword}
                onChange={(event) => setFilters((current) => ({ ...current, keyword: event.target.value }))}
                placeholder="搜索 request_id / route / provider"
                data-testid="log-keyword-input"
              />
            </div>
            <div className="hidden xl:block">
              <LogLevelSelect
                id="log-level-xl"
                testId="log-level-select"
                value={filters.level}
                onChange={(value) => setFilters((current) => ({ ...current, level: value }))}
              />
            </div>
            <div className="hidden xl:block">
              <LogLimitSelect
                id="log-limit-xl"
                testId="log-limit-select"
                value={safeLimit}
                onChange={(value) => setFilters((current) => ({ ...current, limit: value }))}
              />
            </div>
            <SummaryStrip className="hidden xl:grid" tiles={overviewTiles} />
            <div className="grid grid-cols-2 gap-2 sm:flex sm:flex-wrap lg:justify-end">
              <Button
                type="button"
                variant="secondary"
                onClick={() => logsQuery.refetch()}
                disabled={logsQuery.isFetching || clearMutation.isPending}
                data-testid="refresh-logs-button"
              >
                <RefreshCw className={cn("h-4 w-4", logsQuery.isFetching ? "animate-spin" : "")} />
                {logsQuery.isFetching ? "刷新中" : "刷新"}
              </Button>
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button
                    type="button"
                    variant="destructive"
                    disabled={clearMutation.isPending}
                    data-testid="clear-logs-button"
                  >
                    {clearMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
                    {clearMutation.isPending ? "清空中" : "清空日志"}
                  </Button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>确认清空日志？</AlertDialogTitle>
                    <AlertDialogDescription>
                      这会删除当前日志文件内容，线上排障线索可能无法恢复。建议确认已经完成导出或问题记录后再继续。
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancelControl type="button" disabled={clearMutation.isPending}>
                      取消
                    </AlertDialogCancelControl>
                    <AlertDialogActionControl
                      type="button"
                      disabled={clearMutation.isPending}
                      onClick={() => {
                        if (!clearMutation.isPending) {
                          clearMutation.mutate();
                        }
                      }}
                    >
                      确认清空
                    </AlertDialogActionControl>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            </div>
          </div>

          <details className="group rounded-2xl border border-white/70 bg-white/60 px-3 py-2 md:hidden" data-testid="logs-mobile-filter-panel">
            <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-sm font-semibold text-slate-800 outline-none focus-visible:ring-2 focus-visible:ring-teal-500/50">
              筛选和摘要
              <ChevronText value={`${filters.level || "ALL"} / ${safeLimit} 行`} />
            </summary>
            <div className="mt-3 grid grid-cols-2 gap-3">
              <LogLevelSelect
                id="log-level-mobile"
                testId="log-level-select-mobile"
                value={filters.level}
                onChange={(value) => setFilters((current) => ({ ...current, level: value }))}
              />
              <LogLimitSelect
                id="log-limit-mobile"
                testId="log-limit-select-mobile"
                value={safeLimit}
                onChange={(value) => setFilters((current) => ({ ...current, limit: value }))}
              />
            </div>
            <SummaryStrip className="mt-3" tiles={overviewTiles} />
          </details>

          <div className="hidden gap-3 md:grid md:grid-cols-[10rem_9rem_minmax(300px,1fr)] md:items-end xl:hidden">
            <LogLevelSelect
              id="log-level-md"
              testId="log-level-select-md"
              value={filters.level}
              onChange={(value) => setFilters((current) => ({ ...current, level: value }))}
            />
            <LogLimitSelect
              id="log-limit-md"
              testId="log-limit-select-md"
              value={safeLimit}
              onChange={(value) => setFilters((current) => ({ ...current, limit: value }))}
            />
            <SummaryStrip tiles={overviewTiles} />
          </div>
        </CardHeader>

        <CardContent className="flex min-h-0 flex-1 flex-col px-3 pb-3">
          <div
            className="terminal-shell logs-terminal-viewport relative overflow-hidden rounded-[24px] border border-slate-800/60 md:rounded-3xl"
            data-testid="logs-terminal"
          >
            {logsQuery.isFetching && lines.length > 0 ? (
              <div className="absolute right-3 top-3 z-10 inline-flex items-center gap-2 rounded-full border border-white/10 bg-slate-950/80 px-3 py-1 text-xs text-slate-200 backdrop-blur">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                正在刷新
              </div>
            ) : null}

            {logsQuery.isLoading ? (
              <TerminalMessage icon="loading" title="正在加载日志" description="正在读取最新日志内容，请稍候。" />
            ) : logsQuery.isError ? (
              <TerminalMessage icon="error" title="日志加载失败" description={getErrorMessage(logsQuery.error)} />
            ) : lines.length === 0 ? (
              <TerminalMessage icon="empty" title="没有匹配日志" description="当前筛选条件下没有日志行。可以放宽关键字、级别或刷新后再看。" />
            ) : (
              <Virtuoso
                data-testid="logs-terminal-scroller"
                className="snow-scrollbar"
                style={{ height: "100%" }}
                totalCount={lines.length}
                itemContent={(index) => (
                  <LogLine
                    index={index}
                    line={lines[index] ?? ""}
                    highlightedKeyword={highlightedKeyword}
                  />
                )}
              />
            )}
          </div>
        </CardContent>
      </Card>
    </section>
  );
}

function LogLine({
  index,
  line,
  highlightedKeyword,
}: {
  index: number;
  line: string;
  highlightedKeyword: string;
}) {
  const emphasized = highlightedKeyword
    ? line.replace(
        new RegExp(highlightedKeyword.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi"),
        (match) => `[[${match}]]`,
      )
    : line;
  const parts = emphasized.split(/\[\[(.*?)\]\]/g);

  return (
    <div className="border-b border-slate-800/40 px-4 py-3 font-mono text-xs leading-6 text-slate-200">
      {parts.map((part, partIndex) =>
        partIndex % 2 === 1 ? (
          <mark key={`${index}-${partIndex}`} className="rounded bg-teal-400/25 px-1 text-white">
            {part}
          </mark>
        ) : (
          <span key={`${index}-${partIndex}`}>{part}</span>
        ),
      )}
    </div>
  );
}

function LogLevelSelect({
  id = "log-level",
  testId = "log-level-select",
  value,
  onChange,
}: {
  id?: string;
  testId?: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>级别</Label>
      <Select
        value={value || "ALL"}
        onValueChange={(nextValue) => onChange(nextValue === "ALL" ? "" : nextValue)}
      >
        <SelectTrigger id={id} data-testid={testId}>
          <SelectValue placeholder="全部级别" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="ALL">全部级别</SelectItem>
          <SelectItem value="DEBUG">DEBUG</SelectItem>
          <SelectItem value="INFO">INFO</SelectItem>
          <SelectItem value="WARNING">WARNING</SelectItem>
          <SelectItem value="ERROR">ERROR</SelectItem>
        </SelectContent>
      </Select>
    </div>
  );
}

function LogLimitSelect({
  id = "log-limit",
  testId = "log-limit-select",
  value,
  onChange,
}: {
  id?: string;
  testId?: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>数量</Label>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger id={id} data-testid={testId}>
          <SelectValue placeholder="选择数量" />
        </SelectTrigger>
        <SelectContent>
          {LOG_LIMIT_OPTIONS.map((option) => (
            <SelectItem key={option} value={option}>
              {option} 行
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

function SummaryStrip({
  tiles,
  className,
}: {
  tiles: Array<{ label: string; value: string }>;
  className?: string;
}) {
  return (
    <div className={cn("grid grid-cols-3 gap-2", className)}>
      {tiles.map((tile) => (
        <div key={tile.label} className="min-w-0 rounded-2xl border border-white/70 bg-white/72 px-3 py-2">
          <p className="truncate text-[11px] text-slate-500">{tile.label}</p>
          <p className="mt-1 truncate text-sm font-semibold text-slate-900">{tile.value}</p>
        </div>
      ))}
    </div>
  );
}

function ChevronText({ value }: { value: string }) {
  return (
    <span className="inline-flex shrink-0 items-center rounded-full bg-white/80 px-2.5 py-1 text-xs font-medium text-slate-600 ring-1 ring-teal-100">
      {value}
    </span>
  );
}

function TerminalMessage({
  icon,
  title,
  description,
}: {
  icon: "loading" | "error" | "empty";
  title: string;
  description: string;
}) {
  const Icon = icon === "loading" ? Loader2 : icon === "error" ? AlertCircle : CheckCircle2;

  return (
    <div className="flex h-full items-center justify-center px-6 text-center" data-testid={`logs-${icon}-state`}>
      <div className="max-w-md">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl border border-white/10 bg-white/8 text-teal-200">
          <Icon className={cn("h-5 w-5", icon === "loading" ? "animate-spin" : "")} />
        </div>
        <h3 className="mt-4 text-base font-semibold text-white">{title}</h3>
        <p className="mt-2 text-sm leading-6 text-slate-300">{description}</p>
      </div>
    </div>
  );
}

function StatusPill({ tone, message }: { tone: "neutral" | "success" | "warning" | "error"; message: string }) {
  return (
    <div
      className={cn(
        "inline-flex max-w-[58vw] shrink-0 items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-medium md:max-w-none",
        tone === "success" && "border-teal-200 bg-teal-50 text-teal-800",
        tone === "warning" && "border-amber-200 bg-amber-50 text-amber-800",
        tone === "error" && "border-rose-200 bg-rose-50 text-rose-700",
        tone === "neutral" && "border-slate-200 bg-white/80 text-slate-700",
      )}
      data-testid="logs-status"
      aria-live="polite"
    >
      {tone === "error" ? <AlertCircle className="h-3.5 w-3.5" /> : null}
      {tone === "success" ? <CheckCircle2 className="h-3.5 w-3.5" /> : null}
      {tone === "warning" || tone === "neutral" ? <Loader2 className={cn("h-3.5 w-3.5", tone === "warning" ? "animate-spin" : "")} /> : null}
      <span className="truncate">{message}</span>
    </div>
  );
}

function getTerminalStatus({
  isLoading,
  isFetching,
  isError,
  error,
  lineCount,
  clearPending,
  clearError,
  clearSuccess,
  clearErrorValue,
}: {
  isLoading: boolean;
  isFetching: boolean;
  isError: boolean;
  error: unknown;
  lineCount: number;
  clearPending: boolean;
  clearError: boolean;
  clearSuccess: boolean;
  clearErrorValue: unknown;
}) {
  if (clearPending) {
    return { tone: "warning" as const, message: "正在清空日志" };
  }
  if (clearError) {
    return { tone: "error" as const, message: `清空失败：${getErrorMessage(clearErrorValue)}` };
  }
  if (isLoading) {
    return { tone: "warning" as const, message: "正在加载日志" };
  }
  if (isError) {
    return { tone: "error" as const, message: `加载失败：${getErrorMessage(error)}` };
  }
  if (clearSuccess) {
    return { tone: "success" as const, message: "日志已清空" };
  }
  if (isFetching) {
    return { tone: "warning" as const, message: "正在刷新日志" };
  }
  if (lineCount === 0) {
    return { tone: "neutral" as const, message: "暂无匹配日志" };
  }
  return { tone: "success" as const, message: `已加载 ${formatNumber(lineCount)} 行` };
}

function getErrorMessage(error: unknown) {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  if (typeof error === "string" && error.trim()) {
    return error.trim();
  }
  return "请检查后端日志接口或稍后重试。";
}
