# Aurora 第五特性：Memory Retrievability 技术路线

## 1. 第五特性在 Aurora 业务中的定义

Aurora 的第五特性不是“把更多 active memory 塞进回答”，而是把 memory retrieval 从“数据库可读”升级成“业务上值得进入回答链路”。

- `Readable`
  通过 `allowed_scopes + status=active + 当前有效主版本` 过滤后，memory 才能成为候选。
- `Retrievable`
  候选 memory 在当前 `scene + user_query` 下足够相关，值得进入排序。
- `Injectable`
  memory 在排序后仍然足够有价值，才会进入最终 `memory_context`。

Aurora 的多阶段检索链路固定为：

1. 作用域过滤
2. 一致性过滤
3. 场景相关性筛选
4. 排序
5. Top-K 注入

这条边界同时保证：

- memory retrieval 不等于 memory 全量读取
- memory 与 knowledge retrieval 保持两段式解耦
- memory 只是回答增强，不是默认主来源
- prompt 注入量必须严格受控

## 2. MemoryQuery / MemoryCandidate / MemoryRetrievalResult / MemoryRetrievalBundle 定义

代码位置：

- `app/services/memory_retrieval_models.py`

第一版内部契约如下：

- `MemoryQuery`
  包含 `tenant_id / user_id / project_id / session_id / scene / user_query / allowed_scopes / top_k / retrieval_mode / retrieval_metadata`
- `MemoryCandidate`
  表示通过 scope + consistency + active 过滤后的候选项，包含 `memory_fact_id / scope_type / type / content / source_session_id / updated_at / source_confidence`
- `MemoryRetrievalResult`
  表示进入排序阶段后的结果，包含 `retrieval_score / matched_reason / selected_for_injection / score_breakdown`
- `MemoryRetrievalBundle`
  表示上层真正消费的结果包，包含 `selected_memories / dropped_candidates / total_candidates / total_selected / retrieval_trace / memory_context`

上层 `BusinessRequest` 不直接依赖 repository 原始结果，而是消费 `memory_context`。

## 3. RetrievalPlanner 设计与代码

代码位置：

- `app/services/memory_retrieval_planner.py`
- `app/services/memory_scene_policy.py`

职责：

- 统一解析 scene
- 基于 `scene + query + allowed_scopes` 生成 retrieval plan
- 控制 `top_k / candidate_limit / per_scope_candidate_limit / retrieval_mode`
- 输出 explainable plan，供 trace 和 internal preview 复用

第一版 planner 规则：

- `troubleshooting / onboarding` 默认更积极启用 memory retrieval
- `qa_query / command_lookup` 默认更保守，memory 只作为少量增强
- 当 query 含有 `current / session / project / 当前 / 我们 / 上下文` 之类上下文信号时，会提升 memory retrieval 的启用理由
- planner 还会给注入阶段下发 `max_injection_chars_per_memory`，限制单条 memory 注入大小

## 4. MemoryCandidateSelector 设计与代码

代码位置：

- `app/services/memory_candidate_selector.py`

职责：

- 只做 `allowed_scopes + current_only + active` 候选收集
- 不做最终排序
- 不把 memory retrieval 混进 knowledge retrieval

实现要点：

- 按 `allowed_scopes` 逐 scope 查询，避免大范围扫描
- 依赖既有索引：
  - `idx_memory_facts_scope_status`
  - `idx_memory_facts_identity_current`
  - `idx_memory_facts_consistency_group`
- 使用 `candidate_limit + per_scope_candidate_limit` 控制候选规模

## 5. ScenePolicy / ScopeWeightPolicy 设计与代码

代码位置：

- `app/services/memory_scene_policy.py`

默认 scope 优先级仍然是：

- `session > user > project > team > global`

但 Aurora 不再把它硬编码成绝对规则，而是抽成可覆盖的权重策略：

- `qa_query`
  - type：`fact > decision > pending_issue > preference`
- `troubleshooting`
  - type：`pending_issue > fact > decision > preference`
  - scope：允许 `project` 高于 `user`
- `onboarding`
  - type：`decision > fact > preference > pending_issue`
  - scope：允许 `project / team` 高于 `session`
- `command_lookup`
  - type：`fact > decision > pending_issue > preference`
  - 低相关 preference 会被直接过滤

## 6. MemoryRelevanceScorer / MemoryRanker 设计与代码

代码位置：

- `app/services/memory_relevance_scorer.py`
- `app/services/memory_ranker.py`
- `app/services/consistent_memory_retriever.py`

### 6.1 MemoryRelevanceScorer

第一版 relevance 使用轻量规则：

- query/content 词法重叠
- exact phrase 命中
- `fact_key / subject_key` 命中
- 当前会话、当前状态、我们正在讨论什么 这类 query 的 contextual boost

现在同时支持中英文上下文 cue，避免中文场景下检索弱化。

为了后续扩展，新增了 `MemoryRelevanceScorerPort` 和 `CompositeMemoryRelevanceScorer`：

