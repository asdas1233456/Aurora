import { Suspense, lazy, startTransition, useEffect, useMemo, type ReactNode } from "react";

import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { useQuery } from "@tanstack/react-query";
import { Bot, ChartNetwork, Database, FileTerminal, Home, Settings2 } from "lucide-react";
import { NavLink, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";

import { getWorkspaceBootstrap } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { useAppStore, type NavKey } from "@/store/app-store";


const PAGE_LOADERS = {
  overview: () => import("@/pages/overview-page"),
  knowledge: () => import("@/pages/knowledge-page"),
  chat: () => import("@/pages/chat-page"),
  graph: () => import("@/pages/graph-page"),
  settings: () => import("@/pages/settings-page"),
  logs: () => import("@/pages/logs-page"),
};

const OverviewPage = lazy(() => PAGE_LOADERS.overview().then((module) => ({ default: module.OverviewPage })));
const KnowledgePage = lazy(() => PAGE_LOADERS.knowledge().then((module) => ({ default: module.KnowledgePage })));
const ChatPage = lazy(() => PAGE_LOADERS.chat().then((module) => ({ default: module.ChatPage })));
const GraphPage = lazy(() => PAGE_LOADERS.graph().then((module) => ({ default: module.GraphPage })));
const SettingsPage = lazy(() => PAGE_LOADERS.settings().then((module) => ({ default: module.SettingsPage })));
const LogsPage = lazy(() => PAGE_LOADERS.logs().then((module) => ({ default: module.LogsPage })));

const NAV_ITEMS: Array<{
  key: NavKey;
  to: string;
  label: string;
  permission: string;
  icon: typeof Home;
}> = [
  { key: "overview", to: "/", label: "总览", permission: "system.read", icon: Home },
  { key: "knowledge", to: "/knowledge", label: "知识库", permission: "documents.read", icon: Database },
  { key: "chat", to: "/chat", label: "对话", permission: "chat.use", icon: Bot },
  { key: "graph", to: "/graph", label: "图谱", permission: "graph.read", icon: ChartNetwork },
  { key: "settings", to: "/settings", label: "设置", permission: "settings.read", icon: Settings2 },
  { key: "logs", to: "/logs", label: "日志", permission: "logs.read", icon: FileTerminal },
];

export function App() {
  const location = useLocation();
  const navigate = useNavigate();
  const reducedMotion = useReducedMotion();
  const setWorkspaceMeta = useAppStore((state) => state.setWorkspaceMeta);
  const workspaceQuery = useQuery({
    queryKey: ["workspace-bootstrap"],
    queryFn: getWorkspaceBootstrap,
  });

  useEffect(() => {
    if (!workspaceQuery.data?.auth || !workspaceQuery.data?.overview) {
      return;
    }

    setWorkspaceMeta({
      auth: workspaceQuery.data.auth,
      overview: workspaceQuery.data.overview,
    });
  }, [setWorkspaceMeta, workspaceQuery.data]);

  const allowedNavItems = useMemo(() => {
    const permissions = new Set(workspaceQuery.data?.auth.permissions ?? []);
    return NAV_ITEMS.filter((item) => permissions.has(item.permission));
  }, [workspaceQuery.data?.auth.permissions]);

  const activeNavItem = useMemo(() => {
    return allowedNavItems.find((item) =>
      item.to === "/"
        ? location.pathname === "/"
        : location.pathname.startsWith(item.to),
    ) ?? allowedNavItems[0] ?? NAV_ITEMS[0];
  }, [allowedNavItems, location.pathname]);

  useEffect(() => {
    if (workspaceQuery.isLoading || workspaceQuery.isError || allowedNavItems.length === 0) {
      return;
    }

    const isKnownRoute = allowedNavItems.some((item) =>
      item.to === "/"
        ? location.pathname === "/"
        : location.pathname.startsWith(item.to),
    );
    if (!isKnownRoute) {
      startTransition(() => navigate(allowedNavItems[0].to, { replace: true }));
    }
  }, [allowedNavItems, location.pathname, navigate, workspaceQuery.isError, workspaceQuery.isLoading]);

  if (workspaceQuery.isLoading) {
    return <LoadingScreen />;
  }

  if (workspaceQuery.isError || !workspaceQuery.data) {
    return <FailureScreen />;
  }

  const permissions = new Set(workspaceQuery.data.auth.permissions);
  const guard = (permission: string, element: ReactNode) =>
    permissions.has(permission) ? element : <Navigate to={allowedNavItems[0]?.to ?? "/"} replace />;

  return (
    <div className="relative min-h-dvh overflow-x-hidden px-4 pb-4 pt-4 md:px-6">
      <div className="aurora-orb aurora-orb-left" />
      <div className="aurora-orb aurora-orb-right" />
      <div className="mx-auto flex min-h-[calc(100dvh-2rem)] max-w-[1680px] flex-col gap-3">
        <header className="glass-panel flex flex-col gap-2 rounded-[28px] px-4 py-3 md:px-5">
          <div className="flex flex-col gap-2 xl:flex-row xl:items-center xl:justify-between">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-[16px] bg-teal-50 text-teal-700 ring-1 ring-teal-100">
                <Home className="h-5 w-5" aria-hidden="true" />
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="font-display text-[1.5rem] leading-none text-slate-900 md:text-[1.72rem]" data-testid="hero-title">
                  Aurora
                </h1>
                <Badge variant="soft">{workspaceQuery.data.overview.app_version}</Badge>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="outline" data-testid="workspace-user-badge">
                {workspaceQuery.data.auth.user.display_name}
              </Badge>
            </div>
          </div>

          <nav className="flex flex-wrap items-center gap-2" aria-label="Primary">
            {allowedNavItems.map((item) => {
              const Icon = item.icon;
              return (
                <NavLink
                  key={item.key}
                  to={item.to}
                  data-testid={`nav-${item.key}`}
                  onMouseEnter={() => void PAGE_LOADERS[item.key]()}
                  onFocus={() => void PAGE_LOADERS[item.key]()}
                  className={({ isActive }) =>
                    cn(
                      "inline-flex items-center gap-2 rounded-full border px-3 py-2 text-[0.88rem] transition",
                      isActive
                        ? "border-teal-600/70 bg-teal-700 text-white shadow-[0_10px_24px_rgba(15,118,110,0.18)]"
                        : "border-white/60 bg-white/60 text-slate-700 hover:border-teal-300 hover:text-teal-800",
                    )
                  }
                >
                  <Icon className="h-4 w-4" />
                  <span>{item.label}</span>
                </NavLink>
              );
            })}
          </nav>
        </header>

        <AnimatePresence mode="wait">
          <motion.main
            key={location.pathname}
            className="flex-1"
            initial={reducedMotion ? undefined : { opacity: 0, y: 8 }}
            animate={reducedMotion ? undefined : { opacity: 1, y: 0 }}
            exit={reducedMotion ? undefined : { opacity: 0, y: -4 }}
            transition={{ duration: reducedMotion ? 0 : 0.18, ease: "easeOut" }}
          >
            <Suspense fallback={<PagePendingState />}>
              <Routes location={location}>
                <Route path="/" element={guard("system.read", <OverviewPage />)} />
                <Route path="/knowledge" element={guard("documents.read", <KnowledgePage />)} />
                <Route path="/chat" element={guard("chat.use", <ChatPage />)} />
                <Route path="/graph" element={guard("graph.read", <GraphPage />)} />
                <Route path="/settings" element={guard("settings.read", <SettingsPage />)} />
                <Route path="/logs" element={guard("logs.read", <LogsPage />)} />
              </Routes>
            </Suspense>
          </motion.main>
        </AnimatePresence>
      </div>
    </div>
  );
}

function PagePendingState() {
  return (
    <div className="glass-panel flex min-h-[60dvh] items-center justify-center rounded-[28px]">
      <div className="max-w-md space-y-3 px-6 py-8 text-center">
        <h2 className="font-display text-3xl text-slate-900">正在切换页面</h2>
        <p className="text-sm leading-7 text-slate-500">请稍候，Aurora 正在载入当前工作区。</p>
        <div className="mx-auto h-2 w-44 overflow-hidden rounded-full bg-teal-100">
          <div className="aurora-shimmer h-full w-3/4 rounded-full bg-gradient-to-r from-teal-500 via-cyan-400 to-teal-500" />
        </div>
      </div>
    </div>
  );
}

function LoadingScreen() {
  return (
    <div className="min-h-dvh px-4 py-4">
      <div className="glass-panel mx-auto flex min-h-[92dvh] max-w-[1680px] items-center justify-center rounded-[28px]">
        <div className="space-y-3 text-center">
          <h1 className="font-display text-3xl text-slate-900">正在载入工作台</h1>
          <div className="mx-auto h-2 w-40 overflow-hidden rounded-full bg-teal-100">
            <div className="aurora-shimmer h-full w-2/3 rounded-full bg-gradient-to-r from-teal-500 to-cyan-400" />
          </div>
        </div>
      </div>
    </div>
  );
}

function FailureScreen() {
  return (
    <div className="min-h-dvh px-4 py-4">
      <div className="glass-panel mx-auto flex min-h-[92dvh] max-w-[1680px] items-center justify-center rounded-[28px]">
        <div className="max-w-lg space-y-3 text-center">
          <h1 className="font-display text-3xl text-slate-900">工作台数据暂不可用</h1>
          <p className="text-sm leading-7 text-slate-600">
            请确认后端已经启动，并检查当前账户是否具备访问权限。
          </p>
        </div>
      </div>
    </div>
  );
}
