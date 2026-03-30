# Aurora Memory Operability And Security Governance Technical Route

## 1. Feature Positioning

第八特性不是给 Aurora 记忆系统增加新的业务能力，而是把已经存在的 `scope / persistence / consistency / retrieval / correction / retention` 串成一条可治理、可排障、可观测、可审计、可降级的系统链路。

这一特性的业务目标是：

- 记忆链路出了问题，可以快速知道卡在哪一步
- 高风险写入不会轻易进入长期记忆
- 高权限 scope 的写入有更严格边界
- retrieval / correction / retention / provider fallback 有统一审计
- memory 子系统异常不会拖垮 Aurora 主问答链路
- 后续可以平滑扩展到 admin console / policy center / anomaly detection / quota management

这意味着第八特性要解决的，不是“多记一点”，而是“记得更可控”。

---

## 2. Business Definition

### 2.1 Operability

在 Aurora 中，运维性不是单纯的日志打印，而是让系统可以回答这些问题：

- 这次回答到底用了哪些 memory
- 某条 memory 为什么被选中、为什么被丢弃
- retrieval 慢在候选收集、排序、注入还是 provider
- correction 后旧值是否真的退出默认链路
- forgetting / archive 是否真正执行并留下轨迹
- memory 子系统异常时，主链路是否已经安全降级

### 2.2 Security Governance

在 Aurora 中，安全治理也不只是鉴权，而是围绕“什么内容可以进 memory、谁能把它写进更高 scope、失败后如何记录和隔离”构建一套统一规则。

它必须覆盖：

- 访问治理：谁能读 / 写 / 改 / 删
- 内容治理：什么内容必须 block 或 redact
- 来源治理：什么来源不能直接升级为 team/global 长期记忆
- 运行治理：频率异常、检索异常、provider 异常、audit 异常如何处理

---

## 3. Design Principles

第八特性的实现遵循五条原则：

### 3.1 Governance Is A Cross-Cutting Capability

治理不能散落在每个 service 的私有逻辑里，而要有集中入口。  
因此 Aurora 新增了统一的：

- `ObservabilityService`
- `AuditService`
- `AccessGovernancePolicy`
- `SensitiveContentGuard`
- `PromptInjectionGuard`
- `AbuseGuard`
- `DegradationController`
- `GovernanceInspector`

### 3.2 Audit And Main Flow Stay Loosely Coupled

治理必须存在，但不能反过来拖垮问答主链路。  
因此 Aurora 采用：

- audit / metrics / trace 尽量 best-effort
- side effect 失败不直接让主回答失败
- memory retrieval 失败可降级为 knowledge-only
- provider fallback 有统一治理记录，但不阻断受控 fallback

### 3.3 High-Risk Scope Needs Stronger Trust

`team / global` 不是普通对话的自然延伸，而是更高等级的共享知识。  
因此：

- 普通 conversation actor 不能直接写 `team/global`
- team/global 写入需要 internal actor 边界
- model inferred / imported / external content 不能直接提升到高价值共享长期记忆

### 3.4 Sensitive Content Defaults To Deny Or Redact

Aurora 的默认安全姿态不是“先写进去以后再清理”，而是：

- 命中 secret / token / prompt injection 模式时先 block
- 命中 PII / internal env 信息时先 redact
- 高风险动作留下 `policy_decisions + security_events`

### 3.5 Future Platform Expansion Starts With Clean Interfaces

第一版不做重平台，但要把扩展口留对。  
因此本次实现优先稳定：

- 数据表
- 审计入口
- 策略入口
- 降级入口
- 内部治理视图入口

---

## 4. Data Model Changes

### 4.1 Enhanced `memory_access_audit`

文件：

- `app/schemas.py`
- `app/services/storage_service.py`
- `app/services/audit_service.py`

增强后的关键字段：

- `request_id`
- `tenant_id`
- `actor_user_id`
- `session_id`
- `memory_fact_id`
- `action`
- `scope_type`
- `retrieval_stage`
- `decision_reason`
- `created_at`

动作集扩展为：

- `create`
- `read`
- `retrieve`
- `inject`
- `update`
- `correct`
- `deprecate`
- `archive`
- `redact`
- `delete`

