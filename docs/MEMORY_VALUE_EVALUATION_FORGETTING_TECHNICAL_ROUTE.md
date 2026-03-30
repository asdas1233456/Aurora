# Aurora 第七特性：Value Evaluation + Forgetting 技术路线与实现原理

## 1. 第七特性在 Aurora 业务中的定义

Aurora 的第七特性不是“让系统记住更多东西”，而是让系统具备对记忆做价值判断、生命周期治理、主动降噪和可审计遗忘的能力。

这意味着 Aurora 必须明确区分以下概念：

- `Correct`
  记忆当前有效，没有被纠错、替代或冲突治理淘汰。
- `Useful`
  记忆在真实问答里经常能帮助回答问题。
- `Durable`
  即使长时间后，依然值得保留在默认检索主链路中。
- `Temporary`
  短期内很重要，但天然应逐步退出默认主链路。
- `Cooling`
  目前不一定错误，但不再值得默认参与回答。
- `Expired`
  在业务语义上已经失效，不应继续进入默认 retrieval。

Aurora 在这一特性中采用两个核心区分：

- “正确”不直接等于“高价值”
- “遗忘”不直接等于“删除”

因此，第七特性的目标是：

1. 让 `memory_facts` 同时具备正确性治理和价值治理
2. 让默认 retrieval 只消费“当前有效且仍有业务价值”的记忆
3. 让低价值、长期未使用、过期记忆退出默认主链路
4. 让高价值项目事实、关键决策、稳定偏好更持久
5. 保留完整审计与历史追溯能力

## 2. 设计原则

第七特性的实现遵循以下原则：

### 2.1 不绕过前六特性

Retention 不是新的“总开关”，它必须叠加在既有治理链路之上：

1. `scope` 决定是否可读
2. `consistency` 决定是否为当前有效版本
3. `correction-aware` 决定是否应被替代或冲突隔离
4. `retention-aware` 决定是否仍值得进入默认主链路

因此 retention 过滤不能替代 consistency，也不能绕过 correction。

### 2.2 遗忘优先是退出主链路，不是物理删除

Aurora 将“遗忘”拆成四层动作：

- `de-prioritize`
  仍可检索，但优先级下降
- `hide_from_default`
  默认不参与主回答，但仍可审计和历史查看
- `expire`
  业务上失效，不再进入默认 retrieval
- `archive`
  从热路径退出，只保留在审计和历史层

`delete` 仍然保留给显式治理动作，不作为默认遗忘策略。

### 2.3 规则优先、可解释、可调参

第一版不引入复杂 ML，而是采用规则驱动评分：

- 评分公式透明
- 每个决策可审计
- 每种策略可独立调参
- 后续可替换为 learned scoring 或 feedback ranking

### 2.4 生命周期计算迁出热路径

默认 retrieval 不在每次查询时重算所有 memory 的价值，而是依赖持久化字段：

- `value_score`
- `retrieval_visibility`
- `forgetting_status`
- `next_evaluation_at`

价值重算与状态迁移通过后台维护或管理命令执行。

## 3. 业务语义建模

第七特性把记忆分成两层状态：

### 3.1 正确性层

由前六特性 already govern：

- `status`
- `superseded_by`
- `correction_of`
- `consistency_group_id`

这层负责回答：

- 这条记忆是不是当前有效版本
- 这条记忆有没有被纠错或替代
- 这条记忆是否仍允许进入候选集合

### 3.2 价值层

由第七特性新增字段负责：

- `value_score`
- `retention_level`
- `ttl_seconds`
- `expires_at`
- `last_accessed_at`
- `access_count`
- `successful_use_count`
- `decay_factor`
- `archived_at`
- `retrieval_visibility`
- `forgetting_status`
- `next_evaluation_at`
- `retention_policy_id`
- `archive_bucket`

这层负责回答：

- 这条记忆是否值得继续参与默认 retrieval
- 它是在热路径、冷却层、过期层还是归档层
- 它下一次应该什么时候重新评估

## 4. memory_facts 模型扩展

代码位置：

- `app/schemas.py`
- `app/services/storage_service.py`
- `app/services/memory_repository.py`

### 4.1 新增字段语义

- `value_score`
  当前综合价值分，范围为 `0-100`
