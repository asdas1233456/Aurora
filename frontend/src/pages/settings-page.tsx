import { useEffect, type ReactNode } from "react";

import { Controller, useForm, type Control, type UseFormReturn } from "react-hook-form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, CheckCircle2, ChevronDown, Gauge, Loader2, LockKeyhole, Save, SlidersHorizontal, TestTube2, XCircle } from "lucide-react";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

import { getRuntimeHelp, getSettings, getWorkspaceBootstrap, saveSettings, testSettings } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import { TitleInfoIcon } from "@/components/ui/title-info-icon";
import { formatDuration } from "@/lib/format";
import { cn } from "@/lib/utils";


const settingsSchema = z.object({
  llm_provider: z.string().min(1),
  embedding_provider: z.string().min(1),
  llm_model: z.string().min(1, "请输入 LLM 模型名。"),
  embedding_model: z.string().min(1, "请输入 Embedding 模型名。"),
  llm_api_base: z.string().optional(),
  embedding_api_base: z.string().optional(),
  chunk_size: z.number().min(100).max(4000),
  chunk_overlap: z.number().min(0).max(1000),
  top_k: z.number().min(1).max(20),
  max_history_turns: z.number().min(0).max(20),
  no_answer_min_score: z.number().min(0).max(1),
  llm_temperature: z.number().min(0).max(2),
  llm_timeout: z.number().min(1).max(600),
  llm_max_tokens: z.number().min(128).max(16384),
  collection_name: z.string().min(1),
  log_level: z.string().min(1),
});

type SettingsFormValues = z.infer<typeof settingsSchema>;
type SettingsForm = UseFormReturn<SettingsFormValues>;
type SettingsControl = Control<SettingsFormValues>;

