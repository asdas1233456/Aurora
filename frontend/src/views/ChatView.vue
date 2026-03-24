<template>
  <div class="page-grid">
    <section class="page-heading">
      <p class="eyebrow">Chat</p>
      <h1>基于知识库进行多轮问答</h1>
      <p class="page-desc">现在支持流式输出，回答会像真实产品一样边生成边显示，并在结束后附上引用来源。</p>
    </section>

    <PanelCard title="问答参数" tag="Chat">
      <div class="form-grid three-column">
        <div>
          <label class="field-label">Top K</label>
          <input v-model.number="topK" class="input" type="number" min="1" max="20" />
        </div>
        <div class="button-wrap-bottom">
          <button class="button button-ghost" @click="clearMessages">清空聊天记录</button>
        </div>
        <div class="button-wrap-bottom">
          <span class="muted">当前模式：{{ busy ? "流式生成中" : "等待提问" }}</span>
        </div>
      </div>
    </PanelCard>

    <PanelCard title="对话工作区" tag="Streaming">
      <div v-if="!messages.length" class="chat-welcome">
        <div class="welcome-card">
          <h3>欢迎开始测试知识问答</h3>
          <p>你可以直接输入测试问题，或者先试试下面这些提示。</p>
          <div class="quick-prompt-list">
            <button class="prompt-chip" @click="usePrompt('ADB 怎么查看当前前台 Activity？')">
              ADB 怎么查看当前前台 Activity？
            </button>
            <button class="prompt-chip" @click="usePrompt('Linux 中怎么查看端口占用？')">
              Linux 中怎么查看端口占用？
            </button>
            <button class="prompt-chip" @click="usePrompt('移动端弱网测试应该关注哪些点？')">
              移动端弱网测试应该关注哪些点？
            </button>
          </div>
        </div>
      </div>

      <div ref="chatScrollRef" class="chat-wrap chat-scroll">
        <div v-if="messages.length" class="chat-list">
          <div
            v-for="(message, index) in messages"
            :key="index"
            class="chat-message"
            :class="[message.role, { pending: message.streaming }]"
          >
            <div class="chat-role">
              {{ message.role === "user" ? "你" : "Aurora" }}
              <span v-if="message.streaming" class="streaming-badge">生成中</span>
            </div>
            <div class="chat-content">{{ message.content || "正在思考..." }}</div>

            <div v-if="message.meta?.retrieved_count" class="chat-meta">
              已检索 {{ message.meta.retrieved_count }} 个知识片段
            </div>

            <div v-if="message.citations?.length" class="citation-grid">
              <div v-for="(citation, citationIndex) in message.citations" :key="citationIndex" class="citation-card">
                <strong>{{ citation.file_name }}</strong>
                <p>{{ citation.snippet }}</p>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="composer composer-sticky">
        <textarea
          v-model="question"
          class="textarea"
          rows="4"
          placeholder="请输入你的问题，Enter 发送，Shift + Enter 换行"
          @keydown="handleKeydown"
        ></textarea>
        <div class="button-row">
          <button class="button button-primary" :disabled="busy" @click="sendQuestion">
            {{ busy ? "流式生成中..." : "发送问题" }}
          </button>
        </div>
      </div>
    </PanelCard>
  </div>
</template>

<script setup>
import { nextTick, ref } from "vue";
import { streamQuestion } from "../api/client";
import PanelCard from "../components/PanelCard.vue";

const question = ref("");
const topK = ref(4);
const busy = ref(false);
const messages = ref([]);
const chatScrollRef = ref(null);

function createAssistantMessage() {
  return {
    role: "assistant",
    content: "",
    citations: [],
    meta: null,
    streaming: true,
  };
}

async function sendQuestion() {
  if (!question.value.trim() || busy.value) {
    return;
  }

  const userQuestion = question.value.trim();
  const history = messages.value.map((item) => ({
    role: item.role,
    content: item.content,
  }));

  messages.value.push({ role: "user", content: userQuestion, citations: [], meta: null, streaming: false });
  const assistantMessage = createAssistantMessage();
  messages.value.push(assistantMessage);

  question.value = "";
  busy.value = true;
  await scrollToBottom();

  try {
    await streamQuestion(
      {
        question: userQuestion,
        top_k: topK.value,
        chat_history: history,
      },
      {
        onMeta(event) {
          assistantMessage.meta = { retrieved_count: event.retrieved_count };
        },
        onDelta(event) {
          assistantMessage.content += event.content;
          scrollToBottom();
        },
        onDone(event) {
          assistantMessage.streaming = false;
          assistantMessage.content = event.answer || assistantMessage.content;
          assistantMessage.citations = event.citations || [];
          assistantMessage.meta = { retrieved_count: event.retrieved_count };
          scrollToBottom();
        },
        onError(event) {
          assistantMessage.streaming = false;
          assistantMessage.content = event.message || "流式回答失败。";
          scrollToBottom();
        },
      }
    );
  } catch (error) {
    assistantMessage.streaming = false;
    assistantMessage.content = String(error.message || error);
  } finally {
    busy.value = false;
    await scrollToBottom();
  }
}

function clearMessages() {
  messages.value = [];
}

function usePrompt(value) {
  question.value = value;
}

function handleKeydown(event) {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    sendQuestion();
  }
}

async function scrollToBottom() {
  await nextTick();
  if (chatScrollRef.value) {
    chatScrollRef.value.scrollTop = chatScrollRef.value.scrollHeight;
  }
}
</script>
