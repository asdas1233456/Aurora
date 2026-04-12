import { useDeferredValue, useEffect, useMemo, useState } from "react";

import { Controller, useForm } from "react-hook-form";
import { useDropzone } from "react-dropzone";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowUpRight,
  BookOpen,
  FilePlus2,
  FolderSearch,
  Library,
  Network,
  PencilLine,
  RefreshCw,
  Search,
  Settings2,
  Tags,
  Trash2,
  UploadCloud,
  X,
} from "lucide-react";
import { Virtuoso } from "react-virtuoso";
import { z } from "zod";

import {
  deleteDocuments,
  getDocumentPreview,
  getDocuments,
  getKnowledgeStatus,
  rebuildKnowledgeBase,
  renameDocument,
  updateDocumentMetadata,
  uploadDocuments,
} from "@/api/client";
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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { TitleInfoIcon } from "@/components/ui/title-info-icon";
import { formatBytes, formatDateTime, formatNumber } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useAppStore } from "@/store/app-store";
import type { DocumentSummary } from "@/types/api";


const uploadSchema = z.object({
  files: z.array(z.instanceof(File)).min(1, "请至少选择一个文件。").max(10, "单次最多上传 10 个文件。"),
});

const renameSchema = z.object({
  name: z.string().min(1, "请输入新的文档名。"),
});

const metadataSchema = z.object({
  theme: z.string().optional(),
  tags: z.string().optional(),
});

type UploadFormValues = z.infer<typeof uploadSchema>;
type RenameFormValues = z.infer<typeof renameSchema>;
type MetadataFormValues = z.infer<typeof metadataSchema>;

const ALL_VALUE = "__all__";
const LIBRARY_PANEL_CLASS = "glass-panel xl:flex xl:h-[clamp(560px,calc(100dvh-170px),680px)] xl:flex-col";