export function SettingsPage() {
  const queryClient = useQueryClient();
  const settingsQuery = useQuery({
    queryKey: ["settings"],
    queryFn: getSettings,
  });
  const runtimeHelpQuery = useQuery({
    queryKey: ["runtime-help"],
    queryFn: getRuntimeHelp,
  });
  const workspaceQuery = useQuery({
    queryKey: ["workspace-bootstrap"],
    queryFn: getWorkspaceBootstrap,
  });

  const form = useForm<SettingsFormValues>({
    resolver: zodResolver(settingsSchema),
    defaultValues: {
      llm_provider: "openai",
      embedding_provider: "openai",
      llm_model: "",
      embedding_model: "",
      llm_api_base: "",
      embedding_api_base: "",
      chunk_size: 800,
      chunk_overlap: 100,
      top_k: 4,
      max_history_turns: 6,
      no_answer_min_score: 0.22,
      llm_temperature: 0.2,
      llm_timeout: 60,
      llm_max_tokens: 2048,
      collection_name: "ai_kb_docs",
      log_level: "INFO",
    },
  });

  useEffect(() => {
    if (!settingsQuery.data) {
      return;
    }
    form.reset({
      llm_provider: settingsQuery.data.llm_provider,
      embedding_provider: settingsQuery.data.embedding_provider,
      llm_model: settingsQuery.data.llm_model,
      embedding_model: settingsQuery.data.embedding_model,
      llm_api_base: settingsQuery.data.llm_api_base,
      embedding_api_base: settingsQuery.data.embedding_api_base,
      chunk_size: settingsQuery.data.chunk_size,
      chunk_overlap: settingsQuery.data.chunk_overlap,
      top_k: settingsQuery.data.top_k,
      max_history_turns: settingsQuery.data.max_history_turns,
      no_answer_min_score: settingsQuery.data.no_answer_min_score,
      llm_temperature: settingsQuery.data.llm_temperature,
      llm_timeout: settingsQuery.data.llm_timeout,
      llm_max_tokens: settingsQuery.data.llm_max_tokens,
      collection_name: settingsQuery.data.collection_name,
      log_level: settingsQuery.data.log_level,
    });
  }, [form, settingsQuery.data]);

  const saveMutation = useMutation({
    mutationFn: (values: SettingsFormValues) => saveSettings(buildSettingsPayload(values)),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["settings"] });
      await queryClient.invalidateQueries({ queryKey: ["workspace-bootstrap"] });
    },
  });

  const testMutation = useMutation({
    mutationFn: (values: SettingsFormValues) => testSettings(buildSettingsPayload(values)),
  });

  const overview = workspaceQuery.data?.overview;
  const managedByOps = settingsQuery.data?.operations_managed_fields ?? runtimeHelpQuery.data?.managed_by_ops ?? [];
  const actionStatus = getActionStatus({
    settingsLoading: settingsQuery.isLoading,
    settingsError: settingsQuery.isError,
    settingsErrorValue: settingsQuery.error,
    savePending: saveMutation.isPending,
    saveSuccess: saveMutation.isSuccess,
    saveError: saveMutation.isError,
    saveErrorValue: saveMutation.error,
    testPending: testMutation.isPending,
    testSuccess: testMutation.isSuccess,
    testError: testMutation.isError,
    testErrorValue: testMutation.error,
  });
  const disableActions = settingsQuery.isLoading || saveMutation.isPending || testMutation.isPending;

  return (
    <section className="grid min-h-[calc(100dvh-9.5rem)] gap-2 xl:grid-cols-[minmax(280px,340px)_minmax(0,1fr)]" data-testid="settings-page">
      <aside className="order-2 xl:order-1">
        <Card className="glass-panel" data-testid="settings-runtime-status">
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2">
              <Gauge className="h-4 w-4 text-teal-700" />
              只读运行态
              <TitleInfoIcon label="只读运行态说明">这些状态来自运行环境，只展示，不在这里开关。</TitleInfoIcon>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid gap-2 sm:grid-cols-3 xl:grid-cols-1">
              <RuntimeStatusTile label="LLM Key" ready={overview?.llm_api_ready} />
              <RuntimeStatusTile label="Embedding Key" ready={overview?.embedding_api_ready} />
              <RuntimeStatusTile label="知识库检索" ready={overview?.knowledge_base_ready} />
            </div>
            <details className="group border-t border-teal-100/80 pt-3" data-testid="settings-ops-managed">
              <summary className="flex cursor-pointer list-none items-center justify-between gap-3 rounded-2xl py-1 text-sm font-semibold text-slate-800 outline-none focus-visible:ring-2 focus-visible:ring-teal-500/50">
                <span className="inline-flex items-center gap-2">
                  <LockKeyhole className="h-4 w-4 text-teal-700" />
                  运维托管字段
                </span>
                <ChevronDown className="h-4 w-4 shrink-0 text-slate-500 transition group-open:rotate-180" />
              </summary>
              <p className="mt-2 text-xs leading-5 text-slate-500">敏感项和部署项由运维注入，避免在前端误改。</p>
              <div className="mt-3 flex flex-wrap gap-2">
                {managedByOps.length > 0 ? (
                  managedByOps.map((item) => (
                    <Badge key={item} variant="outline">
                      {item}
                    </Badge>
                  ))
                ) : (
                  <p className="text-sm text-slate-500">暂无托管字段。</p>
                )}
              </div>
            </details>
          </CardContent>
        </Card>
      </aside>

      <form
        className="order-1 grid content-start gap-2 xl:order-2"
        onSubmit={form.handleSubmit((values) => saveMutation.mutate(values))}
        data-testid="settings-form"
      >
        <Card className="glass-panel sticky top-3 z-20" data-testid="settings-action-bar">
          <CardContent className="flex flex-col gap-2 px-3 pb-3 pt-3 lg:flex-row lg:items-center lg:justify-between">
            <ActionStatus tone={actionStatus.tone} title={actionStatus.title} message={actionStatus.message} />
            <div className="grid grid-cols-2 gap-2 sm:flex sm:flex-wrap lg:justify-end">
              <Button
                type="button"
                variant="secondary"
                onClick={form.handleSubmit((values) => testMutation.mutate(values))}
                disabled={disableActions}
                data-testid="test-settings-button"
              >
                {testMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <TestTube2 className="h-4 w-4" />}
                {testMutation.isPending ? "测试中" : "测试连接"}
              </Button>
              <Button
                type="submit"
                disabled={disableActions}
                data-testid="save-settings-button"
              >
                {saveMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                {saveMutation.isPending ? "保存中" : "保存配置"}
              </Button>
            </div>
          </CardContent>
          {testMutation.data ? (
            <div className="grid gap-2 border-t border-teal-100/70 px-3 pb-3 pt-3 md:grid-cols-2" data-testid="settings-test-results" aria-live="polite" role="status">
              <LatencyTile label="LLM" ok={testMutation.data.llm.ok} detail={testMutation.data.llm.message} latency={testMutation.data.llm.latency_ms} />
              <LatencyTile label="Embedding" ok={testMutation.data.embedding.ok} detail={testMutation.data.embedding.message} latency={testMutation.data.embedding.latency_ms} />
            </div>
          ) : null}
        </Card>

        <Card className="glass-panel" data-testid="settings-editable-card">
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2">
              <SlidersHorizontal className="h-4 w-4 text-teal-700" />
              可调参数中心
              <TitleInfoIcon label="可调参数中心说明">高频配置留在首屏，高级参数默认折叠，避免上线前误调。</TitleInfoIcon>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <FormSection title="模型连接" description="Provider、模型名和兼容 API Base。">
              <div className="grid gap-3 xl:grid-cols-2">
                <FormSelect control={form.control} name="llm_provider" label="LLM Provider" options={["openai", "openai_compatible", "deepseek", "qwen", "zhipu", "moonshot", "siliconflow", "openrouter"]} />
                <FormSelect control={form.control} name="embedding_provider" label="Embedding Provider" options={["openai", "openai_compatible", "qwen", "zhipu", "siliconflow"]} />
                <FormInput form={form} name="llm_model" label="LLM Model" />
                <FormInput form={form} name="embedding_model" label="Embedding Model" />
                <details className="group rounded-2xl border border-teal-100/80 bg-white/58 px-3 py-2 xl:col-span-2" data-testid="settings-api-base-section">
                  <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-sm font-semibold text-slate-800 outline-none focus-visible:ring-2 focus-visible:ring-teal-500/50">
                    兼容 API Base
                    <ChevronDown className="h-4 w-4 shrink-0 text-slate-500 transition group-open:rotate-180" />
                  </summary>
                  <div className="mt-3 grid gap-3 xl:grid-cols-2">
                    <FormInput form={form} name="llm_api_base" label="LLM API Base" helper="留空时使用 provider 默认地址。" />
                    <FormInput form={form} name="embedding_api_base" label="Embedding API Base" helper="留空时使用 provider 默认地址。" />
                  </div>
                </details>
              </div>
            </FormSection>

            <FormSection title="检索生成" description="影响答案召回、拒答阈值和生成稳定性。">
              <div className="grid gap-3 lg:grid-cols-3">
                <FormSlider control={form.control} name="top_k" label="Top K" min={1} max={20} step={1} />
                <FormSlider control={form.control} name="llm_temperature" label="Temperature" min={0} max={2} step={0.1} />
                <FormSlider control={form.control} name="no_answer_min_score" label="No Answer Min Score" min={0} max={1} step={0.01} />
              </div>
              <div className="mt-3 grid gap-3 xl:grid-cols-2">
                <FormInput form={form} name="collection_name" label="Collection Name" />
                <FormSelect control={form.control} name="log_level" label="Log Level" options={["DEBUG", "INFO", "WARNING", "ERROR"]} />
              </div>
            </FormSection>

            <details className="group border-t border-teal-100/80 pt-3" data-testid="settings-advanced-section">
              <summary className="flex cursor-pointer list-none items-center justify-between gap-3 rounded-2xl px-1 py-1 text-left outline-none focus-visible:ring-2 focus-visible:ring-teal-500/50">
                <span>
                  <span className="block text-sm font-semibold text-slate-900">高级参数</span>
                  <span className="mt-1 block text-xs leading-5 text-slate-500">切块、历史轮数、超时和 token 上限。</span>
                </span>
                <ChevronDown className="h-4 w-4 shrink-0 text-slate-500 transition group-open:rotate-180" />
              </summary>
              <div className="grid gap-3 pb-1 pt-3 xl:grid-cols-2">
                <FormInput form={form} name="chunk_size" label="Chunk Size" type="number" min={100} max={4000} />
                <FormInput form={form} name="chunk_overlap" label="Chunk Overlap" type="number" min={0} max={1000} />
                <FormInput form={form} name="max_history_turns" label="Max History Turns" type="number" min={0} max={20} />
                <FormInput form={form} name="llm_timeout" label="Timeout (s)" type="number" min={1} max={600} />
                <FormInput form={form} name="llm_max_tokens" label="Max Tokens" type="number" min={128} max={16384} />
              </div>
            </details>
          </CardContent>
        </Card>
      </form>
    </section>
  );
}