这里的关键改动是：  
memory 审计不再只覆盖 CRUD，而是覆盖“进入回答链路”和“离开默认链路”。

### 4.2 New `security_events`

用途：记录安全治理事件，而不是普通业务审计。

典型事件：

- `sensitive_memory_detected`
- `unauthorized_scope_write_attempt`
- `suspicious_prompt_injection`
- `abnormal_retrieval_volume`
- `policy_blocked_write`
- `provider_failure_fallback`
- `rate_limit_triggered`

它服务于后续：

- security review queue
- anomaly detection
- SIEM integration

### 4.3 New `policy_decisions`

用途：记录策略模块为什么做出 allow / deny / redact / review / fallback / throttle 判断。

这张表的价值在于解释性：

- 为什么这条 memory 被拒绝
- 为什么 team/global 被拦截
- 为什么 provider 走 fallback
- 为什么触发 rate limit

### 4.4 New `system_metrics_snapshot`

用途：把少量关键指标轻量落盘。  
第一版不引入完整 metrics backend，但已经为：

- dashboard
- governance summary
- 巡检
- future admin console

预留了基础落点。

---

## 5. Core Modules

### 5.1 `ObservabilityService`

文件：

- `app/services/observability_service.py`

职责：

- 打结构化日志
- 维护进程内轻量 metrics
- 在需要时把 metric snapshot 落盘
- 输出 retrieval / retention 相关 trace 摘要

第一版采集点包括：

- 写入计数
- 写入拒绝计数
- 检索候选数
- 检索命中数
- 检索耗时
- per-scope 选中数
- correction / retention 关键计数
- provider latency / error / fallback
- prompt token estimate
- memory context size
- 安全事件相关计数

### 5.2 `AuditService`

文件：

- `app/services/audit_service.py`

职责：

- 统一写 `memory_access_audit`
- 统一写 `policy_decisions`
- 统一写 `security_events`

这样做的目的，是避免各模块自己直接拼 SQL，导致治理逻辑分散、字段风格不统一。

### 5.3 `AccessGovernancePolicy`

文件：

- `app/services/access_governance_policy.py`

职责：

- 在 Feature 1 的 scope isolation 之上补齐高风险操作治理
- 明确哪些 actor 可以操作高权限 scope
- 明确哪些治理动作需要更高权限

第一版规则：

- 普通 conversation actor 不可直接写 `team/global`
- `team/global` 写入必须满足 internal actor 条件
- `delete/redact` 属于更高风险操作
- batch lifecycle / archive 走批量治理入口

### 5.4 `SensitiveContentGuard`

文件：

- `app/services/sensitive_content_guard.py`

职责：

- 在 write path 前扫描内容
- 命中 secret / token / password / bearer / prompt injection 模式时 block
- 命中 email / phone / internal IP 时 redact

这部分当前使用规则和正则实现，原因是：

- 轻量
- 可解释
- 可测试
- 方便以后替换成更完整 policy engine 或检测模型

### 5.5 `PromptInjectionGuard`

文件：

- `app/services/prompt_injection_guard.py`

职责：

- 区分内容来源可信度
- 防止不可信来源直接晋升为高权限长期记忆

第一版规则：

- `knowledge_base_document / external_document / imported` 不能直接晋升到 `team/global`
- `model_inferred / system_generated` 在没有人工 review 时不能直接写高权限 scope

### 5.6 `AbuseGuard`

文件：

- `app/services/abuse_guard.py`

职责：

- 针对高成本动作做基础限流

第一版范围：

- `memory_write`
- `memory_retrieval`
- `memory_correction`
- `memory_lifecycle`

支持粒度：

- per-user
- per-session
- per-tenant

第一版采用进程内 sliding window，原因是 Aurora 当前是本地工作台，优先轻量；后续如果进入多实例或共享部署，再替换成 Redis 即可。

### 5.7 `DegradationController`

文件：

- `app/services/degradation_controller.py`

职责：

- 统一处理治理副作用失败
- 统一处理 provider fallback 记录
- 统一处理 memory retrieval degrade 记录

关键策略：

- audit / policy / security side effect 失败时不阻断主链路
- memory retrieval 失败时可以 fail open 为 knowledge-only
- provider fallback 要留下治理记录

### 5.8 `GovernanceInspector`

文件：