- `retention_level`
  保留级别，取值：
  - `critical`
  - `high`
  - `normal`
  - `low`
  - `temporary`
- `ttl_seconds`
  生命周期基础 TTL
- `expires_at`
  业务过期时间点
- `last_accessed_at`
  最近一次被真正命中并进入默认链路的时间
- `access_count`
  被检索命中的次数
- `successful_use_count`
  被回答链路实际使用的次数
- `decay_factor`
  衰减速度
- `archived_at`
  归档时间
- `retrieval_visibility`
  默认检索可见性：
  - `normal`
  - `deprioritized`
  - `hidden_from_default`
  - `archive_only`
- `forgetting_status`
  遗忘流程状态：
  - `none`
  - `cooling`
  - `expired`
  - `archived`
- `next_evaluation_at`
  下一次生命周期评估时间
- `retention_policy_id`
  命中的保留策略标识
- `archive_bucket`
  为未来 archive storage 预留的桶位字段

### 4.2 存储层设计

SQLite 层新增了：

- `memory_facts` 新字段
- `idx_memory_facts_visibility`
  让 `retrieval_visibility + forgetting_status + value_score` 快速参与过滤
- `idx_memory_facts_next_evaluation`
  支撑周期性维护扫描
- `memory_retention_audit`
  记录 retention 决策、分值和原因

这保证了第七特性是“可治理状态”而不是“隐式规则”。

## 5. 价值评估模型

代码位置：

- `app/services/memory_value_evaluator.py`
- `app/services/retention_policy.py`

### 5.1 评分目标

`MemoryValueEvaluator` 不是判断真伪，而是判断“是否仍值得留在默认主链路”。

它综合以下因素：

- `scope_value`
- `type_value`
- `recency_value`
- `usage_value`
- `source_value`
- `correction_penalty`
- `expiration_penalty`

### 5.2 第一版评分公式

```text
positive_score =
  scope_value * 0.20 +
  type_value * 0.20 +
  recency_value * 0.15 +
  usage_value * 0.20 +
  source_value * 0.15

penalty_score =
  correction_penalty * 0.10 +
  expiration_penalty * 0.10

value_score = normalize(positive_score - penalty_score) * 100
```

该模型的重点不是“数学最优”，而是：

- 透明
- 稳定
- 易调参
- 可在 audit 中解释

### 5.3 各因子含义

#### scope_value

不同 scope 的默认价值不同：

- `session`
  短期高，长期低
- `user`
  中等，偏稳定
- `project`
  高价值主战场
- `team/global`
  可长期保留，但变更需谨慎

#### type_value

不同类型的默认价值不同：

- `fact`
  一般较高
- `decision`
  较高，但可能受时效影响
- `preference`
  中等，取决于稳定性
- `pending_issue`
  短期重要，但更容易过期

#### recency_value

越近期被访问、确认或实际使用的记忆，价值越高。

#### usage_value

通过 `access_count + successful_use_count` 建模：

- 反复被召回的记忆更热
- 真正被回答使用的记忆比仅进入候选更有价值

#### source_value

来源越可靠，价值上限越高：

- `user_confirmed > imported > system_generated > model_inferred`

#### correction_penalty

以下状态会明显降权：

- 被纠错
- 被 supersede
- `conflict_pending_review`
- `stale`

#### expiration_penalty

以下情况会受到强惩罚：

- TTL 已到期
- `pending_issue` 已不再 `active`

## 6. RetentionPolicy 的作用

`RetentionPolicy` 负责给不同 `scope + type` 定义基础生命周期，而不是直接决定最终可见性。

### 6.1 为什么要分离 policy 与 evaluator

如果不分离，系统会把“基础保留策略”和“当前热度评分”混在一起，导致：

- 规则不可解释
- 很难做 per-project override
- 很难做 adaptive TTL

因此 Aurora 采用：

- `RetentionPolicy`
  给出基线 TTL、衰减速度、保留等级
- `MemoryValueEvaluator`
  基于当前状态计算即时价值

### 6.2 第一版最小规则

当前规则已覆盖：

- `session + fact`
  短 TTL，长时间不访问优先 cooling
- `project + fact / decision`
  高价值，TTL 更长，优先保留