export function KnowledgePage() {
  const queryClient = useQueryClient();
  const selectedDocumentId = useAppStore((state) => state.selectedDocumentId);
  const setSelectedDocumentId = useAppStore((state) => state.setSelectedDocumentId);
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState(ALL_VALUE);
  const [statusFilter, setStatusFilter] = useState(ALL_VALUE);
  const [themeFilter, setThemeFilter] = useState(ALL_VALUE);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [indexOpen, setIndexOpen] = useState(false);
  const [renameOpen, setRenameOpen] = useState(false);
  const [metadataOpen, setMetadataOpen] = useState(false);
  const deferredSearch = useDeferredValue(search.trim());

  const documentsQuery = useQuery({
    queryKey: ["documents"],
    queryFn: getDocuments,
  });
  const knowledgeStatusQuery = useQuery({
    queryKey: ["knowledge-status"],
    queryFn: getKnowledgeStatus,
  });
  const previewQuery = useQuery({
    queryKey: ["document-preview", selectedDocumentId],
    queryFn: () => getDocumentPreview(selectedDocumentId!),
    enabled: Boolean(selectedDocumentId),
  });

  const documents = useMemo(
    () =>
      [...(documentsQuery.data ?? [])].sort(
        (left, right) => new Date(right.updated_at).getTime() - new Date(left.updated_at).getTime(),
      ),
    [documentsQuery.data],
  );

  const selectedDocument = useMemo(
    () => documents.find((document) => document.document_id === selectedDocumentId) ?? null,
    [documents, selectedDocumentId],
  );

  const typeOptions = useMemo(
    () => uniqueSorted(documents.map((document) => normalizeExtension(document.extension))),
    [documents],
  );
  const statusOptions = useMemo(
    () => uniqueSorted(documents.map((document) => document.status)),
    [documents],
  );
  const themeOptions = useMemo(
    () => uniqueSorted(documents.map((document) => document.theme).filter(Boolean)),
    [documents],
  );

  const filteredDocuments = useMemo(
    () =>
      documents.filter((document) => {
        if (typeFilter !== ALL_VALUE && normalizeExtension(document.extension) !== typeFilter) {
          return false;
        }
        if (statusFilter !== ALL_VALUE && document.status !== statusFilter) {
          return false;
        }
        if (themeFilter !== ALL_VALUE && document.theme !== themeFilter) {
          return false;
        }
        return !deferredSearch || documentMatchesSearch(document, deferredSearch);
      }),
    [deferredSearch, documents, statusFilter, themeFilter, typeFilter],
  );

  useEffect(() => {
    if (
      documentsQuery.isSuccess &&
      selectedDocumentId &&
      !documents.some((document) => document.document_id === selectedDocumentId)
    ) {
      setSelectedDocumentId(null);
    }
  }, [documents, documentsQuery.isSuccess, selectedDocumentId, setSelectedDocumentId]);

  const uploadForm = useForm<UploadFormValues>({
    resolver: zodResolver(uploadSchema),
    defaultValues: { files: [] },
  });
  const renameForm = useForm<RenameFormValues>({
    resolver: zodResolver(renameSchema),
    defaultValues: { name: selectedDocument?.name ?? "" },
  });
  const metadataForm = useForm<MetadataFormValues>({
    resolver: zodResolver(metadataSchema),
    defaultValues: {
      theme: selectedDocument?.theme ?? "",
      tags: selectedDocument?.tags.join(", ") ?? "",
    },
  });

  useEffect(() => {
    renameForm.reset({ name: selectedDocument?.name ?? "" });
    metadataForm.reset({
      theme: selectedDocument?.theme ?? "",
      tags: selectedDocument?.tags.join(", ") ?? "",
    });
  }, [metadataForm, renameForm, selectedDocument]);

  const invalidateKnowledge = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: ["documents"] }),
      queryClient.invalidateQueries({ queryKey: ["knowledge-status"] }),
      queryClient.invalidateQueries({ queryKey: ["workspace-bootstrap"] }),
      queryClient.invalidateQueries({ queryKey: ["graph"] }),
      selectedDocumentId
        ? queryClient.invalidateQueries({ queryKey: ["document-preview", selectedDocumentId] })
        : Promise.resolve(),
    ]);

  const uploadMutation = useMutation({
    mutationFn: async (values: UploadFormValues) => uploadDocuments(values.files),
    onSuccess: async (_result, values) => {
      uploadForm.reset({ files: [] });
      setUploadOpen(false);
      await invalidateKnowledge();
      const refreshedDocuments = await queryClient.fetchQuery({
        queryKey: ["documents"],
        queryFn: getDocuments,
      });
      const uploadedNames = new Set(values.files.map((file) => file.name));
      const uploadedDocument = refreshedDocuments.find((document) => uploadedNames.has(document.name));
      if (uploadedDocument) {
        setSelectedDocumentId(uploadedDocument.document_id);
        setSearch(uploadedDocument.name);
      }
    },
  });

  const rebuildMutation = useMutation({
    mutationFn: rebuildKnowledgeBase,
    onSuccess: invalidateKnowledge,
  });

  const renameMutation = useMutation({
    mutationFn: (values: RenameFormValues) => renameDocument(selectedDocumentId!, values.name),
    onSuccess: async () => {
      setRenameOpen(false);
      await invalidateKnowledge();
    },
  });

  const metadataMutation = useMutation({
    mutationFn: (values: MetadataFormValues) =>
      updateDocumentMetadata([selectedDocumentId!], {
        theme: values.theme?.trim() || undefined,
        tags: values.tags
          ?.split(",")
          .map((tag) => tag.trim())
          .filter(Boolean),
      }),
    onSuccess: async () => {
      setMetadataOpen(false);
      await invalidateKnowledge();
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => deleteDocuments([selectedDocumentId!]),
    onSuccess: async () => {
      setSelectedDocumentId(null);
      await invalidateKnowledge();
    },
  });

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop: (acceptedFiles) => uploadForm.setValue("files", acceptedFiles, { shouldValidate: true }),
  });

  const currentJob = knowledgeStatusQuery.data?.current_job;
  const filtersActive =
    Boolean(deferredSearch) ||
    typeFilter !== ALL_VALUE ||
    statusFilter !== ALL_VALUE ||
    themeFilter !== ALL_VALUE;
  const clearFilters = () => {
    setSearch("");
    setTypeFilter(ALL_VALUE);
    setStatusFilter(ALL_VALUE);
    setThemeFilter(ALL_VALUE);
  };

  return (
    <section className="space-y-3" data-testid="knowledge-library">
      <Card className="glass-panel overflow-hidden" data-testid="knowledge-snapshot">
        <CardHeader className="items-start gap-2 px-3 pb-2 pt-3 md:px-4">
          <div className="grid w-full gap-2 xl:grid-cols-[minmax(0,1fr)_auto] xl:items-center">
            <div>
              <CardTitle className="flex items-center gap-2 font-display text-[1.55rem] leading-tight">
                知识库
                <TitleInfoIcon label="知识库说明">
                  像图书馆一样搜索、浏览和预览资料；上传与索引收进工具层，避免干扰找资料的主流程。
                </TitleInfoIcon>
              </CardTitle>
            </div>
            <div className="flex flex-wrap gap-2 xl:justify-end">
              <Button type="button" className="h-10" onClick={() => setUploadOpen(true)} data-testid="upload-dialog-button">
                <FilePlus2 className="h-4 w-4" />
                上传资料
              </Button>
              <Button type="button" variant="secondary" className="h-10" onClick={() => setIndexOpen(true)} data-testid="index-tools-button">
                <Settings2 className="h-4 w-4" />
                索引管理
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-2 px-3 pb-3 md:px-4">
          <div className="grid items-center gap-2 rounded-[22px] border border-teal-100 bg-white/72 p-2 shadow-[inset_0_1px_0_rgba(255,255,255,0.86)] lg:grid-cols-[minmax(260px,1fr)_repeat(3,minmax(136px,170px))]">
            <div
              className="flex h-11 items-center gap-3 rounded-[16px] border border-teal-100 bg-white/88 px-4 text-slate-900 transition focus-within:border-teal-500 focus-within:bg-white"
              data-testid="knowledge-search-control"
            >
              <Search className="pointer-events-none h-4 w-4 shrink-0 translate-y-px text-slate-500" />
              <Input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                className="h-full flex-1 rounded-none border-0 bg-transparent px-0 text-[15px] leading-none shadow-none placeholder:text-slate-500 focus:border-0 focus:bg-transparent"
                placeholder="搜索文档名、主题、标签或路径"
                data-testid="knowledge-search-input"
                aria-label="搜索知识库资料"
              />
              {search ? (
                <button
                  type="button"
                  className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"
                  onClick={() => setSearch("")}
                  aria-label="清空搜索"
                >
                  <X className="h-4 w-4" />
                </button>
              ) : null}
            </div>

            <FilterSelect
              label="类型"
              value={typeFilter}
              onValueChange={setTypeFilter}
              options={typeOptions}
              allLabel="全部类型"
              testId="knowledge-type-filter"
            />
            <FilterSelect
              label="状态"
              value={statusFilter}
              onValueChange={setStatusFilter}
              options={statusOptions}
              allLabel="全部状态"
              testId="knowledge-status-filter"
            />
            <FilterSelect
              label="主题"
              value={themeFilter}
              onValueChange={setThemeFilter}
              options={themeOptions}
              allLabel="全部主题"
              testId="knowledge-theme-filter"
            />
          </div>

          <div className="grid gap-2 md:grid-cols-4">
            <MetricTile label="文档数" value={formatNumber(knowledgeStatusQuery.data?.document_count ?? documents.length)} />
            <MetricTile label="切片数" value={formatNumber(knowledgeStatusQuery.data?.chunk_count ?? 0)} />
            <MetricTile label="已索引" value={formatNumber(knowledgeStatusQuery.data?.indexed_count ?? 0)} />
            <MetricTile label="待处理" value={formatNumber(knowledgeStatusQuery.data?.pending_count ?? 0)} />
          </div>

          {(documentsQuery.isError || knowledgeStatusQuery.isError) ? (
            <InlineNotice tone="danger">
              知识库数据暂时不可用，请检查后端服务和当前账号权限后重试。
            </InlineNotice>
          ) : null}
        </CardContent>
      </Card>

      <div className="grid items-start gap-4 xl:grid-cols-[260px_minmax(0,1fr)_380px] xl:items-stretch">
        <Card className={LIBRARY_PANEL_CLASS} data-testid="knowledge-filter-panel">
          <CardHeader className="items-start xl:shrink-0">
            <CardTitle className="flex items-center gap-2">
              <Library className="h-4 w-4 text-teal-700" />
              资料集合
              <TitleInfoIcon label="资料集合说明">按状态、类型和主题缩小范围，列表会实时更新。</TitleInfoIcon>
            </CardTitle>
          </CardHeader>
          <CardContent className="snow-scrollbar space-y-3 xl:min-h-0 xl:flex-1 xl:overflow-y-auto xl:pr-2">
            <LibraryFacet label="当前结果" value={formatNumber(filteredDocuments.length)} hint={`共 ${formatNumber(documents.length)} 份资料`} />
            <LibraryFacet label="文件类型" value={formatNumber(typeOptions.length)} hint={typeOptions.slice(0, 3).join(" / ") || "暂无类型"} />
            <LibraryFacet label="主题数量" value={formatNumber(themeOptions.length)} hint={themeOptions.slice(0, 2).join(" / ") || "未分类"} />
            <Separator />
            <div className="surface-tile rounded-[22px] p-4">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="text-sm font-semibold text-slate-900">索引状态</p>
                  <p className="mt-1 text-xs leading-5 text-slate-600">{currentJob?.message || "暂无后台任务"}</p>
                </div>
                <Badge variant="soft">{currentJob?.status || "idle"}</Badge>
              </div>
            </div>
            {filtersActive ? (
              <Button type="button" variant="secondary" className="w-full" onClick={clearFilters} data-testid="clear-knowledge-filters">
                清除筛选
              </Button>
            ) : null}
          </CardContent>
        </Card>

        <Card className={LIBRARY_PANEL_CLASS} data-testid="knowledge-library-list">
          <CardHeader className="items-start xl:shrink-0">
            <div className="flex w-full flex-wrap items-center justify-between gap-3">
              <div>
                <CardTitle className="flex items-center gap-2">
                  资料书架
                  <TitleInfoIcon label="资料书架说明">
                    {filtersActive
                      ? `找到 ${formatNumber(filteredDocuments.length)} 份匹配资料。`
                      : "浏览所有已收纳资料，选择一份即可在右侧预览。"}
                  </TitleInfoIcon>
                </CardTitle>
                <span className="sr-only">
                  {filtersActive
                    ? `找到 ${formatNumber(filteredDocuments.length)} 份匹配资料。`
                    : "浏览所有已收纳资料，选择一份即可在右侧预览。"}
                </span>
              </div>
              <Badge variant="soft">{formatNumber(filteredDocuments.length)} 项</Badge>
            </div>
          </CardHeader>
          <CardContent className="xl:min-h-0 xl:flex-1">
            <DocumentList
              documents={filteredDocuments}
              selectedDocumentId={selectedDocumentId}
              search={deferredSearch}
              isLoading={documentsQuery.isLoading}
              isEmptyLibrary={documents.length === 0}
              filtersActive={filtersActive}
              onSelect={setSelectedDocumentId}
              onClearFilters={clearFilters}
              onOpenUpload={() => setUploadOpen(true)}
            />
          </CardContent>
        </Card>

        <PreviewPanel
          selectedDocument={selectedDocument}
          preview={previewQuery.data?.preview}
          previewLoading={previewQuery.isLoading}
          previewError={previewQuery.isError}
          renameOpen={renameOpen}
          metadataOpen={metadataOpen}
          setRenameOpen={setRenameOpen}
          setMetadataOpen={setMetadataOpen}
          renameForm={renameForm}
          metadataForm={metadataForm}
          renamePending={renameMutation.isPending}
          metadataPending={metadataMutation.isPending}
          deletePending={deleteMutation.isPending}
          previewMetadata={previewQuery.data?.metadata}
          renameError={mutationError(renameMutation.error)}
          metadataError={mutationError(metadataMutation.error)}
          deleteError={mutationError(deleteMutation.error)}
          onRename={(values) => renameMutation.mutate(values)}
          onMetadata={(values) => metadataMutation.mutate(values)}
          onDelete={() => deleteMutation.mutate()}
        />
      </div>

      <UploadDialog
        open={uploadOpen}
        onOpenChange={setUploadOpen}
        form={uploadForm}
        isDragActive={isDragActive}
        getRootProps={getRootProps}
        getInputProps={getInputProps}
        isPending={uploadMutation.isPending}
        error={mutationError(uploadMutation.error)}
        onSubmit={(values) => uploadMutation.mutate(values)}
      />

      <IndexDialog
        open={indexOpen}
        onOpenChange={setIndexOpen}
        currentJob={currentJob}
        isPending={rebuildMutation.isPending}
        error={mutationError(rebuildMutation.error)}
        onRebuild={(mode) => rebuildMutation.mutate(mode)}
      />
    </section>
  );
}

