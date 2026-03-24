<template>
  <div class="layout">
    <aside class="sidebar">
      <div class="brand-card">
        <div class="brand-mark">AU</div>
        <div>
          <h1>Aurora</h1>
          <p>软件测试知识工作台</p>
        </div>
      </div>

      <nav class="nav-list">
        <RouterLink
          v-for="item in navItems"
          :key="item.to"
          :to="item.to"
          class="nav-item"
        >
          <span class="nav-icon">{{ item.icon }}</span>
          <span>{{ item.label }}</span>
        </RouterLink>
      </nav>

      <section class="runtime-card">
        <div class="section-header">
          <h3>临时测试 Key</h3>
          <span class="tag">{{ runtimeState.active ? "已启用" : "未启用" }}</span>
        </div>
        <p class="muted">
          只保存在当前浏览器本地，不会写入 `.env`。适合临时联调 OpenAI
          或兼容 OpenAI 协议的第三方模型接口。
        </p>

        <label class="field-label">LLM API Key</label>
        <input
          v-model="form.llmApiKey"
          type="password"
          class="input"
          placeholder="输入测试 Key"
        />

        <label class="checkbox-line">
          <input v-model="form.useSameEmbeddingKey" type="checkbox" />
          <span>Embedding 使用同一 Key</span>
        </label>

        <template v-if="!form.useSameEmbeddingKey">
          <label class="field-label">Embedding API Key</label>
          <input
            v-model="form.embeddingApiKey"
            type="password"
            class="input"
            placeholder="输入 Embedding Key"
          />
        </template>

        <label class="field-label">LLM API Base</label>
        <input
          v-model="form.llmApiBase"
          type="text"
          class="input"
          placeholder="例如 https://xxx/v1"
        />

        <label class="checkbox-line">
          <input v-model="form.useSameEmbeddingBase" type="checkbox" />
          <span>Embedding 使用同一 Base</span>
        </label>

        <template v-if="!form.useSameEmbeddingBase">
          <label class="field-label">Embedding API Base</label>
          <input
            v-model="form.embeddingApiBase"
            type="text"
            class="input"
            placeholder="Embedding 接口地址"
          />
        </template>

        <div class="button-row">
          <button class="button button-primary" @click="saveRuntimeConfig">应用</button>
          <button class="button button-ghost" @click="clearRuntimeConfig">清空</button>
        </div>
      </section>

      <section class="runtime-card footer-card">
        <p class="muted">
          前端地址 <strong>http://127.0.0.1:8000</strong><br />
          API 文档 <strong>http://127.0.0.1:8000/docs</strong>
        </p>
      </section>
    </aside>

    <main class="main-content">
      <header class="topbar">
        <div>
          <p class="eyebrow">Aurora Workspace</p>
          <h2>{{ currentTitle }}</h2>
        </div>
        <div class="status-box">
          <span class="status-dot" :class="{ live: runtimeState.active }"></span>
          <span>{{ runtimeState.active ? "会话测试 Key 生效中" : "使用默认后端配置" }}</span>
        </div>
      </header>

      <RouterView />
    </main>
  </div>
</template>

<script setup>
import { computed, reactive } from "vue";
import { RouterLink, RouterView, useRoute } from "vue-router";
import {
  clearRuntimeConfigStorage,
  getRuntimeConfigStorage,
  saveRuntimeConfigStorage,
} from "./api/runtimeConfig";

const route = useRoute();

const navItems = [
  { to: "/", label: "Dashboard", icon: "DB" },
  { to: "/knowledge-base", label: "知识库", icon: "KB" },
  { to: "/chat", label: "对话", icon: "CH" },
  { to: "/settings", label: "配置", icon: "CF" },
  { to: "/logs", label: "日志", icon: "LG" },
];

const storedConfig = getRuntimeConfigStorage();
const form = reactive({
  llmApiKey: storedConfig.llmApiKey || "",
  embeddingApiKey: storedConfig.embeddingApiKey || "",
  llmApiBase: storedConfig.llmApiBase || "",
  embeddingApiBase: storedConfig.embeddingApiBase || "",
  useSameEmbeddingKey: storedConfig.useSameEmbeddingKey ?? true,
  useSameEmbeddingBase: storedConfig.useSameEmbeddingBase ?? true,
});

const runtimeState = reactive({
  active: Boolean(
    storedConfig.llmApiKey ||
      storedConfig.embeddingApiKey ||
      storedConfig.llmApiBase ||
      storedConfig.embeddingApiBase,
  ),
});

const titleMap = {
  "/": "Dashboard",
  "/knowledge-base": "知识库",
  "/chat": "对话",
  "/settings": "配置",
  "/logs": "日志",
};

const currentTitle = computed(() => titleMap[route.path] || "Aurora");

function saveRuntimeConfig() {
  saveRuntimeConfigStorage({ ...form });
  runtimeState.active = Boolean(
    form.llmApiKey || form.embeddingApiKey || form.llmApiBase || form.embeddingApiBase,
  );
  window.dispatchEvent(new CustomEvent("runtime-config-changed"));
}

function clearRuntimeConfig() {
  clearRuntimeConfigStorage();
  form.llmApiKey = "";
  form.embeddingApiKey = "";
  form.llmApiBase = "";
  form.embeddingApiBase = "";
  form.useSameEmbeddingKey = true;
  form.useSameEmbeddingBase = true;
  runtimeState.active = false;
  window.dispatchEvent(new CustomEvent("runtime-config-changed"));
}
</script>
