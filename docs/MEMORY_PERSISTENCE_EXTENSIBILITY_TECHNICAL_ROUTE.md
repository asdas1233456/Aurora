# Aurora Memory Persistence & Extensibility Technical Route

## 1. 文档目标

本文档用于说明 Aurora 记忆系统第三特性 `业务可持续型 持久化 + 可扩展性` 的技术路线、设计原理、实现方法、代码落点与后续演进方向。

第三特性的目标不是让 memory “更聪明”，而是先把 Aurora 的会话、原始消息、提炼记忆、审计信息从轻量运行态升级为：

- 可持久保存
- 服务重启可恢复
- 历史会话可追溯
- 数据量增长后热路径仍可控
- memory 与 knowledge 清晰分层
- 后续能扩展 summary / long-term memory / forgetting / correction / archive

## 2. 为什么第三特性必须独立建设

Feature 1 解决的是 `记忆边界`。

- 谁可以读
- 谁可以写
- 哪些 scope 可见
- 如何避免跨 session / user / project 串线

Feature 2 解决的是 `模型边界`。

- Aurora 先产出自己的业务契约
- provider 只负责适配
- memory / retrieval / knowledge / citations 不跟随某个厂商 SDK 混乱耦合

Feature 3 解决的是 `存储边界`。

- 什么是原始聊天记录
- 什么是提炼后的记忆事实
- 什么是知识库文档证据
- 什么必须进 SQL
- 什么必须留在向量知识层

这三个特性必须分层协作，而不是互相吞并：

- Feature 1 给 Feature 3 提供正确的 memory scope 约束
- Feature 2 保证持久化前后的业务契约不依赖某个 provider
- Feature 3 保证 Feature 1 和 Feature 2 的运行结果可以跨重启恢复并继续增长

## 3. 核心设计原则

### 3.1 原始消息不等于记忆

原始消息是完整会话轨迹，必须保留：

- 用户输入
- assistant 输出
- provider / model
- citations
- 未来用于 summary 的原材料

但它不直接等于 `memory_facts`。

### 3.2 记忆不等于知识库

`memory_facts` 表示 Aurora 提炼后的背景信号，例如：

- 当前 session 正在讨论什么
- 某个用户的偏好
- 某个项目的决策

知识库仍然是文档事实和检索证据：

- Markdown / PDF / txt 文档
- chunk
- 向量检索或本地索引召回结果

二者不能混存，否则会导致：

- citation 失真
- 背景偏好冒充知识证据
- RAG 热路径被 memory 增长拖慢

### 3.3 会话恢复只拿最近窗口

第三特性并不把整个历史会话一次性拼进 prompt。

恢复策略必须遵守：

- 默认只取最近 N 条消息
- retrieval memory 默认 top-k
- knowledge 检索保持独立
- 最后由上层装配 prompt

### 3.4 第三特性必须支持后续归档

现在先用 SQLite 做轻量持久化，但表和仓储设计必须允许后续扩展：

- 热数据：最近会话、最近消息
- 温数据：常用 active memory
- 冷数据：旧消息、旧审计日志、历史归档

## 4. Aurora 的存储分层

Aurora 当前第三特性采用如下分层：

### 4.1 chat_sessions

作用：会话外壳

- 记录会话归属
- 记录会话标题
- 记录当前状态
- 记录最近活跃时间
- 为会话列表、恢复、排序提供基础

### 4.2 chat_messages

作用：原始消息层

- 保存完整 user / assistant / system / tool 消息
- 为会话恢复提供最近上下文
- 为未来 summary / extraction 提供原材料
- 保留 provider / model / citations / metadata

### 4.3 memory_facts

作用：提炼记忆层

- 只存提炼后的结构化 memory
- 按 tenant / scope / user / project 隔离
- 允许 status 演进到 stale / superseded / deleted
- 为后续 correction / forgetting 预留字段和查询模型

### 4.4 knowledge vector store / local index

作用：文档知识层

- 继续服务现有 RAG
- 继续承载 chunk / embedding / local lexical retrieval
- 不与 memory_facts 混存

### 4.5 memory_access_audit

作用：审计与治理层

- 记录 create / read / retrieve / update / delete
- 支持按 request / session / memory_fact 查询
- 为灰度验证、排障、治理提供证据

## 5. 数据模型与索引

### 5.1 chat_sessions

代码落点：

- `app/services/storage_service.py`
- `app/services/session_repository.py`
- `app/schemas.py`