- `app/services/governance_inspector.py`

职责：

- 输出治理状态摘要

第一版摘要包括：

- `hidden_memory_count`
- `archive_only_count`
- `correction_backlog_count`
- `archive_backlog_count`
- recent security events
- recent policy decisions
- top failing policies
- live metrics

---

## 6. Write Path Governance

关键文件：

- `app/services/memory_write_service.py`

Aurora 当前写入链路已经改成：

1. `AbuseGuard`
2. `SensitiveContentGuard`
3. `AccessGovernancePolicy`
4. `PromptInjectionGuard`
5. `ConsistencyChecker / ConflictResolver / VersioningService`
6. `RetentionPolicy / MemoryValueEvaluator`
7. repository persist
8. audit / retention audit / metrics / structured observability

### 6.1 Why This Order

这个顺序是刻意设计的：

- 先做频率控制，避免滥用流量直接打进后续高成本治理链路
- 再做敏感内容和信任来源判断，避免脏数据进入 consistency/versioning
- 然后才做版本治理和 retention 初始化

这保证了 Aurora 不会先把危险内容写进去，再靠补偿逻辑回滚。

### 6.2 Write Outcomes

写入可能有四类结果：

- 正常允许
- block
- redact 后允许
- 因 trust / scope / rate limit 被拒绝

对应会产生：

- `memory_access_audit`
- `policy_decisions`
- `security_events`
- `memory_retention_audit`
- 指标采样

---

## 7. Read Path Governance

关键文件：

- `app/services/memory_retriever.py`
- `app/services/memory_retrieval_trace.py`

Aurora 当前读取链路已经改成：

1. request context 进入 retrieval
2. `AbuseGuard` 先限流
3. planner 输出 retrieval plan
4. candidate selector 收集候选
5. consistency collapse
6. retention-aware filtering
7. relevance scoring + rank
8. memory injection context build
9. selected memories 审计
10. trace / metrics / security event

### 7.1 What Is Observable

现在 Aurora 可以回答：

- 允许访问哪些 scopes
- 一共取了多少候选
- consistency 丢了多少
- retention 丢了多少
- 最终 selected 了哪些 memory
- 每条 selected memory 的 `matched_reason`
- 注入上下文总长度
- 哪一步异常导致 fail-open

### 7.2 Why `inject` Needs Audit

`retrieve` 只表示“进入候选/命中集合”，  
`inject` 才表示“真正进入最终 prompt context”。

这两个动作必须分开，因为：

- 安全排障看的是“用了什么”
- 检索调参看的是“选中过什么”
- 审计链路需要区分“看到”和“实际带入回答”

---

## 8. Retention / Forgetting Governance

关键文件：

- `app/services/lifecycle_maintenance_service.py`
- `app/services/forgetting_executor.py`
- `app/services/retention_audit_service.py`

Aurora 当前已经把 retention 的治理动作纳入统一体系：

- lifecycle maintenance 会先过 batch governance
- forgetting executor 在 archive 时记录 memory action 审计
- retention 变化会落 `memory_retention_audit`
- retention 关键计数会进 metrics

这意味着：

- correction 后的旧值退出默认链路有证据
- hidden / archived / expired 都能追溯
- 后续做 archive backlog 看板时不需要再重做底层数据

---

## 9. Provider And Failure Governance

关键文件：

- `app/services/rag_service.py`
- `app/api/chat.py`
- `app/services/degradation_controller.py`

Aurora 当前对 provider 和 memory 子系统的异常处理策略是：

### 9.1 Memory Retrieval Failure

- `prepare_chat_request` 中 memory retrieval 失败时，降级为空 memory bundle
- 主回答继续走 knowledge retrieval + provider generation
- 同时记录 degrade 事件和结构化日志

### 9.2 Provider Fallback

- 如果 provider config 不可用，`ProviderFactory` 仍可退到 `local_mock`
- `rag_service` 检测到 fallback 后，通过 `DegradationController` 写入：
  - metric
  - `policy_decisions`
  - `security_events`

### 9.3 Side Effect Failure

如果：

- audit 失败
- policy decision 落盘失败
- security event 落盘失败
- metric snapshot 失败

Aurora 会：

- 记录 warning
- 尝试 best-effort degrade
- 不让主问答链路直接失败