function buildSettingsPayload(values: SettingsFormValues) {
  return {
    LLM_PROVIDER: values.llm_provider,
    EMBEDDING_PROVIDER: values.embedding_provider,
    LLM_MODEL: values.llm_model,
    EMBEDDING_MODEL: values.embedding_model,
    LLM_API_BASE: values.llm_api_base,
    EMBEDDING_API_BASE: values.embedding_api_base,
    CHUNK_SIZE: values.chunk_size,
    CHUNK_OVERLAP: values.chunk_overlap,
    TOP_K: values.top_k,
    MAX_HISTORY_TURNS: values.max_history_turns,
    NO_ANSWER_MIN_SCORE: values.no_answer_min_score,
    LLM_TEMPERATURE: values.llm_temperature,
    LLM_TIMEOUT: values.llm_timeout,
    LLM_MAX_TOKENS: values.llm_max_tokens,
    CHROMA_COLLECTION_NAME: values.collection_name,
    LOG_LEVEL: values.log_level,
  };
}

function RuntimeStatusTile({ label, ready }: { label: string; ready?: boolean }) {
  const pending = ready === undefined;
  const Icon = pending ? Loader2 : ready ? CheckCircle2 : XCircle;
  const text = pending ? "加载中" : ready ? "就绪" : "未就绪";

  return (
    <div className="flex items-center justify-between gap-3 rounded-2xl border border-white/70 bg-white/72 px-3 py-2.5">
      <span className="text-sm text-slate-700">{label}</span>
      <Badge
        variant={ready ? "soft" : "outline"}
        className={cn(
          "gap-1.5",
          ready === false ? "text-rose-700 ring-rose-200" : "",
        )}
      >
        <Icon className={cn("h-3.5 w-3.5", pending ? "animate-spin" : "")} />
        {text}
      </Badge>
    </div>
  );
}