最小字段：

- `id`
- `tenant_id`
- `user_id`
- `project_id`
- `title`
- `status`
- `created_at`
- `last_active_at`

关键索引：

- `(tenant_id, user_id, last_active_at DESC)`
- `(tenant_id, project_id, last_active_at DESC)`
- `(user_id, last_active_at DESC)`
- `(project_id, last_active_at DESC)`
- `(last_active_at DESC)`

### 5.2 chat_messages

代码落点：

- `app/services/storage_service.py`
- `app/services/message_repository.py`
- `app/schemas.py`

最小字段：

- `id`
- `tenant_id`
- `session_id`
- `user_id`
- `role`
- `content`
- `provider`
- `model`
- `citations_json`
- `metadata_json`
- `created_at`

关键索引：

- `(tenant_id, session_id, created_at DESC)`
- `(session_id, created_at DESC)`

### 5.3 memory_facts

代码落点：

- `app/services/storage_service.py`
- `app/services/memory_repository.py`

第三特性要求下的关键索引：

- `(tenant_id, scope_type, scope_id, status, updated_at DESC)`
- `(tenant_id, owner_user_id, status, updated_at DESC)`
- `(tenant_id, project_id, status, updated_at DESC)`
- `(tenant_id, source_session_id, status, updated_at DESC)`

### 5.4 memory_access_audit

代码落点：

- `app/services/storage_service.py`
- `app/services/memory_audit_service.py`

关键索引：

- `(tenant_id, request_id, created_at DESC)`
- `(tenant_id, memory_fact_id, created_at DESC)`
- `(tenant_id, session_id, created_at DESC)`

## 6. 核心仓储与服务设计

### 6.1 SessionRepository

代码：

- `app/services/session_repository.py`

职责：

- `ensure_session`
- `get_session`
- `list_sessions`
- `update_last_active`

关键原则：

- 会话壳与原始消息分离
- 同一 `session_id` 在同一 tenant 下不能跨 user / project 复用
- 为恢复和列表查询提供稳定入口

### 6.2 MessageRepository

代码：

- `app/services/message_repository.py`

职责：

- `create_message`
- `list_by_session`
- `list_recent_by_session`
- `count_by_session`
- `count_by_session_ids`
- `get_latest_by_session`

关键原则：

- 原始消息必须独立持久化
- 热路径优先最近窗口，不全量拉历史
- 用 `created_at + rowid` 保障同秒写入场景下的稳定顺序

### 6.3 SessionRecoveryService

代码：

- `app/services/session_recovery_service.py`

职责：

- 恢复 session shell
- 恢复最近消息
- 构造最近聊天上下文
- 为未来 summary 接入保留统一入口

关键实现点：

- 默认只恢复最近 `message_limit` 条
- 构造 chat history 时排除“刚写入的当前 user message”，避免当前问题重复进入上下文

### 6.4 PersistenceHealthService

代码：

- `app/services/persistence_health_service.py`

职责：

- 检查核心表是否存在
- 输出 session / message / memory 计数
- 输出 memory 按 scope 分布

它当前更偏内部运维辅助服务，但已经为后续可视化或诊断接口留好了基础。

## 7. chat 主链路的接入方式

代码入口：

- `app/api/routes/chat.py`
- `app/api/chat.py`

当前主链路流程：

1. 接收 chat 请求
2. 规范化 `request_context`
3. `SessionRepository.ensure_session`
4. `MessageRepository.create_message(role='user')`
5. `SessionRecoveryService.recover_session`
6. `SessionRecoveryService.build_recent_chat_history`
7. `ScopeResolver + MemoryRetriever`
8. 现有 knowledge retrieval
9. `ProviderFactory + CapabilityGuard`
10. `MessageRepository.create_message(role='assistant')`
11. `SessionRepository.update_last_active`

这样做的结果是：

- chat 上下文不再依赖前端把历史全带回
- 服务重启后仍能恢复会话
- memory retrieval 和 knowledge retrieval 仍保持解耦
- assistant 回答和 citations 都有原始落库记录

## 8. 与 Feature 1 的协作关系

Feature 1 的代码核心：

- `app/services/memory_scope.py`
- `app/services/memory_access_policy.py`
- `app/services/memory_retriever.py`
- `app/services/memory_write_service.py`

第三特性没有绕过 Feature 1，而是建立在它之上：