function DocumentList({
  documents,
  selectedDocumentId,
  search,
  isLoading,
  isEmptyLibrary,
  filtersActive,
  onSelect,
  onClearFilters,
  onOpenUpload,
}: {
  documents: DocumentSummary[];
  selectedDocumentId: string | null;
  search: string;
  isLoading: boolean;
  isEmptyLibrary: boolean;
  filtersActive: boolean;
  onSelect: (documentId: string | null) => void;
  onClearFilters: () => void;
  onOpenUpload: () => void;
}) {
  if (isLoading) {
    return (
      <div className="space-y-3 rounded-[24px] border border-white/70 bg-white/68 p-4" data-testid="documents-table">
        {Array.from({ length: 5 }, (_, index) => (
          <div key={index} className="h-[74px] animate-pulse rounded-[20px] bg-teal-50/70" />
        ))}
      </div>
    );
  }

  if (isEmptyLibrary) {
    return (
      <LibraryEmptyState
        title="资料库还是空的"
        description="你可以上传文档建立资料库，也可以先从知识图谱探索主题，再把有价值的知识沉淀到知识库。"
        primaryAction="上传资料"
        onPrimaryAction={onOpenUpload}
      />
    );
  }

  if (documents.length === 0) {
    return (
      <LibraryEmptyState
        title="没有找到匹配资料"
        description="试试更短的关键词，或清除筛选条件。如果资料还未收录，可以上传文档或去图谱探索。"
        primaryAction={filtersActive ? "清除筛选" : "上传资料"}
        onPrimaryAction={filtersActive ? onClearFilters : onOpenUpload}
      />
    );
  }

  return (
    <div className="overflow-hidden rounded-[24px] border border-white/70 bg-white/66" data-testid="documents-table">
      <div className="hidden grid-cols-[minmax(220px,1.65fr)_76px_minmax(120px,0.9fr)_94px_70px_128px] items-center border-b border-white/70 bg-white/82 px-4 py-3 text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 lg:grid">
        <span>文档</span>
        <span>类型</span>
        <span>主题</span>
        <span>状态</span>
        <span>切片</span>
        <span>更新时间</span>
      </div>
      <div className="hidden lg:block">
        <Virtuoso
          className="snow-scrollbar"
          style={{ height: "clamp(360px, calc(100dvh - 395px), 560px)" }}
          data={documents}
          computeItemKey={(_, document) => document.document_id}
          increaseViewportBy={360}
          itemContent={(_, document) => (
            <DocumentRow
              document={document}
              selected={selectedDocumentId === document.document_id}
              search={search}
              onSelect={onSelect}
            />
          )}
        />
      </div>
      <div className="p-3 lg:hidden">
        <Virtuoso
          className="snow-scrollbar"
          style={{ height: "520px" }}
          data={documents}
          computeItemKey={(_, document) => document.document_id}
          increaseViewportBy={240}
          itemContent={(_, document) => (
            <div className="pb-3">
              <DocumentCard
                document={document}
                selected={selectedDocumentId === document.document_id}
                search={search}
                onSelect={onSelect}
              />
            </div>
          )}
        />
      </div>
    </div>
  );
}

