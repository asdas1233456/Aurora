<template>
  <div class="page-grid">
    <section class="page-heading">
      <p class="eyebrow">Logs</p>
      <h1>查看最近运行日志</h1>
      <p class="page-desc">适合排查知识库重建、接口调用和模型请求异常。</p>
    </section>

    <section class="stats-grid">
      <StatCard label="日志文件大小" :value="formatFileSize(logs.summary?.size_bytes || 0)" />
      <StatCard label="日志总行数" :value="logs.summary?.line_count || 0" />
    </section>

    <PanelCard title="日志查看器" tag="Live">
      <div class="button-row">
        <button class="button button-primary" @click="loadLogs">刷新日志</button>
        <button class="button button-ghost" @click="removeLogs">清空日志</button>
      </div>
      <textarea class="textarea preview-text" :value="joinedLogs" readonly rows="20"></textarea>
    </PanelCard>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { clearLogs, getLogs } from "../api/client";
import PanelCard from "../components/PanelCard.vue";
import StatCard from "../components/StatCard.vue";

const logs = ref({ summary: {}, lines: [] });

const joinedLogs = computed(() =>
  logs.value.lines?.length ? logs.value.lines.join("") : "当前没有日志内容。"
);

async function loadLogs() {
  logs.value = await getLogs(200);
}

async function removeLogs() {
  await clearLogs();
  await loadLogs();
}

function formatFileSize(sizeBytes) {
  const units = ["B", "KB", "MB", "GB"];
  let value = Number(sizeBytes);
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value.toFixed(1)} ${units[unitIndex]}`;
}

onMounted(loadLogs);
</script>