这正是“治理不能反过来拖垮业务链路”的设计原则。

---

## 10. Internal API Boundary

关键文件：

- `app/api/routes/memory.py`
- `app/api/routes/providers.py`
- `app/api/routes/internal_chat.py`
- `app/api/internal_utils.py`

第八特性没有把治理入口暴露成公开业务 API，而是继续保持在 internal API 边界后面。

当前策略：

- 仍然要求 `X-Aurora-Internal-Api: true`
- internal governance routes 已设置 `include_in_schema=False`

原因：

- 这些接口主要用于排障、验证、治理和后续 admin tooling
- 它们返回的是 explainable trace、policy decisions、security events、governance summary
- 不适合直接暴露给普通终端用户

第一版新增的内部治理视图接口包括：

- `GET /api/v1/internal/memory/security-events`
- `GET /api/v1/internal/memory/policy-decisions`
- `GET /api/v1/internal/memory/governance/summary`
- `GET /api/v1/internal/memory/metrics/snapshots`

因此，“是不是需要设置成内部 API”的结论是：

- 需要继续作为 internal capability 暴露
- 不需要改成构建期开关
- 不需要并入公开业务 API

---

## 11. Metrics And Audit Mapping

下面是第八特性和实际代码的映射关系：

### 11.1 Write Path

- `memory_create_count`
- `memory_write_rejected_count`
- `sensitive_memory_block_count`
- `scope_upgrade_attempt_count`
- `correction_request_count`

### 11.2 Retrieval Path

- `memory_candidate_count`
- `memory_selected_count`
- `memory_retrieval_latency_ms`
- `memory_injection_count`
- `retrieval_empty_result_count`
- `per_scope_selected_count`

### 11.3 Correction / Retention

- `superseded_memory_count`
- `correction_applied_count`
- `correction_rejected_count`
- `retention_deprioritized_count`
- `retention_archived_count`
- `expired_memory_count`

### 11.4 Provider / Prompt Budget

- `provider_call_latency_ms`
- `provider_error_count`
- `provider_fallback_count`
- `prompt_token_estimate`
- `memory_context_size`

### 11.5 Security Governance

- `unauthorized_access_attempt_count`
- `suspicious_content_detected_count`
- `redaction_applied_count`
- `rate_limit_trigger_count`

---

## 12. Why This Implementation Is Lightweight But Extensible

第八特性第一版刻意没有引入：

- 重型 RBAC 平台
- 复杂的 policy DSL
- 独立 metrics infrastructure
- 独立 SIEM connector
- 独立 security review workflow engine

但它已经把后续扩展需要的四个关键锚点放好了：

### 12.1 Data Anchors

- `security_events`
- `policy_decisions`
- `system_metrics_snapshot`
- enhanced `memory_access_audit`

### 12.2 Service Anchors

- `AuditService`
- `ObservabilityService`
- `AccessGovernancePolicy`
- `DegradationController`

### 12.3 API Anchors

- internal governance summary
- internal policy decision inspection
- internal security event inspection

### 12.4 Extension Directions

未来可以在不破坏当前边界的前提下继续扩展：

- policy center
- anomaly detection
- tenant quota controls
- security review queue
- batch remediation
- compliance export / delete
- SOC / SIEM integration

---

## 13. Validation Strategy

第八特性的最小验收已经通过以下类型测试覆盖：

- 敏感内容阻断
- retrieval rate limit 降级
- governance summary 输出
- internal governance API
- chat memory retrieval fail-open
- 既有 memory write / retrieval / consistency / retention 回归

这保证新增治理能力不是孤立实现，而是实际接入了 Aurora 现有主链路。

---

## 14. Final Summary

第八特性的技术路线可以概括为一句话：

> 在不破坏 Aurora 原有 memory 架构的前提下，把治理能力集中到统一服务和统一数据模型中，再把这些治理点接入 write / retrieve / correction / retention / provider 主链路。

这条路线的核心价值不是“加了更多规则”，而是：

- 问题出现时能看见
- 高风险操作能拦住
- 发生拒绝时能解释
- 子系统异常时能降级
- 未来扩平台时不需要推倒重来

这正是 Aurora 记忆系统从“能工作”走向“可运营、可治理、可扩展”的关键一步。