function DocumentRow({
  document,
  selected,
  search,
  onSelect,
}: {
  document: DocumentSummary;
  selected: boolean;
  search: string;
  onSelect: (documentId: string | null) => void;
}) {
  return (
    <button
      type="button"
      data-testid={`document-select-${document.document_id}`}
      onClick={() => onSelect(document.document_id)}
      className={cn(
        "grid min-h-[76px] w-full grid-cols-[minmax(220px,1.65fr)_76px_minmax(120px,0.9fr)_94px_70px_128px] items-stretch border-b border-white/60 px-4 py-3 text-left transition",
        selected
          ? "bg-teal-50/86 shadow-[inset_3px_0_0_rgba(15,118,110,0.8)]"
          : "bg-white/48 hover:bg-teal-50/58",
      )}
    >
      <div className="min-w-0 self-stretch py-1 pr-4">
        <p className="truncate font-semibold text-slate-900" title={document.name}>
          <HighlightText text={document.name} query={search} />
        </p>
        <p className="mt-1 truncate text-xs text-slate-600" title={document.relative_path}>
          <HighlightText text={document.relative_path} query={search} />
        </p>
      </div>
      <div className="flex items-center">
        <Badge variant="outline">{normalizeExtension(document.extension) || "--"}</Badge>
      </div>
      <p className="min-w-0 self-center pr-3 text-sm text-slate-700" title={document.theme || "未分类"}>
        <span className="block truncate">
          <HighlightText text={document.theme || "未分类"} query={search} />
        </span>
      </p>
      <div className="flex items-center">
        <Badge variant="soft">{document.status}</Badge>
      </div>
      <p className="flex items-center font-mono text-sm text-slate-800">{formatNumber(document.chunk_count)}</p>
      <p className="flex items-center text-sm text-slate-600">{formatDateTime(document.updated_at)}</p>
    </button>
  );
}