- `pending_issue`
  对关闭、长期未访问和过期更敏感
- `team/global + fact / decision`
  具备长期保留倾向，但进入写入链路仍受前置治理保护

## 7. ForgettingPlanner 的职责

代码位置：

- `app/services/forgetting_planner.py`

`ForgettingPlanner` 的职责不是算分，而是把“价值评估结果”翻译成“生命周期动作”。

它会基于：

- `value_score`
- `retention_level`
- `ttl_seconds / expires_at`
- `last_accessed_at`
- `status / superseded / correction`
- `policy cooling/archive thresholds`

输出：

- `retrieval_visibility`
- `forgetting_status`
- `archived_at`
- `next_evaluation_at`
- `action`
- `reason`

### 7.1 决策层级

#### keep_normal

用于：

- 当前有效
- 仍有业务价值
- 应继续参与默认主链路

#### de-prioritize

用于：

- 记忆仍然正确
- 仍有一定价值
- 但应降低默认 ranking 权重

#### hide_from_default

用于：

- 当前不应进入默认回答
- 但仍需保留用于审计、历史查看、人工回溯

#### expire

用于：

- 业务 TTL 已经失效
- 默认 retrieval 必须停止使用它

#### archive

用于：

- 长期冷却
- 已过期且价值较低
- 非当前版本但仍需保留历史

### 7.2 为什么高价值记忆优先冷却而非直接隐藏

这是 Aurora 的关键业务约束：

- 项目事实和关键决策即使近期没访问，也不应轻易消失
- 它们可以被 `deprioritized`
- 可以进入 `cooling`
- 甚至将来进入 `archive`
- 但不应像一次性 session 临时记忆那样很快消失

## 8. ForgettingExecutor 与审计

代码位置：

- `app/services/forgetting_executor.py`
- `app/services/retention_audit_service.py`

`ForgettingExecutor` 负责：

1. 持久化更新 `memory_facts` 的 retention 状态
2. 避免将 retention 更新误写成内容更新
3. 写入 retention audit

### 8.1 为什么 retention 更新不修改内容版本

Retention 不是事实内容变化。

因此 Aurora 刻意把 retention 更新与 version/update 分离：

- 不改变 `subject_key / fact_key`
- 不改变 current-effective 语义
- 不把生命周期迁移误当作内容变更

### 8.2 retention audit 记录什么

每次初始化、降权、隐藏、过期、归档都会记录：

- action
- reason
- value_score
- retention_level
- retrieval_visibility
- forgetting_status
- policy_id
- score breakdown
- previous state
- next state

这保证：

- 遗忘是可解释的
- 调参是可回溯的
- 后续可以分析 heat map 和 retention effectiveness

## 9. 写入链路如何协同

代码位置：

- `app/services/memory_write_service.py`

当前写入链路顺序是：

1. `scope` 写权限校验
2. `FactIdentityResolver`
3. `ConsistencyChecker`
4. `ConflictResolver`
5. `VersioningService`
6. `MemoryValueEvaluator + RetentionPolicy`
7. 持久化写入 `memory_facts`
8. 写 access audit
9. 写 retention audit

### 9.1 关键原则

Retention 初始化只发生在：

- scope/consistency/correction 决策之后
- memory 即将真正落库之前

这样可以确保：

- retention 不会参与事实真伪裁决
- retention 不会影响版本治理
- retention 只是对“已通过治理的事实”附加生命周期元数据

## 10. 读取链路如何协同

代码位置：

- `app/services/memory_retriever.py`
- `app/services/retention_aware_retriever.py`
- `app/services/memory_ranker.py`

当前 retrieval 主链路是：

1. `ScopeResolver`
2. `MemoryCandidateSelector`
3. `ConsistentMemoryRetriever`
4. `RetentionAwareRetriever`
5. `MemoryRelevanceScorer`
6. `MemoryRanker`
7. `MemoryInjectionBuilder`

### 10.1 retention-aware filtering 的规则

默认情况下：

- `archive_only`
  不返回
- `hidden_from_default`
  不返回
- `forgetting_status=expired`
  不返回
- `deprioritized`
  仍保留，但排序有惩罚

### 10.2 forgetting-aware ranking