- lexical scorer 可以继续沿用
- semantic scorer 未来可以按同一接口接入
- hybrid retrieval 可以通过组合 scorer 渐进落地

### 6.2 一致性折叠

`ConsistentMemoryRetriever.collapse_candidates(...)` 会把同一 `subject_key + fact_key` 的跨 scope 重复候选折叠成一个代表项。

代表项不再永远偏向 session，而是由 scene-aware scope weights、source confidence、version、updated_at 共同决定。

### 6.3 MemoryRanker

排序公式：

```text
retrieval_score =
  relevance * 0.40 +
  scope_priority * 0.20 +
  recency * 0.15 +
  type_priority * 0.15 +
  source_confidence * 0.10
```

排序后继续做两层约束：

- `min_relevance_score / min_injection_score`
- `per_scope_top_k + total top_k`

未入选的候选会进入 `dropped_candidates`，至少记录：

- 同 identity 被更优结果遮蔽
- scene type 过滤
- relevance 不足
- 注入阈值不足
- per-scope cap / total top-k cap

此外 ranker 的 score weights 已可注入，便于未来 learned ranking、feedback-based ranking 或 forgetting-aware ranking 做增量调参。

## 7. MemoryInjectionBuilder 设计与代码

代码位置：

- `app/services/memory_injection_builder.py`

职责：

- 把 `MemoryRetrievalResult` 转成 `MemoryContextItem`
- 保持 provider 无关
- 严格控制 memory 注入体积

第一版新增的注入控制：

- 每条 memory 按 scene 使用 `max_injection_chars_per_memory` 截断
- `memory_context` 仍保留 `retrieval_score / matched_reason`，方便内部预览和调试

## 8. 如何改造现有读取链路

现有 public chat 链路已经改造成：

1. `ScopeResolver` 输出 `allowed_scopes`
2. `RetrievalPlanner` 生成 retrieval plan
3. `MemoryCandidateSelector` 收集候选
4. `ConsistentMemoryRetriever` 做一致性折叠
5. `MemoryRelevanceScorer` 打 relevance 分
6. `MemoryRanker` 生成 Top-K 和 dropped_candidates
7. `MemoryInjectionBuilder` 生成 `memory_context`
8. 再进入现有 knowledge retrieval
9. 再组装 `BusinessRequest`
10. provider 生成

涉及代码：

- `app/services/memory_retriever.py`
- `app/api/chat.py`
- `app/services/rag_service.py`
- `app/api/routes/providers.py`

关键行为：

- `BusinessRequest` 优先消费 `memory_context`
- memory retrieval fail-open，不阻塞 knowledge retrieval 主链路
- legacy `retrieve()` 保留，继续服务旧链路和内部工具

## 9. 最小测试用例

第一版最小测试覆盖包括：

- `tests/test_services.py`
  - `test_troubleshooting_retrieval_prefers_project_pending_issue_over_user_preference`
  - `test_command_lookup_can_return_empty_bundle_when_only_irrelevant_preference_exists`
  - `test_onboarding_scene_can_prefer_project_decision_over_session_temporary_override`
  - `test_retrieval_planner_recognizes_chinese_contextual_cues`
  - `test_memory_relevance_scorer_adds_contextual_boost_for_chinese_query`
  - `test_memory_injection_builder_caps_content_length_in_bundle`
- `tests/test_api_routes.py`
  - `test_internal_memory_retrieval_preview_api_returns_bundle_and_trace`
  - `test_features_one_two_three_coexist_without_cross_boundary_side_effects`

本地验证命令：

```powershell
& .\.venv\Scripts\python.exe -m unittest tests.test_services.MemoryIsolationTests tests.test_api_routes.ApiRouteTests tests.test_provider_independence
```

## 10. 第五特性验收 Checklist

- [x] memory 检索不等于 memory 全量读取
- [x] 默认只从 `allowed_scopes + active + 当前有效主版本` 中取候选
- [x] 不同 `scene` 的召回策略不同
- [x] `session / user / project / team / global` 的优先级行为清晰
- [x] Top-K 很小且可控
- [x] 单条 memory 注入长度受控
- [x] 结果能解释为什么选中、为什么丢弃
- [x] memory retrieval 失败时不阻塞 knowledge retrieval 主链路
- [x] memory 与 knowledge retrieval 保持两段式
- [x] 为 semantic / hybrid / learned ranking / forgetting-aware ranking 预留清晰扩展点

## 是否需要做成内部 API

结论：

- 核心 retrieval 能力不应该暴露成 public API，它应当是 Aurora 内部服务层能力
- 但需要 internal preview API 来支持调试、灰度验证和质量分析

当前保留的内部入口：

- `POST /api/v1/internal/memory/retrieve`

它用于查看：

- 当前 scene 的 retrieval plan
- selected memories
- dropped candidates
- retrieval trace
- 最终注入的 `memory_context`

这样第五特性的调优、验收和回归测试都留在内部边界内，不污染 public chat contract。
