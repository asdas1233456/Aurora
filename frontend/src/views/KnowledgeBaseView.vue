<template>
  <div class="page-grid">
    <section class="page-heading">
      <p class="eyebrow">Knowledge Base</p>
      <h1>上传、预览并重建测试知识库</h1>
      <p class="page-desc">文档会保存在 data 目录中，建库时会自动完成解析、切分和向量化。</p>
    </section>

    <section class="stats-grid">
      <StatCard label="文档数" :value="documents.length" />
      <StatCard label="片段数" :value="status.chunk_count || 0" />
      <StatCard label="知识库状态" :value="status.ready ? '已建立' : '未建立'" />
      <StatCard label="最近反馈" :value="statusText || '等待操作'" />
    </section>

    <div class="content-grid two-column">
      <PanelCard title="上传文档" tag="Upload">
        <input class="input" type="file" multiple accept=".pdf,.txt,.md" @change="handleFiles" />
        <div class="button-row">
          <button class="button button-primary" :disabled="!selectedFiles.length || busy.upload" @click="submitUpload">
            {{ busy.upload ? "上传中..." : "保存上传文件" }}
          </button>
        </div>
        <ul v-if="selectedFiles.length" class="file-list">
          <li v-for="item in selectedFiles" :key="item.name">{{ item.name }}</li>
        </ul>
      </PanelCard>

      <PanelCard title="重建知识库" tag="Build">
        <p class="muted">重建会覆盖当前 collection，并重新写入全部文本片段。</p>
        <button class="button button-primary" :disabled="busy.rebuild" @click="handleRebuild">
          {{ busy.rebuild ? "重建中..." : "立即重建" }}
        </button>
        <p v-if="statusText" class="feedback success-text">{{ statusText }}</p>
      </PanelCard>
    </div>

    <div class="content-grid two-column">
      <PanelCard title="文档清单" tag="List">
        <div v-if="documents.length" class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th>文件名</th>
                <th>类型</th>
                <th>大小</th>
                <th>更新时间</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in documents" :key="item.path" @click="selectPreview(item.path)" class="clickable-row">
                <td>{{ item.name }}</td>
                <td>{{ item.extension.toUpperCase() }}</td>
                <td>{{ formatFileSize(item.size_bytes) }}</td>
                <td>{{ item.updated_at }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else class="empty-tip">当前还没有文档。</p>
      </PanelCard>

      <PanelCard title="文档预览" tag="Preview">
        <textarea class="textarea preview-text" :value="previewText" readonly></textarea>
      </PanelCard>
    </div>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref } from "vue";
import {
  getDocumentPreview,
  getDocuments,
  getKnowledgeBaseStatus,
  rebuildKnowledgeBase,
  uploadDocuments,
} from "../api/client";
import PanelCard from "../components/PanelCard.vue";
import StatCard from "../components/StatCard.vue";

const documents = ref([]);
const status = ref({ ready: false, chunk_count: 0 });
const previewText = ref("请选择左侧文档查看预览。");
const selectedFiles = ref([]);
const statusText = ref("");
const busy = ref({
  upload: false,
  rebuild: false,
});

async function loadData() {
  [documents.value, status.value] = await Promise.all([getDocuments(), getKnowledgeBaseStatus()]);
  if (documents.value.length && previewText.value === "请选择左侧文档查看预览。") {
    await selectPreview(documents.value[0].path);
  }
}

function handleFiles(event) {
  selectedFiles.value = [...event.target.files];
}

async function submitUpload() {
  busy.value.upload = true;
  statusText.value = "";
  try {
    await uploadDocuments(selectedFiles.value);
    selectedFiles.value = [];
    await loadData();
    statusText.value = "文件已保存到 data 目录。";
  } catch (error) {
    statusText.value = String(error.message || error);
  } finally {
    busy.value.upload = false;
  }
}

async function handleRebuild() {
  busy.value.rebuild = true;
  statusText.value = "";
  try {
    const result = await rebuildKnowledgeBase();
    statusText.value = `重建完成：处理 ${result.document_count} 个文档，生成 ${result.chunk_count} 个片段。`;
    await loadData();
  } catch (error) {
    statusText.value = String(error.message || error);
  } finally {
    busy.value.rebuild = false;
  }
}

async function selectPreview(path) {
  const result = await getDocumentPreview(path);
  previewText.value = result.preview || "当前文件没有可预览内容。";
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