- `chat_messages` 只做原始消息存储，不参与 scope 判断
- `memory_facts` 仍然必须通过 `ScopeResolver`
- memory read / write 仍然必须经过 `MemoryAccessPolicy`
- 审计仍落在 `memory_access_audit`

这保证了 “恢复上下文” 不会变成 “绕开隔离直接读取所有 memory”。

## 9. 与 Feature 2 的协作关系

Feature 2 的代码核心：

- `app/providers/*`
- `app/services/capability_guard.py`
- `app/services/rag_service.py`
- `app/api/routes/providers.py`

第三特性也没有侵入 Feature 2 的 provider 边界：

- provider 面向的是 `BusinessRequest`
- memory / knowledge / conversation context 先在 Aurora 内部组装
- provider dry-run 是只读验证，不写 `chat_sessions`
- provider dry-run 不写 `chat_messages`
- provider dry-run 不依赖会话恢复

这条边界非常重要，因为它保证：

- Feature 2 可以独立验证 provider 行为
- Feature 3 不会把 provider 调试接口变成副作用入口

## 10. 当前内部 API 边界

### 10.1 internal memory API

代码：

- `app/api/routes/memory.py`

用途：

- 手工验证 memory 写入
- 验证 retrieve / read / update / audit 行为

### 10.2 internal provider API

代码：

- `app/api/routes/providers.py`

用途：

- 查看 provider registry
- 解析 provider 归一化结果
- 做 read-only dry-run

### 10.3 internal chat API

代码：

- `app/api/routes/internal_chat.py`

用途：

- 查看会话列表
- 查看单会话详情
- 做最近消息恢复

这组内部 API 共同支撑 1/2/3 特性的灰度验证和边界检查。

## 11. 为什么当前实现不会拖慢现有 RAG 主链路

第三特性的热路径设计刻意遵循“小窗口”原则：

- 会话恢复只读最近 N 条消息
- memory retrieve 只取 top-k
- knowledge retrieve 继续走原有链路
- 不做“大查询把所有原始消息 + 所有 memory + 所有知识一起拿出”

换句话说，Aurora 现在的 prompt 装配顺序是：

1. 最近原始消息窗口
2. 少量 scope-safe memory
3. 少量知识证据

这种顺序能在数据增长时保持主链路可控。

## 12. 后续扩展方向

第三特性当前还没有实现以下能力，但底座已经为它们预留：

### 12.1 summary

可以在 `SessionRecoveryService` 之上增加：

- 会话摘要表
- 摘要滚动更新任务
- 热窗口 + 摘要混合恢复

### 12.2 long-term memory

可以在 `memory_facts` 之上增加：

- scoring
- importance
- confidence
- source trace

### 12.3 forgetting / correction

当前 `status` 已经支持：

- `active`
- `stale`
- `superseded`
- `deleted`

未来可以在不重构仓储的前提下继续扩展。

### 12.4 archive / cold storage

当前按时间戳和会话维度的设计，允许未来把：

- 旧 `chat_messages`
- 旧 `memory_access_audit`

迁移到归档库或冷存储中。

## 13. 风险与当前约束

第三特性当前是轻量本地实现，仍有明确边界：

- 先使用 SQLite，不引入重型基础设施
- 先做最近窗口恢复，不做全量历史压缩
- 先做结构预留，不提前落地复杂 forgetting 算法
- `chat_messages` 仍然是原始消息，不自动变成 memory
- `knowledge_context` 仍然只能来自知识检索层

## 14. 代码落点总览

- `app/services/storage_service.py`
- `app/services/session_repository.py`
- `app/services/message_repository.py`
- `app/services/session_recovery_service.py`
- `app/services/persistence_health_service.py`
- `app/services/memory_repository.py`
- `app/services/memory_audit_service.py`
- `app/api/chat.py`
- `app/api/routes/chat.py`
- `app/api/routes/internal_chat.py`
- `app/api/routes/providers.py`
- `app/api/routes/memory.py`
- `app/api/internal_utils.py`
- `app/schemas.py`

## 15. 验收结论

Aurora 第三特性当前已经完成以下关键能力：

- 会话壳持久化
- 原始消息持久化
- 服务重启后恢复最近上下文
- memory / knowledge / raw chat 分层存储
- 内部会话列表 / 详情 / 恢复接口
- provider dry-run 与持久化主链路边界隔离
- 为 summary / long-term memory / forgetting / archive 预留扩展基础

第三特性的本质不是“多记一点”，而是“让 Aurora 的记忆系统成为一个可维护、可恢复、可持续增长的后端能力”。
