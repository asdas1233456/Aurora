# Aurora - 软件测试知识工作台
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.118+-009688)](https://fastapi.tiangolo.com/)
[![Vue](https://img.shields.io/badge/Vue-3-42b883)](https://vuejs.org/)
[![Vite](https://img.shields.io/badge/Vite-7-646cff)](https://vite.dev/)
[![Chroma](https://img.shields.io/badge/Chroma-VectorDB-16A34A)](https://www.trychroma.com/)

一个面向软件测试场景的知识库问答系统，支持文档入库、向量检索、流式问答、Dashboard 工作台、运行时测试 Key 和 REST API。  
[功能特性](#-功能特性) • [快速开始](#-快速开始) • [工作流](#-工作流) • [适用场景](#-适用场景) • [版本迭代](#-版本迭代)

当前版本：`v0.4.1`

---

## ✨ 功能特性

### 核心功能

| 功能模块 | 核心特性 | 状态 |
| --- | --- | --- |
| **文档入库** | 支持 `pdf`、`txt`、`md` 文档读取、上传和解析 | ✅ |
| **向量知识库** | 基于 LlamaIndex + Chroma 完成切分、向量化和召回 | ✅ |
| **知识库重建** | 支持一键重建知识库并刷新索引 | ✅ |
| **多轮问答** | 支持带历史上下文的知识库问答 | ✅ |
| **流式输出** | 聊天页支持边生成边展示 | ✅ |
| **引用来源** | 展示命中文档、来源路径和片段引用 | ✅ |
| **运行时测试 Key** | 前端可临时填写模型 Key 和 API Base 联调 | ✅ |
| **REST API** | 提供文档、建库、问答、日志、配置接口 | ✅ |
| **OpenAI 兼容模型** | 支持 OpenAI API 和 OpenAI Compatible API | ✅ |
| **Agent 路由** | 根据问题类型切换知识库或工具能力 | 🚧 |
| **网页搜索工具** | 为知识库之外的问题补充外部信息 | 🚧 |
| **SQL 查询工具** | 为结构化数据查询提供工具调用能力 | 🚧 |

### 工作台能力

| 页面模块 | 功能说明 | 状态 |
| --- | --- | --- |
| **Dashboard** | 系统状态、文档统计、最近文档、快速入口 | ✅ |
| **知识库管理** | 文档列表、预览、上传、重建知识库 | ✅ |
| **对话页面** | 流式问答、消息气泡、引用来源、多轮会话 | ✅ |
| **配置页面** | 查看和更新 `.env` 配置 | ✅ |
| **日志页面** | 查看最近日志、清空日志 | ✅ |

### 内置知识主题

| 主题 | 内容示例 | 状态 |
| --- | --- | --- |
| **测试网站** | 接口测试站点、模拟站点、练习站点 | ✅ |
| **ADB 命令** | 设备连接、安装、抓日志、Activity 排查 | ✅ |
| **Linux 命令** | 文件、进程、网络、系统排查常用命令 | ✅ |
| **Python 测试经验** | Pytest、接口测试、自动化脚本建议 | ✅ |
| **Java 测试经验** | 单测、接口测试、后端排查思路 | ✅ |
| **手机测试** | Android 测试思路、兼容性与排障 | ✅ |
| **Web 测试** | 功能、兼容、UI、网络、前端排障 | ✅ |
| **性能测试** | 压测、瓶颈分析、性能指标理解 | ✅ |

---

## 🧱 技术栈

### 后端

- **FastAPI** - REST API 框架
- **Uvicorn** - ASGI 服务
- **LlamaIndex** - RAG 编排
- **Chroma** - 向量数据库
- **OpenAI SDK** - 模型接口接入
- **python-dotenv** - 环境变量管理
- **Pydantic** - 数据校验

### 前端

- **Vue 3** - UI 框架
- **Vite** - 构建工具
- **Vue Router** - 路由管理
- **Chart.js** - 图表展示

---

## 🚀 快速开始

### 环境要求

- Python 3.11+
- Node.js 20+
- npm 10+
- 可访问的模型 API

### 安装与启动

#### Windows

```powershell
cd aurora
.\start.ps1
```

#### Linux / macOS

```bash
cd aurora
chmod +x start.sh
./start.sh
```

### 访问地址

| 服务 | 地址 |
| --- | --- |
| 前端页面 | `http://127.0.0.1:8000` |
| API 文档 | `http://127.0.0.1:8000/docs` |
| 健康检查 | `http://127.0.0.1:8000/health` |

### 环境变量示例

先复制环境变量模板：

```powershell
Copy-Item .env.example .env
```

或：

```bash
cp .env.example .env
```

#### 方案一：全部使用 OpenAI

```env
LLM_PROVIDER=openai
EMBEDDING_PROVIDER=openai

LLM_API_KEY=your_openai_key
LLM_MODEL=gpt-4.1-mini

EMBEDDING_API_KEY=your_openai_key
EMBEDDING_MODEL=text-embedding-3-small
```

#### 方案二：聊天模型使用兼容 API，Embedding 使用 OpenAI

```env
LLM_PROVIDER=openai_compatible
LLM_API_KEY=your_llm_key
LLM_API_BASE=https://your-compatible-api.example.com/v1
LLM_MODEL=your-model-name

EMBEDDING_PROVIDER=openai
EMBEDDING_API_KEY=your_openai_key
EMBEDDING_MODEL=text-embedding-3-small
```

---

## 🔄 工作流

```text
准备测试文档
    -> 放入 data/ 或从前端上传
    -> 重建知识库
    -> 文档切分与向量化
    -> Chroma 存储索引
    -> 用户发起提问
    -> 检索相关片段
    -> 调用模型生成回答
    -> 返回答案与引用来源
```

### 推荐使用流程

1. 把测试知识文档放进 `data/` 目录，或通过前端页面上传。
2. 在知识库页面点击“重建知识库”。
3. 在配置页或运行时测试 Key 面板中填写模型配置。
4. 进入对话页提问，查看流式回答和引用来源。
5. 结合 Dashboard 观察系统状态和文档情况。

---

## 🎯 适用场景

- **测试经验沉淀**：把零散文档、命令、FAQ 整理成统一知识库。
- **团队提效**：减少重复问答，加快新人上手和问题排查。
- **测试门户集成**：作为 QA Portal、测试平台或内部工具的 AI 问答入口。
- **演示与 PoC**：适合做知识库问答、RAG、Agent 基础工程演示。
- **后续扩展基础**：为网页搜索、SQL 工具和 Agent 路由提供基础骨架。

---

## 📡 REST API

| 接口 | 方法 | 说明 |
| --- | --- | --- |
| `/health` | `GET` | 健康检查 |
| `/api/v1/system/overview` | `GET` | 系统总览 |
| `/api/v1/documents` | `GET` | 文档列表 |
| `/api/v1/documents/preview` | `GET` | 文档预览 |
| `/api/v1/documents/upload` | `POST` | 上传文档 |
| `/api/v1/knowledge-base/status` | `GET` | 知识库状态 |
| `/api/v1/knowledge-base/rebuild` | `POST` | 重建知识库 |
| `/api/v1/chat/ask` | `POST` | 普通问答 |
| `/api/v1/chat/stream` | `POST` | 流式问答 |
| `/api/v1/logs` | `GET/DELETE` | 查询或清空日志 |
| `/api/v1/settings` | `GET/PUT` | 查看或更新配置 |
| `/api/v1/runtime/config` | `GET` | 查看运行时请求头说明 |

---

## 📁 项目结构

```text
aurora/
├── app/
│   ├── api/
│   ├── services/
│   ├── config.py
│   ├── llm.py
│   ├── logging_config.py
│   ├── schemas.py
│   └── server.py
├── frontend/
│   ├── src/
│   │   ├── api/
│   │   ├── components/
│   │   ├── router/
│   │   ├── views/
│   │   ├── App.vue
│   │   └── main.js
│   ├── index.html
│   ├── package.json
│   └── vite.config.js
├── data/
├── db/
├── logs/
├── api_server.py
├── requirements.txt
├── .env.example
├── start.ps1
├── start.sh
└── README.md
```

---

## 🛠 待优化功能

| 优化项 | 说明 | 优先级 |
| --- | --- | --- |
| 历史会话管理 | 增加会话列表、会话命名、会话持久化 | 高 |
| 文档管理 | 增加删除、批量操作、重命名能力 | 高 |
| 问答体验 | 增加停止生成、重新生成、复制答案 | 中 |
| 配置校验 | 增强字段校验和错误提示 | 中 |
| 日志筛选 | 支持按级别、关键词、时间范围筛选 | 中 |
| 自动化测试 | 增加前后端测试用例 | 高 |
| 安全能力 | 增加登录、权限控制、敏感配置保护 | 高 |

---

## 🗺 后续规划

### 短期规划

- 增加聊天历史会话列表
- 增加文档删除和批量管理
- 增加问答耗时和检索耗时展示
- 增加更完整的空状态和错误状态页

### 中期规划

- 接入 Ollama 或本地模型
- 增加网页搜索工具
- 增加 SQL 查询工具
- 增加 Agent Router
- 增加 Prompt 配置能力

### 长期规划

- 多知识库空间
- 多用户协作
- 审计日志
- 工作流编排
- 从知识库系统演进为测试智能体平台

---

## 📈 版本迭代

| 版本 | 迭代内容 |
| --- | --- |
| `v0.1.0` | 基于 Streamlit 的 MVP，完成基础知识库问答 |
| `v0.2.0` | 后端模块化拆分，加入知识库、日志、配置能力雏形 |
| `v0.3.0` | 增加 Dashboard 思路和 REST API 层，为前后端分离做准备 |
| `v0.4.0` | 前端重构为 Vue 3 + Vite，FastAPI 托管前端，支持流式聊天 |
| `v0.4.1` | 统一命名为 Aurora，清理冗余脚本和历史文档，项目结构进一步收口 |

---

## ❓ FAQ

### 当前默认前端是什么？

当前默认前端是 Vue，Streamlit 已从主项目中移除。

### 页面能打开但问答失败，通常是什么原因？

通常是以下几类问题：

- 没有配置有效的模型 Key
- 没有配置可用的 Embedding 接口
- 还没有重建知识库
- API Base 配置错误

### 前端填写的测试 Key 会写入 `.env` 吗？

默认不会。测试 Key 只作用于当前浏览器会话和当前请求。

### 推荐的启动方式是什么？

推荐直接使用：

```powershell
.\start.ps1
```

### 这个项目现在已经是 Agent 了吗？

当前更准确地说是“知识库问答系统 + AI 工作台”，但已经为网页搜索、SQL 工具和 Agent 路由预留了扩展空间。