function ActionStatus({
  tone,
  title,
  message,
}: {
  tone: "neutral" | "success" | "warning" | "error";
  title: string;
  message: string;
}) {
  const Icon = tone === "success" ? CheckCircle2 : tone === "error" ? AlertCircle : tone === "warning" ? Loader2 : LockKeyhole;

  return (
    <div className="flex min-w-0 flex-1 items-start gap-2.5" aria-live="polite" role="status" data-testid="settings-action-status">
      <div
        className={cn(
          "mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-2xl",
          tone === "success" && "bg-teal-50 text-teal-700 ring-1 ring-teal-200",
          tone === "warning" && "bg-amber-50 text-amber-700 ring-1 ring-amber-200",
          tone === "error" && "bg-rose-50 text-rose-700 ring-1 ring-rose-200",
          tone === "neutral" && "bg-slate-50 text-slate-700 ring-1 ring-slate-200",
        )}
      >
        <Icon className={cn("h-4 w-4", tone === "warning" ? "animate-spin" : "")} />
      </div>
      <div className="min-w-0">
        <p className="text-sm font-semibold text-slate-900">{title}</p>
        <p className="mt-0.5 text-sm leading-5 text-slate-600">{message}</p>
      </div>
    </div>
  );
}

function LatencyTile({
  label,
  ok,
  detail,
  latency,
}: {
  label: string;
  ok: boolean;
  detail: string;
  latency: number;
}) {
  return (
    <div className="rounded-2xl border border-white/70 bg-white/72 px-3 py-2.5">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-semibold text-slate-900">{label}</p>
        <Badge variant={ok ? "soft" : "outline"} className={ok ? "" : "text-rose-700 ring-rose-200"}>
          {ok ? "OK" : "Fail"}
        </Badge>
      </div>
      <p className="mt-2 text-sm leading-6 text-slate-600">{detail}</p>
      <p className="mt-1 text-xs text-slate-500">{formatDuration(latency)}</p>
    </div>
  );
}

function FormSection({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <fieldset className="border-t border-teal-100/80 pt-3">
      <legend className="px-1">
        <span className="inline-flex items-center gap-2 text-sm font-semibold text-slate-900">
          {title}
          <TitleInfoIcon label={`${title}说明`}>{description}</TitleInfoIcon>
        </span>
      </legend>
      <span className="sr-only">{description}</span>
      {children}
    </fieldset>
  );
}

