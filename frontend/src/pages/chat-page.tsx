import { startTransition, useDeferredValue, useEffect, useMemo, useRef, useState } from "react";

import { AnimatePresence, motion } from "framer-motion";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronLeft,
  ChevronRight,
  DatabaseZap,
  FileSearch,
  LoaderCircle,
  PencilLine,
  Plus,
  Search,
  ShieldCheck,
  Sparkles,
  Square,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { ApiError, getChatSessionMessages, listChatSessions, renameChatSession, streamChat } from "@/api/client";
import { TypewriterText } from "@/components/chat/typewriter-text";
import { EmptyState } from "@/components/feedback/empty-state";
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
import { Slider } from "@/components/ui/slider";
import { Textarea } from "@/components/ui/textarea";
import { TitleInfoIcon } from "@/components/ui/title-info-icon";
import { formatConfidence, formatDuration, formatRelativeTime } from "@/lib/format";
import { cn, createId, isUnreadablePlaceholderText, shortText } from "@/lib/utils";
import { useAppStore } from "@/store/app-store";
import type {
  ChatDoneEvent,
  ChatMessagePayload,
  ChatMessagesResponse,
  CitationPayload,
} from "@/types/api";


const SUGGESTED_PROMPTS = [
  "ADB 怎么查看当前前台 Activity？",
  "根据知识库总结一下测试环境接入流程。",
  "帮我对比 README 和现有接口里关于图谱模块的差异。",
];

const EMPTY_THREAD: ChatMessagesResponse = {
  session: {
    id: "",
    tenant_id: "",
    user_id: "",
    project_id: "",
    title: "新会话",
    status: "draft",
    created_at: new Date().toISOString(),
    last_active_at: new Date().toISOString(),
  },
  messages: [],
  count: 0,
};

const UNREADABLE_MESSAGE = "这条历史消息疑似因旧编码写入而无法还原，请重新发送问题。";
const UNREADABLE_TITLE = "历史会话（编码异常）";

function readableText(value: string, fallback = UNREADABLE_MESSAGE) {
  return isUnreadablePlaceholderText(value) ? fallback : value;
}

function sessionTitle(value: string) {
  return readableText(value, UNREADABLE_TITLE);
}

function sessionPreview(value?: string | null) {
  const text = readableText(value || "还没有消息，点击继续提问。");
  return shortText(text.replace(/\s+/g, " "), 64);
}