`MemoryRanker` 现在额外引入了 `retention_value`：

- `value_score` 越高，越容易保留在前列
- `deprioritized` 会附带 visibility modifier
- 这样 retention 不仅能“过滤”，还可以“降噪”

### 10.3 usage heat 如何回写

当前主链路做了两类热度回写：

- 被 retrieval 选中进入默认链路时：
  - 更新 `last_accessed_at`
  - 累加 `access_count`
- 被回答真正使用时：
  - 累加 `successful_use_count`

这两个指标是后续做 adaptive retention 的基础。

## 11. 生命周期维护入口

代码位置：

- `app/services/lifecycle_maintenance_service.py`
- `app/api/routes/memory.py`

Aurora 不把 retention 计算塞进每次问答，而是提供独立维护入口：

- `LifecycleMaintenanceService.run_due()`
- `POST /api/v1/internal/memory/lifecycle/run`

### 11.1 维护任务做什么

它会按 `next_evaluation_at` 和 `expires_at` 扫描到期 memory，并执行：

1. 重新解析 policy
2. 重算 value score
3. 规划 forgetting action
4. 执行状态迁移
5. 写入 retention audit

### 11.2 为什么使用 next_evaluation_at

这是控制成本的关键：

- 避免每次 retrieval 扫全表
- 避免每次 maintenance 都重算全部 memory
- 让生命周期评估变成“增量、可分批、可后台化”的工作

## 12. 性能与扩展性设计

### 12.1 主链路性能控制

第七特性尽量不拖慢 retrieval：

- retrieval 使用持久化好的 `value_score / retrieval_visibility / forgetting_status`
- 只对少量候选做 retention-aware filtering
- 生命周期重算通过 maintenance service 完成

### 12.2 索引与查询策略

新增索引重点支持：

- 默认主链路 visibility 过滤
- 定期到期扫描
- retention audit 查询

### 12.3 未来扩展点

当前设计已经为以下能力预留接口：

- `adaptive TTL`
  可在 `RetentionPolicy` 上按项目或团队覆盖
- `feedback-based promotion/demotion`
  可复用 `successful_use_count + retention_audit`
- `semantic usefulness score`
  可扩展 `MemoryValueEvaluator`
- `archive storage`
  可基于 `archive_bucket` 和 `archive_only` 做冷热分层
- `per-project retention tuning`
  可通过 `retention_policy_id` 或策略覆盖实现
- `memory heat map`
  可基于 `access_count / successful_use_count / last_accessed_at / retention_audit`

## 13. 实现原理总结

Aurora 第七特性的核心思想可以概括为三句话：

### 13.1 正确不等于值得长期参与默认检索

一条 memory 可以是正确的，但可能只是一次性的、已经冷却的、业务上过期的，因此不应长期污染主回答链路。

### 13.2 遗忘不是删除，而是分层退出主链路

Aurora 默认采用：

- 降权
- 隐藏
- 过期
- 归档

而不是直接物理删除。

### 13.3 生命周期治理必须独立于事实治理

事实治理回答“这条 memory 是否正确”。

生命周期治理回答“这条 memory 是否还值得继续进入默认主链路”。

两者都重要，但职责必须拆开。

## 14. 当前实现对应模块

已落地的主要模块如下：

- `app/services/retention_policy.py`
- `app/services/memory_value_evaluator.py`
- `app/services/forgetting_planner.py`
- `app/services/forgetting_executor.py`
- `app/services/retention_aware_retriever.py`
- `app/services/lifecycle_maintenance_service.py`
- `app/services/retention_audit_service.py`
- `app/services/memory_repository.py`
- `app/services/memory_write_service.py`
- `app/services/memory_retriever.py`

## 15. 验收 Checklist

- [x] memory 默认只保留“当前有效且仍有业务价值”的对象参与主链路
- [x] 低价值、长期未使用、过期记忆能退出默认检索
- [x] 高价值项目事实和关键决策不轻易被移出主链路
- [x] 遗忘不等于删除，历史和审计仍可追溯
- [x] retention-aware retrieval 与前六特性兼容
- [x] 生命周期计算不必在每次 retrieval 中全量重算
- [x] 后续可扩展到 adaptive TTL、archive、feedback learning 和 forgetting-aware ranking