function FormInput({
  form,
  name,
  label,
  type = "text",
  min,
  max,
  helper,
}: {
  form: SettingsForm;
  name: keyof SettingsFormValues;
  label: string;
  type?: string;
  min?: number;
  max?: number;
  helper?: string;
}) {
  const error = form.formState.errors[name]?.message;
  const inputId = String(name);

  return (
    <div className="space-y-1.5">
      <Label htmlFor={inputId}>{label}</Label>
      <Input
        id={inputId}
        type={type}
        min={min}
        max={max}
        aria-invalid={Boolean(error)}
        {...form.register(name, { valueAsNumber: type === "number" })}
      />
      {helper ? <p className="text-xs leading-5 text-slate-500">{helper}</p> : null}
      {error ? <p className="text-xs leading-5 text-rose-600" role="alert">{String(error)}</p> : null}
    </div>
  );
}

function FormSlider({
  control,
  name,
  label,
  min,
  max,
  step,
}: {
  control: SettingsControl;
  name: keyof SettingsFormValues;
  label: string;
  min: number;
  max: number;
  step: number;
}) {
  return (
    <Controller
      control={control}
      name={name}
      render={({ field }) => (
        <div className="rounded-2xl border border-teal-100/80 bg-white/72 p-3">
          <div className="flex items-center justify-between gap-3">
            <Label>{label}</Label>
            <Badge variant="soft">{field.value}</Badge>
          </div>
          <Slider
            className="mt-3"
            min={min}
            max={max}
            step={step}
            value={[Number(field.value)]}
            onValueChange={(value) => field.onChange(value[0] ?? min)}
          />
        </div>
      )}
    />
  );
}

function FormSelect({
  control,
  name,
  label,
  options,
}: {
  control: SettingsControl;
  name: keyof SettingsFormValues;
  label: string;
  options: string[];
}) {
  const id = String(name);

  return (
    <Controller
      control={control}
      name={name}
      render={({ field }) => (
        <div className="space-y-1.5">
          <Label htmlFor={id}>{label}</Label>
          <Select value={String(field.value)} onValueChange={field.onChange}>
            <SelectTrigger id={id}>
              <SelectValue placeholder={`选择 ${label}`} />
            </SelectTrigger>
            <SelectContent>
              {options.map((option) => (
                <SelectItem key={option} value={option}>
                  {option}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}
    />
  );
}

function getActionStatus({
  settingsLoading,
  settingsError,
  settingsErrorValue,
  savePending,
  saveSuccess,
  saveError,
  saveErrorValue,
  testPending,
  testSuccess,
  testError,
  testErrorValue,
}: {
  settingsLoading: boolean;
  settingsError: boolean;
  settingsErrorValue: unknown;
  savePending: boolean;
  saveSuccess: boolean;
  saveError: boolean;
  saveErrorValue: unknown;
  testPending: boolean;
  testSuccess: boolean;
  testError: boolean;
  testErrorValue: unknown;
}) {
  if (settingsLoading) {
    return { tone: "warning" as const, title: "正在读取配置", message: "加载完成后即可测试连接或保存非敏感配置。" };
  }
  if (settingsError) {
    return { tone: "error" as const, title: "配置加载失败", message: getErrorMessage(settingsErrorValue) };
  }
  if (savePending) {
    return { tone: "warning" as const, title: "正在保存", message: "正在提交非敏感配置，请不要重复点击。" };
  }
  if (saveError) {
    return { tone: "error" as const, title: "保存失败", message: getErrorMessage(saveErrorValue) };
  }
  if (saveSuccess) {
    return { tone: "success" as const, title: "保存成功", message: "配置已写入，运行态信息已刷新。" };
  }
  if (testPending) {
    return { tone: "warning" as const, title: "正在测试连接", message: "正在检查 LLM 和 Embedding 可用性。" };
  }
  if (testError) {
    return { tone: "error" as const, title: "测试失败", message: getErrorMessage(testErrorValue) };
  }
  if (testSuccess) {
    return { tone: "success" as const, title: "测试完成", message: "最新连通性结果就在下方。" };
  }
  return { tone: "neutral" as const, title: "上线前检查", message: "建议先测试连接，确认通过后再保存配置。" };
}

function getErrorMessage(error: unknown) {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  if (typeof error === "string" && error.trim()) {
    return error.trim();
  }
  return "请检查后端接口或稍后重试。";
}