export function ChatPage() {
  const queryClient = useQueryClient();
  const activeChatSessionId = useAppStore((state) => state.activeChatSessionId);
  const setActiveChatSessionId = useAppStore((state) => state.setActiveChatSessionId);
  const draftChatSession = useAppStore((state) => state.draftChatSession);
  const ensureDraftChatSession = useAppStore((state) => state.ensureDraftChatSession);
  const clearDraftChatSession = useAppStore((state) => state.clearDraftChatSession);
  const renameDraftChatSession = useAppStore((state) => state.renameDraftChatSession);
  const chatSidebarCollapsed = useAppStore((state) => state.chatSidebarCollapsed);
  const toggleChatSidebar = useAppStore((state) => state.toggleChatSidebar);
  const chatTopK = useAppStore((state) => state.chatTopK);
  const setChatTopK = useAppStore((state) => state.setChatTopK);
  const streamAbortController = useAppStore((state) => state.streamAbortController);
  const setStreamAbortController = useAppStore((state) => state.setStreamAbortController);

  const [search, setSearch] = useState("");
  const [question, setQuestion] = useState("");
  const [renameOpen, setRenameOpen] = useState(false);
  const [renameValue, setRenameValue] = useState("");
  const deferredSearch = useDeferredValue(search);
  const messageEndRef = useRef<HTMLDivElement | null>(null);

  const sessionsQuery = useQuery({
    queryKey: ["chat-sessions"],
    queryFn: () => listChatSessions({ limit: 50 }),
  });

  useEffect(() => {
    if (!activeChatSessionId) {
      ensureDraftChatSession();
    }
  }, [activeChatSessionId, ensureDraftChatSession]);

  useEffect(() => {
    if (
      draftChatSession &&
      sessionsQuery.data?.items.some((item) => item.session.id === draftChatSession.id)
    ) {
      clearDraftChatSession();
    }
  }, [clearDraftChatSession, draftChatSession, sessionsQuery.data?.items]);

  const sessionItems = useMemo(() => {
    const items = [...(sessionsQuery.data?.items ?? [])];
    if (
      draftChatSession &&
      !items.some((item) => item.session.id === draftChatSession.id)
    ) {
      items.unshift({
        session: {
          id: draftChatSession.id,
          tenant_id: "",
          user_id: "",
          project_id: "",
          title: draftChatSession.title,
          status: "draft",
          created_at: draftChatSession.createdAt,
          last_active_at: draftChatSession.createdAt,
        },
        message_count: 0,
        last_message: null,
      });
    }
    return items;
  }, [draftChatSession, sessionsQuery.data?.items]);

  const activeEntry = sessionItems.find((item) => item.session.id === activeChatSessionId) ?? null;
  const searchText = deferredSearch.trim().toLowerCase();
  const filteredSessions = useMemo(
    () =>
      searchText
        ? sessionItems.filter((item) => sessionTitle(item.session.title).toLowerCase().includes(searchText))
        : sessionItems,
    [searchText, sessionItems],
  );

  const hasCachedThread = Boolean(
    activeChatSessionId &&
      queryClient.getQueryData<ChatMessagesResponse>(["chat-messages", activeChatSessionId]),
  );
  const isPersistedSession = Boolean(
    activeChatSessionId &&
      sessionsQuery.data?.items.some((item) => item.session.id === activeChatSessionId),
  );

  const messagesQuery = useQuery({
    queryKey: ["chat-messages", activeChatSessionId],
    queryFn: () => getChatSessionMessages(activeChatSessionId!),
    enabled: Boolean(activeChatSessionId && (isPersistedSession || hasCachedThread)),
  });

  const thread = messagesQuery.data
    ?? (activeEntry
      ? ({
          ...EMPTY_THREAD,
          session: activeEntry.session,
        })
      : EMPTY_THREAD);

  const latestAssistant = useMemo(
    () => [...thread.messages].reverse().find((message) => message.role === "assistant") ?? null,
    [thread.messages],
  );

  useEffect(() => {
    let ticks = 0;
    const scrollToLatest = () => {
      messageEndRef.current?.scrollIntoView({ block: "end" });
    };
    const frame = requestAnimationFrame(scrollToLatest);
    const interval = window.setInterval(() => {
      scrollToLatest();
      ticks += 1;
      if (ticks >= 28) {
        window.clearInterval(interval);
      }
    }, 80);

    return () => {
      cancelAnimationFrame(frame);
      window.clearInterval(interval);
    };
  }, [latestAssistant?.content, thread.messages.length]);

  const renameMutation = useMutation({
    mutationFn: ({ sessionId, title }: { sessionId: string; title: string }) => renameChatSession(sessionId, title),
    onSuccess: async () => {
      setRenameOpen(false);
      await queryClient.invalidateQueries({ queryKey: ["chat-sessions"] });
    },
  });

  const chatMutation = useMutation({
    mutationFn: async ({ prompt, sessionId, sessionTitle }: { prompt: string; sessionId: string; sessionTitle: string }) => {
      const key = ["chat-messages", sessionId];
      const existingThread = queryClient.getQueryData<ChatMessagesResponse>(key) ?? {
        ...EMPTY_THREAD,
        session: {
          ...(activeEntry?.session ?? EMPTY_THREAD.session),
          id: sessionId,
          title: sessionTitle,
          last_active_at: new Date().toISOString(),
          created_at: activeEntry?.session.created_at ?? new Date().toISOString(),
        },
      };
      const history = existingThread.messages.slice(-8).map((message) => ({
        role: message.role,
        content: message.content,
      }));
      const userMessage: ChatMessagePayload = {
        id: createId("user"),
        tenant_id: "",
        session_id: sessionId,
        user_id: "",
        role: "user",
        content: prompt,
        provider: "",
        model: "",
        citations: [],
        metadata: {},
        created_at: new Date().toISOString(),
      };
      const assistantId = createId("assistant");
      const assistantMessage: ChatMessagePayload = {
        id: assistantId,
        tenant_id: "",
        session_id: sessionId,
        user_id: "",
        role: "assistant",
        content: "",
        provider: "",
        model: "",
        citations: [],
        metadata: { streaming: true, confidence: 0 },
        created_at: new Date().toISOString(),
      };

      queryClient.setQueryData<ChatMessagesResponse>(key, {
        session: existingThread.session,
        messages: [...existingThread.messages, userMessage, assistantMessage],
        count: existingThread.messages.length + 2,
      });

      const controller = new AbortController();
      setStreamAbortController(controller);

      const updateAssistant = (updater: (message: ChatMessagePayload) => ChatMessagePayload) => {
        queryClient.setQueryData<ChatMessagesResponse>(key, (current) => {
          if (!current) {
            return current;
          }
          return {
            ...current,
            messages: current.messages.map((message) =>
              message.id === assistantId ? updater(message) : message,
            ),
          };
        });
      };

      await streamChat(
        {
          question: prompt,
          top_k: chatTopK,
          session_id: sessionId,
          session_title: sessionTitle,
          chat_history: history,
        },
        {
          onMeta: (event) => {
            updateAssistant((message) => ({
              ...message,
              metadata: {
                ...message.metadata,
                ...event,
                streaming: true,
              },
            }));
          },
          onDelta: (event) => {
            updateAssistant((message) => ({
              ...message,
              content: `${message.content}${event.content}`,
            }));
          },
          onDone: (event) => {
            updateAssistant((message) => finalizeAssistantMessage(message, event));
          },
          onError: (event) => {
            updateAssistant((message) => ({
              ...message,
              content: message.content || event.message,
              metadata: {
                ...message.metadata,
                streaming: false,
                error: event.message,
              },
            }));
          },
        },
        controller.signal,
      );

      return { sessionId };
    },
    onError: (error, variables) => {
      if (error instanceof DOMException && error.name === "AbortError") {
        queryClient.setQueryData<ChatMessagesResponse>(
          ["chat-messages", variables.sessionId],
          (current) => {
            if (!current) {
              return current;
            }
            return {
              ...current,
              messages: current.messages.map((message) =>
                message.role === "assistant" && message.metadata.streaming
                  ? {
                      ...message,
                      metadata: {
                        ...message.metadata,
                        streaming: false,
                        stopped: true,
                      },
                    }
                  : message,
              ),
            };
          },
        );
        return;
      }

      const text = error instanceof ApiError ? error.message : "消息生成失败。";
      queryClient.setQueryData<ChatMessagesResponse>(
        ["chat-messages", variables.sessionId],
        (current) => {
          if (!current) {
            return current;
          }
          return {
            ...current,
            messages: current.messages.map((message) =>
              message.role === "assistant" && message.metadata.streaming
                ? {
                    ...message,
                    content: text,
                    metadata: {
                      ...message.metadata,
                      streaming: false,
                      error: text,
                    },
                  }
                : message,
            ),
          };
        },
      );
    },
    onSettled: async (_result, _error, variables) => {
      setStreamAbortController(null);
      await queryClient.invalidateQueries({ queryKey: ["chat-sessions"] });
      await queryClient.invalidateQueries({ queryKey: ["chat-messages", variables.sessionId] });
    },
  });

  const activeConfidence = Number(latestAssistant?.metadata.confidence ?? 0);
  const activeCitations = latestAssistant?.citations ?? [];
  const activeMetrics = {
    retrieval: formatDuration(Number(latestAssistant?.metadata.retrieval_ms ?? 0)),
    generation: formatDuration(Number(latestAssistant?.metadata.generation_ms ?? 0)),
    total: formatDuration(Number(latestAssistant?.metadata.total_ms ?? 0)),
  };

  const handleCreateSession = () => {
    const draft = ensureDraftChatSession();
    startTransition(() => setActiveChatSessionId(draft.id));
    queryClient.setQueryData<ChatMessagesResponse>(["chat-messages", draft.id], {
      ...EMPTY_THREAD,
      session: {
        ...EMPTY_THREAD.session,
        id: draft.id,
        title: draft.title,
      },
    });
  };

  const handleRenameSession = () => {
    if (!activeEntry) {
      return;
    }
    if (draftChatSession?.id === activeEntry.session.id) {
      renameDraftChatSession(renameValue.trim() || "新会话");
      setRenameOpen(false);
      return;
    }
    renameMutation.mutate({
      sessionId: activeEntry.session.id,
      title: renameValue.trim() || activeEntry.session.title,
    });
  };

  const handleSend = async () => {
    const prompt = question.trim();
    if (!prompt || chatMutation.isPending) {
      return;
    }

    const sessionId = activeChatSessionId ?? ensureDraftChatSession().id;
    const sessionTitle = activeEntry?.session.title || draftChatSession?.title || shortText(prompt, 24);
    setQuestion("");
    chatMutation.mutate({ prompt, sessionId, sessionTitle });
  };

  const isStreaming = Boolean(streamAbortController || chatMutation.isPending);

  return (
    <section
      className="surface-grid surface-grid-three min-h-0 max-xl:auto-rows-auto xl:h-[calc(100dvh-9.75rem)] xl:min-h-[560px]"
      style={{
        gridTemplateColumns: chatSidebarCollapsed ? "5rem minmax(0,1fr) 22rem" : "16rem minmax(0,1fr) 22rem",
      }}
      data-testid="chat-workbench"
    >
      <Card className="glass-panel order-2 flex min-h-[460px] flex-col overflow-hidden xl:order-none xl:h-full xl:min-h-0">
        <CardHeader className={cn("shrink-0", chatSidebarCollapsed && "px-3 py-4")}>
          <div className="flex items-center justify-between gap-2">
            {!chatSidebarCollapsed ? (
              <div>
                <CardTitle>会话历史</CardTitle>
              </div>
            ) : null}
            <Button variant="ghost" size="icon" onClick={toggleChatSidebar} data-testid="chat-sidebar-toggle">
              {chatSidebarCollapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
            </Button>
          </div>
        </CardHeader>
        <CardContent className={cn("flex min-h-0 flex-1 flex-col space-y-3", chatSidebarCollapsed && "px-3")}>
          <Button className="w-full" size={chatSidebarCollapsed ? "icon" : "default"} onClick={handleCreateSession}>
            <Plus className="h-4 w-4" />
            {!chatSidebarCollapsed ? <span>新建会话</span> : null}
          </Button>
          {!chatSidebarCollapsed ? (
            <div className="relative">
              <Search className="pointer-events-none absolute left-4 top-3.5 h-4 w-4 text-slate-400" />
              <Input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="搜索会话标题"
                className="pl-10"
              />
            </div>
          ) : null}
          <ScrollArea className="snow-scrollbar min-h-0 flex-1 pr-2">
            <div className="space-y-2">
              {filteredSessions.length === 0 ? (
                <EmptyState
                  icon={Search}
                  title="没有找到匹配的会话"
                  description="试试更短的关键词，或者新建一个新的问题流。"
                  className={cn(chatSidebarCollapsed ? "px-2 py-4" : "px-4 py-6")}
                  actions={
                    chatSidebarCollapsed
                      ? []
                      : [{ label: "清空搜索", variant: "secondary", onClick: () => setSearch("") }]
                  }
                />
              ) : (
                filteredSessions.map((item) => {
                  const title = sessionTitle(item.session.title);
                  const preview = sessionPreview(item.last_message?.content);
                  return (
                    <button
                      key={item.session.id}
                      type="button"
                      title={preview}
                      aria-label={`打开会话：${title}`}
                      data-testid={`chat-session-${item.session.id}`}
                      onClick={() => startTransition(() => setActiveChatSessionId(item.session.id))}
                      className={cn(
                        "w-full rounded-[24px] border px-3 py-3 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/40",
                        activeChatSessionId === item.session.id
                          ? "border-teal-300 bg-[linear-gradient(145deg,rgba(240,253,250,0.96),rgba(222,247,244,0.92))] shadow-[0_18px_34px_rgba(15,118,110,0.08)]"
                          : "border-white/70 bg-white/65 hover:border-teal-200 hover:bg-white",
                        chatSidebarCollapsed ? "flex justify-center px-0" : "flex min-h-[112px] flex-col",
                      )}
                    >
                      {chatSidebarCollapsed ? (
                        <span className="text-sm font-semibold text-teal-800">{title.slice(0, 1) || "新"}</span>
                      ) : (
                        <>
                          <div className="flex items-start gap-3">
                            <div className="min-w-0 flex-1">
                              <p className="break-words text-sm font-semibold leading-5 text-slate-900">
                                {title}
                              </p>
                            </div>
                            <Badge variant="outline" className="shrink-0">
                              {item.message_count}
                            </Badge>
                          </div>
                          <p className="mt-2 break-words text-[12.5px] leading-[1.55] text-slate-700">
                            {preview}
                          </p>
                          <p className="mt-auto pt-3 text-[10.5px] font-semibold text-slate-500">
                            {formatRelativeTime(item.session.last_active_at)}
                          </p>
                        </>
                      )}
                    </button>
                  );
                })
              )}
            </div>
          </ScrollArea>
        </CardContent>
      </Card>

      <div className="order-1 min-h-0 xl:order-none xl:h-full">
        <Card className="glass-panel flex h-[calc(100dvh-14rem)] min-h-[600px] flex-col overflow-hidden xl:h-full xl:min-h-0">
          <CardHeader className="shrink-0 pb-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <CardTitle className="flex items-center gap-2">
                  {activeEntry ? readableText(activeEntry.session.title, UNREADABLE_TITLE) : "新会话"}
                  <TitleInfoIcon label="对话工作区说明">
                    中间区域负责流式对话，完成后右侧证据面板会自动补齐引用、耗时与置信度。
                  </TitleInfoIcon>
                  <Dialog open={renameOpen} onOpenChange={setRenameOpen}>
                    <DialogTrigger asChild>
                      <Button
                        size="icon"
                        variant="ghost"
                        onClick={() => setRenameValue(activeEntry?.session.title ?? "")}
                      >
                        <PencilLine className="h-4 w-4" />
                      </Button>
                    </DialogTrigger>
                    <DialogContent>
                      <DialogHeader>
                        <DialogTitle>重命名会话</DialogTitle>
                        <DialogDescription>修改左侧历史列表里的会话标题。</DialogDescription>
                      </DialogHeader>
                      <div className="space-y-4">
                        <div className="space-y-2">
                          <Label htmlFor="rename-session-input">标题</Label>
                          <Input
                            id="rename-session-input"
                            value={renameValue}
                            onChange={(event) => setRenameValue(event.target.value)}
                          />
                        </div>
                        <Button onClick={handleRenameSession} disabled={renameMutation.isPending}>
                          保存标题
                        </Button>
                      </div>
                    </DialogContent>
                  </Dialog>
                </CardTitle>
              </div>
              <div className="flex items-center gap-2">
                <Badge variant="outline">Top K {chatTopK}</Badge>
                {isStreaming ? (
                  <Badge variant="soft">
                    <LoaderCircle className="mr-1 h-3.5 w-3.5 animate-spin" />
                    正在生成
                  </Badge>
                ) : null}
              </div>
            </div>
          </CardHeader>
          <CardContent className="flex min-h-0 flex-1 flex-col gap-3">
            <ScrollArea className="snow-scrollbar min-h-0 flex-1 pr-4">
              <div className="space-y-3">
                {thread.messages.length === 0 ? (
                  <FirstPromptPanel
                    prompts={SUGGESTED_PROMPTS}
                    onSelect={(prompt) => setQuestion(prompt)}
                  />
                ) : (
                  thread.messages.map((message) => {
                    const isAssistant = message.role === "assistant";
                    const shouldAnimate = isAssistant && latestAssistant?.id === message.id;
                    const isStreamingMessage = Boolean(message.metadata.streaming);
                    const isUnreadable = isUnreadablePlaceholderText(message.content);
                    const messageContent = readableText(message.content);
                    return (
                      <motion.div
                        key={message.id}
                        initial={{ opacity: 0, y: 14 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ duration: 0.22, ease: "easeOut" }}
                        data-testid={isAssistant ? "chat-assistant-message" : "chat-user-message"}
                        className={cn("flex", isAssistant ? "justify-start" : "justify-end")}
                      >
                        <div
                          className={cn(
                            "rounded-[22px] px-4 py-2.5 text-[13px] leading-[1.65] shadow-sm",
                            isAssistant ? "chat-bubble-assistant max-w-[76%] text-slate-800" : "chat-bubble-user max-w-[64%] text-slate-900",
                            isUnreadable && "border-amber-200 bg-amber-50/80 text-amber-950",
                          )}
                        >
                          <div className="mb-1 flex items-center justify-between gap-3 text-[10px] uppercase tracking-[0.18em] text-slate-500">
                            <div className="flex items-center gap-2">
                              <span>{isAssistant ? "Aurora" : "You"}</span>
                              {isStreamingMessage ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : null}
                              {isUnreadable ? <Badge variant="outline">编码异常</Badge> : null}
                            </div>
                            <span className="font-mono normal-case tracking-normal text-slate-500">
                              {formatRelativeTime(message.created_at)}
                            </span>
                          </div>
                          <TypewriterText
                            content={messageContent}
                            animate={shouldAnimate}
                            streaming={isStreamingMessage}
                            className="min-h-[1.5rem]"
                          />
                          {isAssistant && latestAssistant?.id === message.id ? (
                            <div className="mt-3 flex flex-wrap items-center gap-2">
                              <Badge variant="outline">{activeCitations.length} citations</Badge>
                              <Badge variant="outline">{activeMetrics.total}</Badge>
                              {message.provider ? <Badge variant="soft">{message.provider}</Badge> : null}
                            </div>
                          ) : null}
                        </div>
                      </motion.div>
                    );
                  })
                )}
                <div ref={messageEndRef} className="h-px" aria-hidden="true" />
              </div>
            </ScrollArea>

            <div
              className="shrink-0 rounded-[22px] border border-white/70 bg-[linear-gradient(180deg,rgba(255,255,255,0.88),rgba(247,252,252,0.94))] p-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.78)]"
              data-testid="chat-input-shell"
            >
              <div className={cn("mb-2 flex flex-wrap items-center justify-end gap-3 text-xs text-slate-600", !streamAbortController && "hidden")}>
                <div className="hidden">
                  <span>支持流式逐字更新，回答完成后会自动联动右侧证据卡片。</span>
                </div>
                {streamAbortController ? (
                  <Button
                    variant="destructive"
                    size="sm"
                    onClick={() => streamAbortController.abort()}
                    data-testid="stop-chat-button"
                  >
                    <Square className="h-3.5 w-3.5" />
                    停止生成
                  </Button>
                ) : null}
              </div>
              <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
                <Textarea
                  value={question}
                  onChange={(event) => setQuestion(event.target.value)}
                  placeholder="输入问题，让 Aurora 结合知识库给出带引用的回答"
                  className="min-h-[58px] max-h-[120px] resize-none rounded-[18px]"
                  data-testid="chat-input"
                />
                <Button className="h-[58px] px-5" onClick={handleSend} disabled={!question.trim() || chatMutation.isPending} data-testid="send-chat-button">
                  发送问题
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card className="glass-panel order-3 flex min-h-[520px] flex-col overflow-hidden xl:order-none xl:h-full xl:min-h-0" data-testid="chat-sources-panel">
        <CardHeader className="shrink-0 pb-2">
          <CardTitle className="flex items-center gap-2">
            引用与检索
            <TitleInfoIcon label="引用与检索说明">固定承载当前回答的引用片段、耗时指标与 Top K 调整。</TitleInfoIcon>
          </CardTitle>
        </CardHeader>
        <CardContent className="flex min-h-0 flex-1 flex-col gap-3">
          <div className="rounded-[24px] border border-white/70 bg-white/76 p-3" data-testid="chat-evidence-summary">
            <div className="flex items-center gap-3">
              <ConfidenceRing value={activeConfidence} />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold text-slate-900">回答置信度</p>
                <p className="text-xs text-slate-500">{formatConfidence(activeConfidence)}</p>
                <div className="mt-2 flex items-center justify-between">
                  <p className="text-xs font-semibold text-slate-700">Top K</p>
                  <Badge variant="soft">{chatTopK}</Badge>
                </div>
                <Slider
                  value={[chatTopK]}
                  onValueChange={(value) => setChatTopK(value[0] ?? 4)}
                  min={1}
                  max={10}
                  step={1}
                  className="mt-2"
                />
              </div>
            </div>
          </div>
          <div className="flex min-h-0 flex-1 flex-col gap-3">
            <div className="flex items-center justify-between">
              <p className="text-sm font-semibold text-slate-900">引用片段</p>
              <Badge variant="outline">{activeCitations.length}</Badge>
            </div>
            <ScrollArea className="snow-scrollbar min-h-0 flex-1 pr-3">
              <AnimatePresence mode="popLayout">
                <div className="space-y-3">
                  {latestAssistant ? (
                    activeCitations.length === 0 ? (
                      <EvidenceEmptyState
                        icon={FileSearch}
                        title="这轮回答还没有引用片段"
                        description="如果回答来自通用推理或检索为空，这里会保持安静；调整 Top K 后下一轮会立刻生效。"
                        className="py-4"
                      />
                    ) : (
                      activeCitations.map((citation, index) => (
                        <CitationCard key={citation.knowledge_id} citation={citation} index={index} />
                      ))
                    )
                  ) : (
                    <EvidenceEmptyState
                      icon={Sparkles}
                      title="等待第一条回答"
                      description="对话开始后，这里会同步展示引用文档、高亮片段、相似度和整轮耗时。"
                      className="py-4"
                    />
                  )}
                </div>
              </AnimatePresence>
            </ScrollArea>
          </div>
          <div className="grid shrink-0 grid-cols-3 gap-2">
            <MetricLine icon={FileSearch} label="检索耗时" value={activeMetrics.retrieval} />
            <MetricLine icon={DatabaseZap} label="生成耗时" value={activeMetrics.generation} />
            <MetricLine icon={ShieldCheck} label="总耗时" value={activeMetrics.total} />
          </div>
        </CardContent>
      </Card>
    </section>
  );
}

function finalizeAssistantMessage(message: ChatMessagePayload, event: ChatDoneEvent): ChatMessagePayload {
  return {
    ...message,
    content: event.answer,
    provider: event.provider,
    model: event.model,
    citations: event.citations,
    metadata: {
      ...message.metadata,
      ...event,
      streaming: false,
    },
  };
}

function PromptHint({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-3 rounded-[16px] border border-white/70 bg-white/72 px-3 py-2">
      <span className="text-[10px] uppercase tracking-[0.2em] text-slate-400">{label}</span>
      <span className="max-w-[68%] text-right text-[12.5px] leading-5 text-slate-600">{value}</span>
    </div>
  );
}

function FirstPromptPanel({
  prompts,
  onSelect,
}: {
  prompts: string[];
  onSelect: (prompt: string) => void;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12, scale: 0.99 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.24, ease: "easeOut" }}
      data-testid="chat-first-prompt-panel"
      className="relative overflow-hidden rounded-[22px] border border-teal-100 bg-[linear-gradient(140deg,rgba(255,255,255,0.9),rgba(241,250,249,0.78))] px-4 py-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.78)]"
    >
      <div className="relative grid gap-3 xl:grid-cols-[minmax(0,1fr)_17rem] xl:items-center">
        <div className="flex min-w-0 items-start gap-3">
          <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-[12px] border border-teal-100 bg-white/86 text-teal-700">
            <Sparkles className="h-[18px] w-[18px]" />
          </div>
          <div className="min-w-0">
            <p className="text-[9.5px] uppercase tracking-[0.18em] text-teal-700/65">First Prompt</p>
            <h3 className="mt-1 font-display text-[1.18rem] leading-tight text-slate-900">
              向 Aurora 发出第一个问题
            </h3>
            <p className="mt-1 max-w-2xl text-[12.5px] leading-5 text-slate-600">
              它会检索知识库、流式生成答案，并把引用依据同步到右侧面板。
            </p>
          </div>
        </div>

        <div className="grid gap-2 rounded-[18px] border border-white/75 bg-white/78 p-2 text-left">
          <PromptHint label="适合提问" value="故障排查、README 对齐、环境配置、知识库总结" />
          <PromptHint label="输出联动" value="引用片段、检索耗时、总耗时与置信度" />
        </div>
      </div>

      <div className="relative mt-2.5 grid grid-cols-1 gap-2 md:grid-cols-3">
        {prompts.map((prompt, index) => (
          <Button
            key={prompt}
            type="button"
            size="sm"
            variant={index === 0 ? "default" : "secondary"}
            className={cn("h-8 min-w-0 rounded-full px-3 text-xs", index > 0 && "bg-white/80")}
            onClick={() => onSelect(prompt)}
            title={prompt}
          >
            <span className="truncate">{prompt}</span>
          </Button>
        ))}
      </div>
    </motion.div>
  );
}

