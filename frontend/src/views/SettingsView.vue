<template>
  <div class="page-grid">
    <section class="page-heading">
      <p class="eyebrow">Settings</p>
      <h1>编辑后端 .env 配置</h1>
      <p class="page-desc">适合保存长期使用的模型参数和系统参数。保存后建议重启后端服务。</p>
    </section>

    <PanelCard title="系统配置" tag="Env">
      <div class="form-grid two-column">
        <div>
          <label class="field-label">LLM Provider</label>
          <select v-model="form.LLM_PROVIDER" class="input">
            <option value="openai">openai</option>
            <option value="openai_compatible">openai_compatible</option>
          </select>
        </div>
        <div>
          <label class="field-label">Embedding Provider</label>
          <select v-model="form.EMBEDDING_PROVIDER" class="input">
            <option value="openai">openai</option>
            <option value="openai_compatible">openai_compatible</option>
          </select>
        </div>
        <div>
          <label class="field-label">LLM Model</label>
          <input v-model="form.LLM_MODEL" class="input" type="text" />
        </div>
        <div>
          <label class="field-label">Embedding Model</label>
          <input v-model="form.EMBEDDING_MODEL" class="input" type="text" />
        </div>
        <div>
          <label class="field-label">LLM API Base</label>
          <input v-model="form.LLM_API_BASE" class="input" type="text" />
        </div>
        <div>
          <label class="field-label">Embedding API Base</label>
          <input v-model="form.EMBEDDING_API_BASE" class="input" type="text" />
        </div>
        <div>
          <label class="field-label">LLM API Key</label>
          <input v-model="form.LLM_API_KEY" class="input" type="password" />
        </div>
        <div>
          <label class="field-label">Embedding API Key</label>
          <input v-model="form.EMBEDDING_API_KEY" class="input" type="password" />
        </div>
        <div>
          <label class="field-label">Chunk Size</label>
          <input v-model="form.CHUNK_SIZE" class="input" type="number" />
        </div>
        <div>
          <label class="field-label">Chunk Overlap</label>
          <input v-model="form.CHUNK_OVERLAP" class="input" type="number" />
        </div>
        <div>
          <label class="field-label">Top K</label>
          <input v-model="form.TOP_K" class="input" type="number" />
        </div>
        <div>
          <label class="field-label">Max History Turns</label>
          <input v-model="form.MAX_HISTORY_TURNS" class="input" type="number" />
        </div>
        <div>
          <label class="field-label">Collection Name</label>
          <input v-model="form.CHROMA_COLLECTION_NAME" class="input" type="text" />
        </div>
        <div>
          <label class="field-label">Log Level</label>
          <select v-model="form.LOG_LEVEL" class="input">
            <option value="DEBUG">DEBUG</option>
            <option value="INFO">INFO</option>
            <option value="WARNING">WARNING</option>
            <option value="ERROR">ERROR</option>
          </select>
        </div>
      </div>

      <div class="button-row">
        <button class="button button-primary" :disabled="busy" @click="saveSettings">
          {{ busy ? "保存中..." : "保存到 .env" }}
        </button>
      </div>
      <p v-if="message" class="feedback success-text">{{ message }}</p>
    </PanelCard>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from "vue";
import PanelCard from "../components/PanelCard.vue";
import { getSettings, updateSettings } from "../api/client";

const form = reactive({});
const message = ref("");
const busy = ref(false);

async function loadSettings() {
  const data = await getSettings();
  Object.assign(form, {
    LLM_PROVIDER: data.llm_provider,
    EMBEDDING_PROVIDER: data.embedding_provider,
    LLM_MODEL: data.llm_model,
    EMBEDDING_MODEL: data.embedding_model,
    LLM_API_BASE: data.llm_api_base,
    EMBEDDING_API_BASE: data.embedding_api_base,
    LLM_API_KEY: "",
    EMBEDDING_API_KEY: "",
    CHUNK_SIZE: data.chunk_size,
    CHUNK_OVERLAP: data.chunk_overlap,
    TOP_K: data.top_k,
    MAX_HISTORY_TURNS: data.max_history_turns,
    CHROMA_COLLECTION_NAME: data.collection_name,
    LOG_LEVEL: data.log_level,
  });
}

async function saveSettings() {
  busy.value = true;
  message.value = "";
  try {
    const payload = { ...form };
    if (!payload.LLM_API_KEY) {
      delete payload.LLM_API_KEY;
    }
    if (!payload.EMBEDDING_API_KEY) {
      delete payload.EMBEDDING_API_KEY;
    }
    await updateSettings(payload);
    message.value = "配置已写入 .env，建议重启后端服务。";
  } catch (error) {
    message.value = String(error.message || error);
  } finally {
    busy.value = false;
  }
}

onMounted(loadSettings);
</script>
