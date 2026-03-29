# Aurora

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.118+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-18-149ECA?logo=react&logoColor=white)](https://react.dev/)
[![Vite](https://img.shields.io/badge/Vite-7-646CFF?logo=vite&logoColor=white)](https://vite.dev/)
[![Chroma](https://img.shields.io/badge/Chroma-VectorDB-16A34A)](https://www.trychroma.com/)

Aurora 是一个面向软件测试场景的本地知识工作台，把文档管理、知识库重建、RAG 问答、知识图谱、日志检索和配置中心整合到一个控制台里。

它适合测试团队把常见文档、排障经验、ADB 命令、Linux 命令、Web / 移动端测试经验、接口测试和性能测试资料沉淀成一个可检索、可追问、可持续维护的内部知识库。

当前版本：`v0.7.0`

---

## 📚 目录导航

- [✨ 项目简介](#-项目简介)
- [🚀 核心特性](#-核心特性)
- [🖼️ 界面预览](#️-界面预览)
- [🎯 适用场景](#-适用场景)
- [🧭 推荐工作流](#-推荐工作流)
- [🧪 本地演示模式](#-本地演示模式)
- [🤖 当前支持的模型接入方式](#-当前支持的模型接入方式)
- [🧱 技术栈](#-技术栈)
- [⚡ 快速开始](#-快速开始)
- [🔧 配置说明](#-配置说明)
- [🗂️ 项目结构](#️-项目结构)
- [🖥️ 当前页面工作区](#️-当前页面工作区)
- [✅ 测试与构建](#-测试与构建)
- [📌 当前状态](#-当前状态)
- [🛣️ 版本路线图](#️-版本路线图)
- [🔭 后续优化方向](#-后续优化方向)

---

## ✨ 项目简介

Aurora 不是单纯的聊天界面，也不是单纯的文件管理工具，而是一套围绕“知识资料沉淀 -> 索引构建 -> 问答验证 -> 图谱浏览 -> 日志排查”闭环设计的本地工作台。

你可以把它理解成：

- 测试团队内部知识库控制台
- RAG 问答效果验证平台
- 模型联调与知识库调试工作台
- 知识图谱和日志辅助排查入口

---

## 🚀 核心特性

| 模块 | 能力 | 当前状态 |
| --- | --- | --- |
| 📄 文档管理 | 上传、预览、重命名、删除、主题标签维护、批量操作 | 已完成 |
| 🧠 知识库构建 | 一键重建、索引状态查看、切片统计、失败文档统计 | 已完成 |
| 💬 RAG 问答 | 多会话、流式回答、引用来源、耗时展示、本地演示模式问答 | 已完成 |
| 🕸️ 知识图谱 | 按主题、文件类型、文档生成轻量图谱并浏览 | 已完成 |
| ⚙️ 设置与联调 | `.env` 保存、多厂商预设、连通性测试、运行时覆盖 | 已完成 |
| 📜 日志排查 | 日志筛选、日志概况、固定高度滚动查看、清空日志 | 已完成 |

---

## 🖼️ 界面预览

| 页面                | 建议文件名                                                   | 当前状态 |
| ------------------- | ------------------------------------------------------------ | -------- |
| 总览 / 主控制台     | ![总览 / 主控制台](./images/README/overview_dashboard.png)   | ✅        |
| 知识库 / 控制台视图 | ![知识库 / 控制台视图](./images/README/knowledge_base_view.png) | ✅        |
| 对话 / RAG 问答     | ![对话 / RAG 问答](./images/README/chat-workbench.png)       | ✅        |
| 图谱 / 关系视图     | ![图谱 / 关系视图](./images/README/knowledge_graph_view.png) | ✅        |
| 日志 / 设置页面     | ![日志 / 设置页面](./images/README/logs_settings_page.png)   | ✅        |

---

## 🎯 适用场景

| 场景 | 适合做什么 | 对应页面 |
| --- | --- | --- |
| 团队知识沉淀 | 把测试规范、排障手册、命令集合和经验文档沉淀到知识库 | 知识库 |
| RAG 联调 | 验证切片、检索、引用和回答链路是否有效 | 知识库 / 对话 / 日志 |
| 问答验收 | 用真实测试资料验证回答质量与引用可信度 | 对话 |
| 图谱辅助理解 | 看知识覆盖范围、主题聚类和资料结构关系 | 图谱 |
| 日志排查 | 排查建库、问答、模型调用、配置异常 | 日志 |

---

## 🧭 推荐工作流

1. 准备资料

把测试资料放入 `data/` 目录，或者在“知识库”页面直接上传。

2. 配置模型

长期配置放在“设置”页保存到 `.env`；临时联调使用运行时请求头覆盖。

3. 重建知识库

点击“开始重建”，系统会扫描文档、切片并写入向量索引。

4. 进入对话验证

在“对话”页提问，观察回答、引用来源和耗时是否符合预期。

5. 查看图谱与日志

在“图谱”页检查知识结构，在“日志”页排查建库或问答异常。

---

## 🧪 本地演示模式

当未配置完整的 LLM / Embedding 密钥时，Aurora 会进入“本地演示模式”。

此模式下仍可完成：

- 文档上传、预览、重命名、删除和元数据维护
- 知识库重建与本地索引更新
- 本地抽取式问答
- 知识图谱浏览
- 设置页配置维护与连通性测试
- 日志查询与排查

适合用于：

- 本地试用
- 前后端联调
- 功能验收
- 演示流程走查

---

## 🤖 当前支持的模型接入方式

| 类别 | 当前支持 | 说明 |
| --- | --- | --- |
| 后端接入模式 | `openai` / OpenAI Compatible | 当前主要通过 OpenAI 及兼容接口工作 |
| 前端厂商预设 | `openai`、`openai_compatible`、`deepseek`、`qwen`、`zhipu`、`moonshot`、`siliconflow`、`openrouter` | 便于快速填充提供方、模型名和 API Base |
| 运行时覆盖 | 支持 | 仅对当前请求生效，不写入 `.env` |

补充说明：

- 除 `openai` 外，大部分厂商当前都通过 OpenAI Compatible 方式接入
- 预设是为了提升联调效率，不代表所有厂商都已做独立后端适配

---

## 🧱 技术栈

| 层级 | 技术 |
| --- | --- |
| 后端 | FastAPI、Uvicorn、LlamaIndex、Chroma、OpenAI SDK、python-dotenv |
| 前端 | React 18、Vite 7、Vitest、原生 CSS |
| 运行环境 | Python 3.11+、Node.js 20+、npm 10+ |

---

## ⚡ 快速开始

### 环境要求

| 项目 | 要求 |
| --- | --- |
| Python | 3.11+ |
| Node.js | 20+ |
| npm | 10+ |

### 一键启动

| 系统 | 命令 |
| --- | --- |
| Windows | `.\start.ps1` |
| Linux / macOS | `chmod +x start.sh && ./start.sh` |

启动脚本会自动完成：

- 创建 `.venv`
- 创建 `.env`
- 安装后端依赖
- 安装前端依赖
- 构建前端
- 启动 FastAPI 服务

默认访问地址：

| 地址 | 说明 |
| --- | --- |
| `http://127.0.0.1:8000` | 应用首页 |
| `http://127.0.0.1:8000/health` | 健康检查 |

### 手动安装

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt

cd frontend
npm install
cd ..
```

### 手动启动后端

```powershell
.\.venv\Scripts\python.exe api_server.py
```

### 手动启动前端开发模式

```powershell
cd frontend
npm run dev
```

---

## 🔧 配置说明

项目首次启动时会自动创建 `.env`。

常见配置包括：

| 配置项 | 说明 |
| --- | --- |
| `LLM_PROVIDER` | 聊天模型提供方 |
| `EMBEDDING_PROVIDER` | 向量模型提供方 |
| `LLM_MODEL` | 聊天模型名称 |
| `EMBEDDING_MODEL` | 向量模型名称 |
| `LLM_API_BASE` | 聊天模型接口地址 |
| `EMBEDDING_API_BASE` | 向量模型接口地址 |
| `LLM_API_KEY` | 聊天模型密钥 |
| `EMBEDDING_API_KEY` | 向量模型密钥 |
| `CHUNK_SIZE` | 切片大小 |
| `CHUNK_OVERLAP` | 切片重叠长度 |
| `TOP_K` | 检索召回数量 |
| `MAX_HISTORY_TURNS` | 最大上下文轮数 |
| `LOG_LEVEL` | 日志级别 |
| `API_HOST` / `API_PORT` | 服务监听地址和端口 |

推荐做法：

- 长期固定配置放 `.env`
- 临时切换 Key / Base 用前端运行时请求头覆盖

---

## 🗂️ 项目结构

```text
Aurora/
├─ app/
│  ├─ api/
│  ├─ services/
│  ├─ config.py
│  ├─ llm.py
│  ├─ logging_config.py
│  ├─ schemas.py
│  └─ server.py
├─ data/
├─ db/
├─ logs/
├─ frontend/
│  ├─ src/
│  │  ├─ App.jsx
│  │  ├─ api.js
│  │  ├─ styles.css
│  │  └─ lib/
│  └─ package.json
├─ tests/
├─ api_server.py
├─ start.ps1
├─ start.sh
├─ requirements.txt
└─ README.md
```

---

## 🖥️ 当前页面工作区

| 页面 | 用途 |
| --- | --- |
| 总览 | 查看系统状态、资料规模和近期资产 |
| 知识库 | 管理文档、维护元数据、执行重建 |
| 对话 | 进行多会话问答与引用验证 |
| 图谱 | 查看知识结构与关键节点 |
| 设置 | 维护模型与运行参数 |
| 日志 | 筛选、查看和清空日志 |

---

## ✅ 测试与构建

### 后端测试

```powershell
python -m unittest discover -s tests -v
```

### 前端测试

```powershell
cd frontend
npm test -- --run
```

### 前端构建

```powershell
cd frontend
npm run build
```

---

## 📌 当前状态

当前仓库已经完成 P0 收尾，核心状态如下：

| 能力 | 状态 |
| --- | --- |
| 可启动 | 已完成 |
| 可建库 | 已完成 |
| 可问答 | 已完成 |
| 可浏览图谱 | 已完成 |
| 可维护设置 | 已完成 |
| 可查看日志 | 已完成 |

详细验收可见：

- [P0_ACCEPTANCE_REPORT.md](./P0_ACCEPTANCE_REPORT.md)

后续待办可见：

- [UNFINISHED_BACKLOG.md](./UNFINISHED_BACKLOG.md)

安全待处理项可见：

- [SECURITY_PENDING.md](./SECURITY_PENDING.md)

项目上下文总结可见：

- [PROJECT_CONTEXT_SUMMARY_2026-03-29.md](./PROJECT_CONTEXT_SUMMARY_2026-03-29.md)

---

## 🛣️ 版本路线图

| 阶段 | 状态 | 说明 |
| --- | --- | --- |
| P0 | 已完成 | 可启动、可建库、可问答、可看图谱、可配设置、可查日志 |
| P1 | 进行中 | 前端拆分、集成测试补齐、任务体系增强、体验继续精修 |
| P2 | 待推进 | 本地演示模式产品化、多模型扩展、图谱与日志产品化升级 |

---

## 🔭 后续优化方向

| 方向 | 说明 |
| --- | --- |
| 前端结构拆分 | 继续拆分 `App.jsx`，降低维护成本 |
| 集成测试补齐 | 增加 API 级和页面级回归验证 |
| 任务体系增强 | 完善知识库重建任务持久化与恢复 |
| 体验优化 | 继续压缩信息密度，优化首屏和日志页 |
| 演示模式产品化 | 明确本地演示模式与正式模式边界 |
| 模型扩展 | 继续扩展更多 provider 接入方式 |

---

## License

当前仓库未单独声明 License；如需开源发布，建议补充明确许可证文件。