function EvidenceEmptyState({
  icon: Icon,
  title,
  description,
  className,
}: {
  icon: LucideIcon;
  title: string;
  description: string;
  className?: string;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.22, ease: "easeOut" }}
      data-testid="chat-evidence-empty-state"
      className={cn(
        "relative overflow-hidden rounded-[22px] border border-dashed border-teal-200/85 bg-[linear-gradient(145deg,rgba(255,255,255,0.9),rgba(236,248,246,0.74))] px-4 py-4 text-left shadow-[inset_0_1px_0_rgba(255,255,255,0.78)]",
        className,
      )}
    >
      <div className="pointer-events-none absolute -right-8 -top-10 h-28 w-28 rounded-full bg-cyan-100/55 blur-2xl" />
      <div className="pointer-events-none absolute left-4 top-5 h-2 w-2 rounded-full bg-teal-300/80 shadow-[0_0_0_7px_rgba(20,184,166,0.08)]" />
      <div className="relative flex items-start gap-3">
        <div className="mt-0.5 flex h-11 w-11 shrink-0 items-center justify-center rounded-[16px] border border-white/80 bg-white/90 text-teal-700 shadow-[0_12px_24px_rgba(15,118,110,0.11)] backdrop-blur-xl">
          <Icon className="h-5 w-5" />
        </div>
        <div className="min-w-0 flex-1">
          <h3 className="mt-1 text-[15px] font-semibold leading-6 text-slate-900">
            {title}
          </h3>
          <p className="mt-1 text-[12.5px] leading-5 text-slate-600">
            {description}
          </p>
        </div>
      </div>
    </motion.div>
  );
}