function DocumentCard({
  document,
  selected,
  search,
  onSelect,
}: {
  document: DocumentSummary;
  selected: boolean;
  search: string;
  onSelect: (documentId: string | null) => void;
}) {
  return (
    <button
      type="button"
      data-testid={`document-select-${document.document_id}`}
      onClick={() => onSelect(document.document_id)}
      className={cn(
        "w-full rounded-[22px] border p-4 text-left transition",
        selected
          ? "border-teal-300 bg-teal-50/88 shadow-[0_12px_28px_rgba(15,118,110,0.1)]"
          : "border-white/70 bg-white/72 hover:border-teal-200 hover:bg-teal-50/50",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="line-clamp-2 font-semibold text-slate-900">
            <HighlightText text={document.name} query={search} />
          </p>
          <p className="mt-1 truncate text-xs text-slate-600">
            <HighlightText text={document.relative_path} query={search} />
          </p>
        </div>
        <Badge variant="soft">{normalizeExtension(document.extension) || "--"}</Badge>
      </div>
      <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-600">
        <Badge variant="outline">{document.status}</Badge>
        <Badge variant="outline">{document.theme || "未分类"}</Badge>
        <Badge variant="outline">{formatNumber(document.chunk_count)} 切片</Badge>
      </div>
    </button>
  );
}

function PreviewPanel({
  selectedDocument,
  preview,
  previewLoading,
  previewError,
  previewMetadata,
  renameOpen,
  metadataOpen,
  setRenameOpen,
  setMetadataOpen,
  renameForm,
  metadataForm,
  renamePending,
  metadataPending,
  deletePending,
  renameError,
  metadataError,
  deleteError,
  onRename,
  onMetadata,
  onDelete,
}: {
  selectedDocument: DocumentSummary | null;
  preview?: string;
  previewLoading: boolean;
  previewError: boolean;
  previewMetadata?: {
    file_type: string;
    parser_name: string;
    source_url?: string;
    resolved_url?: string;
  };
  renameOpen: boolean;
  metadataOpen: boolean;
  setRenameOpen: (open: boolean) => void;
  setMetadataOpen: (open: boolean) => void;
  renameForm: ReturnType<typeof useForm<RenameFormValues>>;
  metadataForm: ReturnType<typeof useForm<MetadataFormValues>>;
  renamePending: boolean;
  metadataPending: boolean;
  deletePending: boolean;
  renameError: string | null;
  metadataError: string | null;
  deleteError: string | null;
  onRename: (values: RenameFormValues) => void;
  onMetadata: (values: MetadataFormValues) => void;
  onDelete: () => void;
}) {
  return (
    <Card
      className={cn(LIBRARY_PANEL_CLASS, "xl:overflow-hidden")}
      data-testid="knowledge-preview-panel"
    >
      <CardHeader className="items-start xl:shrink-0">
        <CardTitle className="flex items-center gap-2">
          <BookOpen className="h-4 w-4 text-teal-700" />
          资料预览
          <TitleInfoIcon label="资料预览说明">选择左侧资料后，这里会显示正文预览、元数据和管理操作。</TitleInfoIcon>
        </CardTitle>
      </CardHeader>
      <CardContent className="snow-scrollbar space-y-4 xl:min-h-0 xl:flex-1 xl:overflow-y-auto xl:pr-2">
        {!selectedDocument ? (
          <div className="surface-tile rounded-[26px] px-5 py-8 text-center">
            <FolderSearch className="mx-auto h-8 w-8 text-teal-700" />
            <h3 className="mt-4 text-lg font-semibold text-slate-900">选择一份资料开始预览</h3>
            <p className="mt-2 text-sm leading-6 text-slate-600">你可以从文档列表选择资料，或使用上方搜索快速定位。</p>
          </div>
        ) : (
          <>
            <div className="surface-tile rounded-[26px] p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h3 className="line-clamp-2 text-lg font-semibold text-slate-900" data-testid="selected-document-name">
                    {selectedDocument.name}
                  </h3>
                  <p className="mt-1 truncate text-sm text-slate-600">{selectedDocument.relative_path}</p>
                </div>
                <Badge variant="outline">{normalizeExtension(selectedDocument.extension) || "--"}</Badge>
              </div>
              <div className="mt-4 grid grid-cols-2 gap-2 text-sm text-slate-700">
                <MiniMeta label="状态" value={selectedDocument.status} />
                <MiniMeta label="切片" value={`${formatNumber(selectedDocument.chunk_count)} 片`} />
                <MiniMeta label="大小" value={formatBytes(selectedDocument.size_bytes)} />
                <MiniMeta label="更新" value={formatDateTime(selectedDocument.updated_at)} />
              </div>
            </div>

            <div className="rounded-[24px] bg-slate-950 p-4">
              <div className="mb-3 flex items-center justify-between gap-3">
                <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-300">正文预览</p>
                <Dialog>
                  <DialogTrigger asChild>
                    <Button variant="outline" size="sm" disabled={!preview} data-testid="preview-launcher-button">
                      查看全文
                    </Button>
                  </DialogTrigger>
                  <DialogContent
                    className="flex h-[86dvh] max-h-[820px] max-w-5xl flex-col overflow-hidden p-0"
                    data-testid="preview-overlay"
                  >
                    <DialogHeader className="mb-0 shrink-0 border-b border-teal-100/80 px-6 pb-4 pr-14 pt-6">
                      <DialogTitle data-testid="document-preview-name">{selectedDocument.name}</DialogTitle>
                      <DialogDescription>{selectedDocument.relative_path}</DialogDescription>
                    </DialogHeader>
                    <div className="snow-scrollbar min-h-0 flex-1 overflow-auto px-6 py-4" data-testid="preview-scroll-area">
                      <pre
                        className="min-h-full whitespace-pre-wrap rounded-[22px] bg-slate-950 p-5 font-mono text-xs leading-7 text-slate-100"
                        data-testid="preview-content"
                      >
                        {preview ?? "暂无预览内容"}
                      </pre>
                    </div>
                  </DialogContent>
                </Dialog>
              </div>
              <pre
                className="snow-scrollbar max-h-[260px] overflow-auto whitespace-pre-wrap font-mono text-xs leading-7 text-slate-100"
                data-testid="preview-inline-content"
              >
                {previewLoading
                  ? "正在载入预览..."
                  : previewError
                    ? "预览加载失败，请稍后重试。"
                    : preview || "暂无预览内容。"}
              </pre>
            </div>

            <div className="grid gap-2 text-sm">
              <MetaRow label="解析器" value={previewMetadata?.parser_name} />
              <MetaRow label="文件类型" value={previewMetadata?.file_type || selectedDocument.extension} />
              <MetaRow label="来源 URL" value={previewMetadata?.source_url} />
              <MetaRow label="解析后 URL" value={previewMetadata?.resolved_url} />
            </div>

            <div className="flex flex-wrap gap-2">
              {(selectedDocument.tags.length ? selectedDocument.tags : ["暂无标签"]).map((tag) => (
                <Badge key={tag} variant="outline">
                  {tag}
                </Badge>
              ))}
            </div>

            <div className="grid grid-cols-2 gap-2">
              <a
                href="/chat"
                className="inline-flex h-9 items-center justify-center gap-2 rounded-full bg-white/70 px-3 text-sm font-medium text-slate-800 ring-1 ring-teal-200 transition hover:bg-white"
              >
                问这个文档
                <ArrowUpRight className="h-4 w-4" />
              </a>
              <a
                href="/graph"
                className="inline-flex h-9 items-center justify-center gap-2 rounded-full bg-white/70 px-3 text-sm font-medium text-slate-800 ring-1 ring-teal-200 transition hover:bg-white"
              >
                查看图谱
                <Network className="h-4 w-4" />
              </a>
            </div>

            <div className="flex flex-wrap gap-2">
              <Dialog open={renameOpen} onOpenChange={setRenameOpen}>
                <DialogTrigger asChild>
                  <Button variant="outline" size="sm">
                    <PencilLine className="h-4 w-4" />
                    重命名
                  </Button>
                </DialogTrigger>
                <DialogContent>
                  <DialogHeader>
                    <DialogTitle>重命名文档</DialogTitle>
                    <DialogDescription>修改名称后会自动标记为需要重新索引。</DialogDescription>
                  </DialogHeader>
                  <form className="space-y-4" onSubmit={renameForm.handleSubmit(onRename)}>
                    <div className="space-y-2">
                      <Label htmlFor="rename-name">新名称</Label>
                      <Input id="rename-name" {...renameForm.register("name")} />
                      {renameForm.formState.errors.name?.message ? (
                        <p className="text-xs text-rose-600">{renameForm.formState.errors.name.message}</p>
                      ) : null}
                    </div>
                    {renameError ? <InlineNotice tone="danger">{renameError}</InlineNotice> : null}
                    <Button type="submit" className="w-full" disabled={renamePending}>
                      {renamePending ? "保存中..." : "保存名称"}
                    </Button>
                  </form>
                </DialogContent>
              </Dialog>

              <Dialog open={metadataOpen} onOpenChange={setMetadataOpen}>
                <DialogTrigger asChild>
                  <Button variant="outline" size="sm">
                    <Tags className="h-4 w-4" />
                    主题与标签
                  </Button>
                </DialogTrigger>
                <DialogContent>
                  <DialogHeader>
                    <DialogTitle>编辑主题与标签</DialogTitle>
                    <DialogDescription>标签用逗号分隔，保存后会触发增量更新。</DialogDescription>
                  </DialogHeader>
                  <form className="space-y-4" onSubmit={metadataForm.handleSubmit(onMetadata)}>
                    <div className="space-y-2">
                      <Label htmlFor="metadata-theme">主题</Label>
                      <Input id="metadata-theme" {...metadataForm.register("theme")} />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="metadata-tags">标签</Label>
                      <Input id="metadata-tags" {...metadataForm.register("tags")} placeholder="adb, android, activity" />
                    </div>
                    {metadataError ? <InlineNotice tone="danger">{metadataError}</InlineNotice> : null}
                    <Button type="submit" className="w-full" disabled={metadataPending}>
                      {metadataPending ? "保存中..." : "保存元数据"}
                    </Button>
                  </form>
                </DialogContent>
              </Dialog>

              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button variant="destructive" size="sm" disabled={deletePending} data-testid="delete-current-document-button">
                    <Trash2 className="h-4 w-4" />
                    删除文档
                  </Button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>删除当前文档？</AlertDialogTitle>
                    <AlertDialogDescription>会同时删除源文件和索引记录，这个操作不可撤销。</AlertDialogDescription>
                  </AlertDialogHeader>
                  {deleteError ? <InlineNotice tone="danger">{deleteError}</InlineNotice> : null}
                  <AlertDialogFooter>
                    <AlertDialogCancelControl>取消</AlertDialogCancelControl>
                    <AlertDialogActionControl onClick={onDelete}>
                      {deletePending ? "删除中..." : "确认删除"}
                    </AlertDialogActionControl>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

function UploadDialog({
  open,
  onOpenChange,
  form,
  isDragActive,
  getRootProps,
  getInputProps,
  isPending,
  error,
  onSubmit,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  form: ReturnType<typeof useForm<UploadFormValues>>;
  isDragActive: boolean;
  getRootProps: ReturnType<typeof useDropzone>["getRootProps"];
  getInputProps: ReturnType<typeof useDropzone>["getInputProps"];
  isPending: boolean;
  error: string | null;
  onSubmit: (values: UploadFormValues) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>上传资料</DialogTitle>
          <DialogDescription>把文档收纳进知识库，上传完成后会自动选中新资料并刷新索引状态。</DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={form.handleSubmit(onSubmit)}>
          <div
            {...getRootProps()}
            className={cn(
              "rounded-[26px] border border-dashed px-5 py-8 text-center transition",
              isDragActive ? "border-teal-500 bg-teal-50/90" : "border-teal-200 bg-white/72 hover:border-teal-300",
            )}
          >
            <input {...getInputProps()} data-testid="knowledge-file-input" />
            <UploadCloud className="mx-auto h-8 w-8 text-teal-700" />
            <p className="mt-3 text-sm font-semibold text-slate-800">拖拽文档到这里，或点击选择文件</p>
            <p className="mt-1 text-xs leading-5 text-slate-600">支持 pdf / docx / xlsx / md / csv / json / url 等格式</p>
          </div>

          <Controller
            control={form.control}
            name="files"
            render={({ field, fieldState }) => (
              <div className="space-y-2">
                {field.value.length > 0 ? (
                  <div className="surface-tile rounded-[18px] px-3 py-3 text-xs leading-6 text-slate-700">
                    {field.value.map((file) => file.name).join("、")}
                  </div>
                ) : null}
                {fieldState.error ? <p className="text-xs text-rose-600">{fieldState.error.message}</p> : null}
              </div>
            )}
          />

          {error ? <InlineNotice tone="danger">{error}</InlineNotice> : null}
          <Button type="submit" className="w-full" data-testid="upload-documents-button" disabled={isPending}>
            <FilePlus2 className="h-4 w-4" />
            {isPending ? "上传中..." : "上传到知识库"}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function IndexDialog({
  open,
  onOpenChange,
  currentJob,
  isPending,
  error,
  onRebuild,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  currentJob?: { status: string; message: string; progress: number } | null;
  isPending: boolean;
  error: string | null;
  onRebuild: (mode: "sync" | "scan" | "reset") => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>索引管理</DialogTitle>
          <DialogDescription>同步、扫描和重建索引都在这里执行，避免干扰资料搜索。</DialogDescription>
        </DialogHeader>
        <div className="surface-tile rounded-[24px] p-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="font-semibold text-slate-900">当前后台任务</p>
              <p className="mt-1 text-sm leading-6 text-slate-600">{currentJob?.message || "暂无后台任务"}</p>
            </div>
            <Badge variant="soft">{currentJob?.status || "idle"}</Badge>
          </div>
          <div className="mt-3 h-2 overflow-hidden rounded-full bg-teal-100">
            <div
              className="h-full rounded-full bg-teal-700 transition-all"
              style={{ width: `${Math.max(0, Math.min(100, currentJob?.progress ?? 0))}%` }}
            />
          </div>
        </div>
        {error ? <InlineNotice tone="danger">{error}</InlineNotice> : null}
        <div className="grid gap-2">
          <Button
            type="button"
            variant="secondary"
            data-testid="sync-knowledge-button"
            onClick={() => onRebuild("sync")}
            disabled={isPending}
          >
            <RefreshCw className="h-4 w-4" />
            同步索引
          </Button>
          <Button
            type="button"
            variant="secondary"
            data-testid="scan-knowledge-button"
            onClick={() => onRebuild("scan")}
            disabled={isPending}
          >
            扫描增量
          </Button>
          <Button
            type="button"
            variant="destructive"
            data-testid="reset-knowledge-button"
            onClick={() => onRebuild("reset")}
            disabled={isPending}
          >
            重置重建
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function FilterSelect({
  label,
  value,
  onValueChange,
  options,
  allLabel,
  testId,
}: {
  label: string;
  value: string;
  onValueChange: (value: string) => void;
  options: string[];
  allLabel: string;
  testId: string;
}) {
  return (
    <div className="min-w-0">
      <Label className="sr-only">{label}</Label>
      <Select value={value} onValueChange={onValueChange}>
        <SelectTrigger
          className="h-14 rounded-[20px] border-teal-100 bg-white/88 px-5 text-[15px] leading-none shadow-[inset_0_1px_0_rgba(255,255,255,0.9)]"
          aria-label={label}
          data-testid={testId}
        >
          <SelectValue placeholder={allLabel} />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL_VALUE}>{allLabel}</SelectItem>
          {options.map((option) => (
            <SelectItem key={option} value={option}>
              {option}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

function LibraryEmptyState({
  title,
  description,
  primaryAction,
  onPrimaryAction,
}: {
  title: string;
  description: string;
  primaryAction: string;
  onPrimaryAction: () => void;
}) {
  return (
    <div className="rounded-[28px] border border-dashed border-teal-200 bg-gradient-to-br from-white/92 to-teal-50/74 px-6 py-10 text-center" data-testid="knowledge-empty-state">
      <FolderSearch className="mx-auto h-10 w-10 text-teal-700" />
      <h3 className="mt-4 text-xl font-semibold text-slate-900">{title}</h3>
      <p className="mx-auto mt-2 max-w-xl text-sm leading-7 text-slate-600">{description}</p>
      <div className="mt-5 flex flex-wrap justify-center gap-3">
        <Button type="button" onClick={onPrimaryAction}>
          {primaryAction}
        </Button>
        <a
          href="/graph"
          className="inline-flex h-10 items-center justify-center gap-2 rounded-full bg-white/70 px-4 text-sm font-medium text-slate-800 ring-1 ring-teal-200 transition hover:bg-white"
        >
          打开知识图谱探索
          <Network className="h-4 w-4" />
        </a>
      </div>
    </div>
  );
}

function LibraryFacet({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="surface-tile rounded-[22px] p-4">
      <p className="text-xs uppercase tracking-[0.18em] text-slate-500">{label}</p>
      <p className="mt-2 text-2xl font-semibold text-slate-900">{value}</p>
      <p className="mt-1 truncate text-xs text-slate-600">{hint}</p>
    </div>
  );
}

function MetricTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="surface-tile flex min-h-10 items-center justify-between gap-3 rounded-[16px] px-3 py-2">
      <p className="text-xs font-medium text-slate-500">{label}</p>
      <p className="font-mono text-base font-semibold text-slate-900">{value}</p>
    </div>
  );
}

function MiniMeta({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[18px] bg-white/78 p-3 ring-1 ring-teal-100">
      <p className="text-xs text-slate-500">{label}</p>
      <p className="mt-1 truncate font-medium text-slate-900">{value}</p>
    </div>
  );
}

function MetaRow({ label, value }: { label: string; value?: string }) {
  return (
    <div className="surface-tile rounded-[20px] p-3">
      <p className="text-xs uppercase tracking-[0.16em] text-slate-500">{label}</p>
      <p className="mt-1 break-words text-sm text-slate-800">{value || "--"}</p>
    </div>
  );
}

function InlineNotice({ tone = "default", children }: { tone?: "default" | "danger"; children: string }) {
  return (
    <div
      className={cn(
        "rounded-[18px] px-3 py-2 text-sm leading-6",
        tone === "danger"
          ? "bg-rose-50 text-rose-700 ring-1 ring-rose-100"
          : "bg-teal-50 text-teal-800 ring-1 ring-teal-100",
      )}
    >
      {children}
    </div>
  );
}

function HighlightText({ text, query }: { text: string; query: string }) {
  if (!query.trim()) {
    return <>{text}</>;
  }

  const lowerText = text.toLocaleLowerCase();
  const lowerQuery = query.toLocaleLowerCase();
  const parts: Array<{ text: string; highlighted: boolean }> = [];
  let cursor = 0;
  while (cursor < text.length) {
    const index = lowerText.indexOf(lowerQuery, cursor);
    if (index === -1) {
      parts.push({ text: text.slice(cursor), highlighted: false });
      break;
    }
    if (index > cursor) {
      parts.push({ text: text.slice(cursor, index), highlighted: false });
    }
    parts.push({ text: text.slice(index, index + query.length), highlighted: true });
    cursor = index + query.length;
  }

  return (
    <>
      {parts.map((part, index) =>
        part.highlighted ? (
          <mark key={`${part.text}-${index}`} className="rounded bg-amber-100 px-0.5 text-slate-950">
            {part.text}
          </mark>
        ) : (
          <span key={`${part.text}-${index}`}>{part.text}</span>
        ),
      )}
    </>
  );
}

function documentMatchesSearch(document: DocumentSummary, query: string) {
  const normalizedQuery = query.toLocaleLowerCase();
  return [
    document.name,
    document.relative_path,
    document.extension,
    document.status,
    document.theme,
    ...document.tags,
  ]
    .filter(Boolean)
    .some((value) => value.toLocaleLowerCase().includes(normalizedQuery));
}

function uniqueSorted(values: string[]) {
  return [...new Set(values.filter(Boolean))].sort((left, right) => left.localeCompare(right));
}

function normalizeExtension(extension: string) {
  return extension.replace(/^\./, "").toLowerCase();
}

function mutationError(error: unknown) {
  if (!error) {
    return null;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "操作失败，请稍后重试。";
}
