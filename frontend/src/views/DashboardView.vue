<template>
  <div class="page-grid">
    <section class="hero-card">
      <div>
        <p class="eyebrow">Product Dashboard</p>
        <h1>把测试知识、检索问答和接口调试放到一个前端工作台里</h1>
        <p class="hero-text">
          这里展示系统健康度、知识资产规模、接口连通性和最近文档变化。你也可以直接在左侧填临时
          Key，不改 .env 就能验证第三方模型接口。
        </p>
      </div>
      <div class="hero-grid">
        <div class="mini-pill" :class="{ success: overview.llm_api_ready }">
          {{ overview.llm_api_ready ? "LLM API 就绪" : "LLM API 未就绪" }}
        </div>
        <div class="mini-pill" :class="{ success: overview.embedding_api_ready }">
          {{ overview.embedding_api_ready ? "Embedding 就绪" : "Embedding 未就绪" }}
        </div>
        <div class="mini-pill" :class="{ success: overview.knowledge_base_ready }">
          {{ overview.knowledge_base_ready ? "知识库已建立" : "知识库待建立" }}
        </div>
      </div>
    </section>

    <section class="stats-grid">
      <StatCard label="知识文档" :value="overview.source_file_count" hint="已发现的经验资料数量" />
      <StatCard label="向量片段" :value="overview.chunk_count" hint="当前 Chroma 中的片段总量" />
      <StatCard label="文档体积" :value="formatFileSize(totalSizeBytes)" hint="知识资产总体积" />
      <StatCard label="日志行数" :value="logs.summary?.line_count || 0" hint="最近运行日志规模" />
    </section>

    <div class="content-grid two-column">
      <PanelCard title="知识主题分布" tag="Chart">
        <div style="height: 280px">
          <Bar v-if="barData.labels.length" :data="barData" :options="barOptions" />
          <p v-else class="empty-tip">当前还没有可展示的主题数据。</p>
        </div>
      </PanelCard>

      <PanelCard title="文件类型占比" tag="Chart">
        <div style="height: 280px">
          <Doughnut v-if="doughnutData.labels.length" :data="doughnutData" :options="doughnutOptions" />
          <p v-else class="empty-tip">当前还没有文件类型数据。</p>
        </div>
      </PanelCard>
    </div>

    <div class="content-grid two-column">
      <PanelCard title="系统健康" tag="Status">
        <div class="health-list">
          <div class="health-row">
            <span>LLM Provider</span>
            <strong>{{ overview.llm_provider }}</strong>
          </div>
          <div class="health-row">
            <span>Embedding Provider</span>
            <strong>{{ overview.embedding_provider }}</strong>
          </div>
          <div class="health-row">
            <span>LLM API</span>
            <strong>{{ overview.llm_api_ready ? "已配置" : "未配置" }}</strong>
          </div>
          <div class="health-row">
            <span>Embedding API</span>
            <strong>{{ overview.embedding_api_ready ? "已配置" : "未配置" }}</strong>
          </div>
          <div class="health-row">
            <span>知识库状态</span>
            <strong>{{ overview.knowledge_base_ready ? "已建立" : "未建立" }}</strong>
          </div>
        </div>
      </PanelCard>

      <PanelCard title="快速入口" tag="Action">
        <div class="quick-list">
          <div class="quick-step">
            <strong>1.</strong>
            <span>先到“知识库”页确认测试资料和文档预览。</span>
          </div>
          <div class="quick-step">
            <strong>2.</strong>
            <span>填写左侧临时测试 Key，或者在“配置”页保存正式配置。</span>
          </div>
          <div class="quick-step">
            <strong>3.</strong>
            <span>重建知识库后，进入“对话”页提问并核对引用来源。</span>
          </div>
        </div>
      </PanelCard>
    </div>

    <PanelCard title="最近文档" tag="Recent">
      <div v-if="recentDocuments.length" class="table-wrap">
        <table class="data-table">
          <thead>
            <tr>
              <th>文件名</th>
              <th>主题</th>
              <th>类型</th>
              <th>大小</th>
              <th>更新时间</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in recentDocuments" :key="item.path">
              <td>{{ item.name }}</td>
              <td>{{ inferCategory(item.name) }}</td>
              <td>{{ item.extension.toUpperCase() }}</td>
              <td>{{ formatFileSize(item.size_bytes) }}</td>
              <td>{{ item.updated_at }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else class="empty-tip">当前还没有文档。</p>
    </PanelCard>
  </div>
</template>

<script setup>
import { Chart as ChartJS, ArcElement, BarElement, CategoryScale, Legend, LinearScale, Tooltip } from "chart.js";
import { computed, onMounted, onUnmounted, ref } from "vue";
import { Bar, Doughnut } from "vue-chartjs";
import PanelCard from "../components/PanelCard.vue";
import StatCard from "../components/StatCard.vue";
import { getDocuments, getLogs, getOverview } from "../api/client";

ChartJS.register(ArcElement, BarElement, CategoryScale, Legend, LinearScale, Tooltip);

const overview = ref({
  llm_provider: "-",
  embedding_provider: "-",
  llm_api_ready: false,
  embedding_api_ready: false,
  knowledge_base_ready: false,
  source_file_count: 0,
  chunk_count: 0,
});
const documents = ref([]);
const logs = ref({ summary: { line_count: 0 } });

const totalSizeBytes = computed(() =>
  documents.value.reduce((total, item) => total + item.size_bytes, 0)
);

const recentDocuments = computed(() =>
  [...documents.value].sort((a, b) => b.updated_at.localeCompare(a.updated_at)).slice(0, 6)
);

const categoryStats = computed(() => {
  const accumulator = new Map();
  for (const item of documents.value) {
    const category = inferCategory(item.name);
    const current = accumulator.get(category) || { size: 0, count: 0 };
    accumulator.set(category, {
      size: current.size + item.size_bytes,
      count: current.count + 1,
    });
  }
  return [...accumulator.entries()].map(([label, value]) => ({
    label,
    sizeKb: Number((value.size / 1024).toFixed(2)),
    count: value.count,
  }));
});

const extensionStats = computed(() => {
  const accumulator = new Map();
  for (const item of documents.value) {
    const extension = item.extension.toUpperCase();
    accumulator.set(extension, (accumulator.get(extension) || 0) + 1);
  }
  return [...accumulator.entries()].map(([label, count]) => ({ label, count }));
});

const barData = computed(() => ({
  labels: categoryStats.value.map((item) => item.label),
  datasets: [
    {
      label: "大小（KB）",
      data: categoryStats.value.map((item) => item.sizeKb),
      backgroundColor: ["#0ea5e9", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#14b8a6"],
      borderRadius: 10,
    },
  ],
}));

const doughnutData = computed(() => ({
  labels: extensionStats.value.map((item) => item.label),
  datasets: [
    {
      label: "文件数",
      data: extensionStats.value.map((item) => item.count),
      backgroundColor: ["#0ea5e9", "#10b981", "#f97316", "#8b5cf6"],
      borderWidth: 0,
    },
  ],
}));

const barOptions = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: { display: false },
  },
};

const doughnutOptions = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: { position: "bottom" },
  },
};

async function loadData() {
  [overview.value, documents.value, logs.value] = await Promise.all([
    getOverview(),
    getDocuments(),
    getLogs(20),
  ]);
}

function inferCategory(fileName) {
  const stem = fileName.replace(/\.[^.]+$/, "");
  const normalized = /^\d+_/.test(stem) ? stem.replace(/^\d+_/, "") : stem;
  return normalized.replaceAll("_", " ").replace(/\b\w/g, (char) => char.toUpperCase());
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

function handleRuntimeChange() {
  loadData();
}

onMounted(() => {
  loadData();
  window.addEventListener("runtime-config-changed", handleRuntimeChange);
});

onUnmounted(() => {
  window.removeEventListener("runtime-config-changed", handleRuntimeChange);
});
</script>
