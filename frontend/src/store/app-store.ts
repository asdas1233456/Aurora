import { create } from "zustand";

import { createId } from "@/lib/utils";
import type { AuthPayload, OverviewPayload } from "@/types/api";


export type NavKey = "overview" | "knowledge" | "chat" | "graph" | "settings" | "logs";

export interface DraftChatSession {
  id: string;
  title: string;
  createdAt: string;
}

interface AppState {
  auth: AuthPayload | null;
  overview: OverviewPayload | null;
  selectedDocumentId: string | null;
  activeChatSessionId: string | null;
  draftChatSession: DraftChatSession | null;
  chatSidebarCollapsed: boolean;
  chatTopK: number;
  graphThemeFilter: string;
  graphTypeFilter: string;
  streamAbortController: AbortController | null;
  setWorkspaceMeta: (payload: { auth: AuthPayload; overview: OverviewPayload }) => void;
  setSelectedDocumentId: (documentId: string | null) => void;
  toggleChatSidebar: () => void;
  setChatTopK: (value: number) => void;
  setGraphThemeFilter: (value: string) => void;
  setGraphTypeFilter: (value: string) => void;
  setActiveChatSessionId: (sessionId: string | null) => void;
  ensureDraftChatSession: () => DraftChatSession;
  renameDraftChatSession: (title: string) => void;
  clearDraftChatSession: () => void;
  setStreamAbortController: (controller: AbortController | null) => void;
}

export const useAppStore = create<AppState>((set, get) => ({
  auth: null,
  overview: null,
  selectedDocumentId: null,
  activeChatSessionId: null,
  draftChatSession: null,
  chatSidebarCollapsed: false,
  chatTopK: 4,
  graphThemeFilter: "",
  graphTypeFilter: "",
  streamAbortController: null,
  setWorkspaceMeta: ({ auth, overview }) => set({ auth, overview }),
  setSelectedDocumentId: (selectedDocumentId) => set({ selectedDocumentId }),
  toggleChatSidebar: () => set((state) => ({ chatSidebarCollapsed: !state.chatSidebarCollapsed })),
  setChatTopK: (chatTopK) => set({ chatTopK }),
  setGraphThemeFilter: (graphThemeFilter) => set({ graphThemeFilter }),
  setGraphTypeFilter: (graphTypeFilter) => set({ graphTypeFilter }),
  setActiveChatSessionId: (activeChatSessionId) => set({ activeChatSessionId }),
  ensureDraftChatSession: () => {
    const existing = get().draftChatSession;
    if (existing) {
      return existing;
    }

    const draft = {
      id: createId("session"),
      title: "新会话",
      createdAt: new Date().toISOString(),
    };
    set({ draftChatSession: draft, activeChatSessionId: draft.id });
    return draft;
  },
  renameDraftChatSession: (title) =>
    set((state) => ({
      draftChatSession: state.draftChatSession
        ? { ...state.draftChatSession, title }
        : state.draftChatSession,
    })),
  clearDraftChatSession: () => set({ draftChatSession: null }),
  setStreamAbortController: (streamAbortController) => set({ streamAbortController }),
}));
