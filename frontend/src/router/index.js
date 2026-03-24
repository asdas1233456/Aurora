import { createRouter, createWebHistory } from "vue-router";
import ChatView from "../views/ChatView.vue";
import DashboardView from "../views/DashboardView.vue";
import KnowledgeBaseView from "../views/KnowledgeBaseView.vue";
import LogsView from "../views/LogsView.vue";
import SettingsView from "../views/SettingsView.vue";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", component: DashboardView },
    { path: "/knowledge-base", component: KnowledgeBaseView },
    { path: "/chat", component: ChatView },
    { path: "/settings", component: SettingsView },
    { path: "/logs", component: LogsView },
  ],
});

export default router;