function CitationCard({ citation, index }: { citation: CitationPayload; index: number }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.22, delay: Math.min(index * 0.04, 0.16), ease: "easeOut" }}
      data-testid="chat-citation-card"
      className="rounded-[20px] border border-white/70 bg-white/72 p-3"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <p className="break-all text-sm font-semibold leading-5 text-slate-800">{citation.file_name}</p>
          <p className="mt-1 break-all text-xs leading-4 text-slate-500">{citation.relative_path}</p>
        </div>
        <Badge variant="soft">{Math.round((citation.score ?? 0) * 100)}%</Badge>
      </div>
      <div className="mt-2 whitespace-pre-wrap break-words rounded-[16px] bg-teal-50/75 px-3 py-2 text-[12px] leading-[1.55] text-slate-800">
        {citation.snippet}
      </div>
    </motion.div>
  );
}

function ConfidenceRing({ value }: { value: number }) {
  const radius = 42;
  const circumference = 2 * Math.PI * radius;
  const progress = Math.max(0, Math.min(1, value));
  const offset = circumference * (1 - progress);

  return (
    <svg viewBox="0 0 120 120" className="h-16 w-16 shrink-0">
      <circle cx="60" cy="60" r={radius} fill="none" stroke="rgba(15,118,110,0.12)" strokeWidth="10" />
      <circle
        cx="60"
        cy="60"
        r={radius}
        fill="none"
        stroke="url(#aurora-confidence)"
        strokeLinecap="round"
        strokeWidth="10"
        strokeDasharray={circumference}
        strokeDashoffset={offset}
        transform="rotate(-90 60 60)"
      />
      <circle cx="60" cy="60" r="32" fill="rgba(255,255,255,0.74)" />
      <text x="60" y="58" textAnchor="middle" className="fill-slate-900 text-[20px] font-semibold">
        {Math.round(progress * 100)}
      </text>
      <text x="60" y="76" textAnchor="middle" className="fill-slate-400 text-[10px] uppercase tracking-[0.2em]">
        信心值
      </text>
      <defs>
        <linearGradient id="aurora-confidence" x1="0%" x2="100%">
          <stop offset="0%" stopColor="#0f766e" />
          <stop offset="100%" stopColor="#7dd3fc" />
        </linearGradient>
      </defs>
    </svg>
  );
}

function MetricLine({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof FileSearch;
  label: string;
  value: string;
}) {
  return (
    <div className="min-w-0 rounded-[18px] border border-white/70 bg-white/72 px-2 py-2">
      <div className="flex min-w-0 items-center gap-1.5">
        <div className="shrink-0 rounded-xl bg-teal-50 p-1 text-teal-700">
          <Icon className="h-3.5 w-3.5" />
        </div>
        <span className="truncate text-[11px] text-slate-600">{label}</span>
      </div>
      <span className="mt-1 block truncate font-mono text-[11px] font-semibold text-slate-900">{value}</span>
    </div>
  );
}
