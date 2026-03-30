# Aurora 第五特性实现说明：Memory Retrievability

## 1. 文档目的

本文档用于说明 Aurora 第五特性的技术路线和实现原理，重点回答下面几个问题：

- 为什么 Aurora 需要单独设计 memory retrieval，而不是直接读取所有 active memory
- 第五特性和前四个特性的边界是什么
- 当前实现采用了怎样的分层链路
- 每个核心模块分别解决什么问题
- 为什么当前方案既能满足第一版上线，又能为后续 semantic / hybrid / learned ranking 预留扩展空间

这份文档偏实现说明，和 [MEMORY_RETRIEVABILITY_TECHNICAL_ROUTE.md](/C:/Users/ddd/Desktop/Aurora/docs/MEMORY_RETRIEVABILITY_TECHNICAL_ROUTE.md) 的关系是：

- route 文档更偏特性目标、验收项和模块清单
- 本文更偏设计思路、链路原理和当前代码落点

## 2. 问题定义

Aurora 已经具备以下能力：

- scope 隔离
- provider 无关边界
- memory 持久化
- consistency 过滤

但这还不等于“memory 可以直接进入回答链路”。

如果没有第五特性，系统会面临三个典型问题：

1. 可读不等于可用
   数据库能查到的 memory，未必对当前问题有帮助。
2. active 不等于该注入
   所有 active memory 一股脑注入 prompt，会导致噪声上升和 prompt 膨胀。
3. memory 不应抢占知识库主来源地位
   Aurora 的知识证据仍然应该优先来自 knowledge retrieval，memory 只做背景增强。

因此，第五特性的本质是：

> 让 memory 从“可读的数据”变成“按业务场景可控召回、可解释排序、严格限量注入的辅助上下文”。

## 3. Aurora 中“可检索性”的三层含义

### 3.1 Readable

Readable 表示 memory 可以被读取为候选，但还没有资格直接进入 prompt。

必须满足：

- scope 在 `allowed_scopes` 内
- `status = active`
- 通过当前有效主版本过滤

### 3.2 Retrievable

Retrievable 表示 memory 在当前 `scene + user_query` 下足够相关，值得参与排序。

这一步要回答的是：

- 当前业务场景需不需要 memory
- 哪些 memory type 更可能有帮助
- 哪些候选和问题几乎没有关系，应该提前过滤

### 3.3 Injectable

Injectable 表示 memory 在完成排序后仍然足够有价值，值得进入最终 `memory_context`。

这一步要控制的是：

- Top-K 总量
- 每个 scope 的注入上限
- 单条 memory 的内容长度

Aurora 的核心原则是：

- 数据库查到了，不代表应该进回答
- active memory 不是默认全量注入
- memory retrieval 必须是多阶段检索，不是一次查表

## 4. 第五特性的总体技术路线

当前实现采用规则驱动的多阶段链路：

1. `ScopeResolver` 输出 `allowed_scopes`
2. `RetrievalPlanner` 生成 retrieval plan
3. `MemoryCandidateSelector` 收集候选
4. `ConsistentMemoryRetriever` 做一致性折叠
5. `ScenePolicy / ScopeWeightPolicy` 提供场景化权重
6. `MemoryRelevanceScorer` 计算 relevance
7. `MemoryRanker` 综合排序并输出 Top-K
8. `MemoryInjectionBuilder` 生成 `memory_context`
9. 进入既有 knowledge retrieval
10. 组装 `BusinessRequest`
11. provider 生成最终回答

这个设计的关键目标是分层解耦：

- memory retrieval 和 knowledge retrieval 是两段
- retrieval scorer 不依赖 provider
- memory retrieval 失败时，主链路仍然可以继续走 knowledge retrieval

## 5. 为什么要拆成多个模块

### 5.1 RetrievalPlanner

代码位置：

- [memory_retrieval_planner.py](/C:/Users/ddd/Desktop/Aurora/app/services/memory_retrieval_planner.py)

职责：

- 判断当前请求是否启用 memory retrieval
- 统一生成 `top_k / candidate_limit / per_scope_candidate_limit / retrieval_mode`
- 收集 query 中的上下文 cue

这样做的原因是：

- 是否检索 memory，本身就是业务决策，不应该散落在各层 `if/else`
- planner 输出 plan 后，后续 selector / scorer / ranker 才能围绕同一个 plan 工作

### 5.2 MemoryCandidateSelector

代码位置：

- [memory_candidate_selector.py](/C:/Users/ddd/Desktop/Aurora/app/services/memory_candidate_selector.py)

职责：

- 只负责收集候选
- 只做 scope、active、current-only 过滤
- 不参与排序和注入决策

这样做的原因是：

- 候选收集需要尽量贴近存储层和索引
- 排序逻辑属于业务层，不应该反向污染 repository 查询

### 5.3 ScenePolicy / ScopeWeightPolicy

代码位置：

- [memory_scene_policy.py](/C:/Users/ddd/Desktop/Aurora/app/services/memory_scene_policy.py)

职责：

- 定义 scene 对 scope 权重和 type 权重的覆盖
- 控制不同场景的 Top-K、阈值和最近窗口

这样做的原因是：

- 默认 scope 优先级只是一组基础偏好，不是绝对规则
- troubleshooting、onboarding、command_lookup 对 memory 的期待明显不同

### 5.4 MemoryRelevanceScorer

代码位置：

- [memory_relevance_scorer.py](/C:/Users/ddd/Desktop/Aurora/app/services/memory_relevance_scorer.py)

职责：

- 对候选 memory 打 relevance 分
- 当前版本采用轻量词法规则

这样做的原因是：

- 第一版先用可解释、低成本、可快速调试的规则
- 不引入 embedding 也能先建立正确的业务边界

当前 relevance 信号包括：

- query 和 content 的词法重叠
- exact phrase 命中
- `fact_key / subject_key` 命中
- contextual scope boost

当前实现还特别处理了中英文 cue：

- 英文：`current / session / context / discussion`
- 中文：`当前 / 我们 / 上下文 / 讨论 / 状态`

这样可以避免中文 query 因规则缺失而被低估。

### 5.5 MemoryRanker

代码位置：

- [memory_ranker.py](/C:/Users/ddd/Desktop/Aurora/app/services/memory_ranker.py)

职责：

- 综合多个信号输出 retrieval score
- 执行 Top-K、per-scope cap 和阈值过滤
- 记录 dropped candidates 的原因

当前公式：

```text
retrieval_score =
  relevance * 0.40 +
  scope_priority * 0.20 +
  recency * 0.15 +
  type_priority * 0.15 +
  source_confidence * 0.10
```

这样设计的原因是：

- relevance 仍然是第一主因
- scope 和 type 体现业务偏好
- recency 让最近状态更容易进入答案
- source confidence 帮助高质量记忆稳定胜出

### 5.6 MemoryInjectionBuilder

代码位置：

- [memory_injection_builder.py](/C:/Users/ddd/Desktop/Aurora/app/services/memory_injection_builder.py)

职责：

- 把排序后的结果转换成 provider 无关的 `MemoryContextItem`
- 统一控制注入内容长度

这样做的原因是：

- 上层消费的是业务对象，而不是 repository row
- prompt budget 控制必须集中，不能散落在 provider adapter 里

## 6. 为什么要有 consistency collapse

代码位置：

- [consistent_memory_retriever.py](/C:/Users/ddd/Desktop/Aurora/app/services/consistent_memory_retriever.py)

Aurora 前四个特性已经保证：

- 只返回当前有效主版本
- 能识别 superseded / correction / conflict

但在第五特性里还存在一个问题：

> 同一个逻辑事实可能在多个 scope 下同时存在，不能让它们一起挤占 Top-K。

因此当前实现会基于 `subject_key + fact_key` 对候选做折叠：

- 每组只保留一个代表项进入 ranker
- 其余候选作为 dropped candidate 记录下来

这里不再写死“session 永远赢”，而是根据：

- scene-aware scope weights
- source confidence
- version
- updated_at

综合判断哪个候选更适合作为当前场景的代表项。

这就是为什么在 onboarding 场景中，project decision 可以压过 session 的临时演示状态。

## 7. 为什么 memory 和 knowledge 必须分层

Aurora 明确保持：

- `memory_context` 表示背景事实、偏好、决策、临时状态
- `knowledge_context` 表示知识库检索得到的证据

原因有三点：

1. 语义不同
   memory 更像业务背景，knowledge 更像可引用证据。
2. 风险不同
   memory 不应该伪装成 citation。
3. 控制目标不同
   knowledge 更关注证据完整性，memory 更关注相关性和注入成本。

当前主链路里，memory retrieval 总是在 knowledge retrieval 之前执行，但两者仍然保持分段，不混检，不混排，不混存。

## 8. 当前实现如何控制性能

第五特性第一版不引入复杂检索引擎，但做了几项关键控制：

### 8.1 避免全表扫描

候选收集基于：

- `tenant_id`
- `scope_type + scope_id`
- `status`
- `updated_at`

并依赖既有索引：

- `idx_memory_facts_scope_status`
- `idx_memory_facts_identity_current`
- `idx_memory_facts_consistency_group`

### 8.2 控制候选规模

通过 plan 中的参数控制：

- `candidate_limit`
- `per_scope_candidate_limit`
- `top_k`
- `per_scope_top_k`

这样能避免低价值 memory 进入 scorer 和 ranker。

### 8.3 控制注入规模

当前同时控制：

- 总注入条数
- 每个 scope 的注入条数
- 单条 memory 的字符数

### 8.4 Trace 不阻塞主链路

`RetrievalTraceService` 只构造内存对象，不做额外 I/O，因此不会把 trace 变成主链路瓶颈。

## 9. 当前实现如何支持未来扩展

第五特性当前是规则驱动，但接口已经往正确方向铺好了。

### 9.1 Semantic Retrieval

当前 `MemoryRelevanceScorerPort` 已经把 scorer 接口抽出来，未来可以新增：

- `SemanticRelevanceScorer`

只要满足相同的 `score(query, candidate)` 契约，就能接入现有 ranker。

### 9.2 Hybrid Retrieval

当前已经提供：

- `CompositeMemoryRelevanceScorer`

未来可以组合：

- lexical scorer
- semantic scorer
- specialized scene scorer

### 9.3 Learned Ranking

当前 `MemoryRanker` 支持可注入的权重配置，未来可以逐步从固定权重演进到：

- learned weights
- scene-specific tuned weights
- feedback-based reranking

### 9.4 Forgetting-aware Ranking

当前已保留了 recency 和 score breakdown 边界，未来可以继续加入：

- decay by age
- decay by contradiction history
- decay by low reuse rate

而无需重写整个 retrieval 管道。

## 10. 当前内部调试边界

为了支持第五特性的灰度验证和调试，当前提供内部接口：

- `POST /api/v1/internal/memory/retrieve`

它用于查看：

- 当前 scene 的 retrieval plan
- selected memories
- dropped candidates
- retrieval trace
- 最终注入的 `memory_context`

当前设计结论是：

- memory retrieval 核心能力不应该暴露成 public API
- 但必须保留 internal preview API，用于调试、回归和质量分析

## 11. 关键代码落点

核心实现文件：

- [memory_retrieval_models.py](/C:/Users/ddd/Desktop/Aurora/app/services/memory_retrieval_models.py)
- [memory_retrieval_planner.py](/C:/Users/ddd/Desktop/Aurora/app/services/memory_retrieval_planner.py)
- [memory_candidate_selector.py](/C:/Users/ddd/Desktop/Aurora/app/services/memory_candidate_selector.py)
- [memory_scene_policy.py](/C:/Users/ddd/Desktop/Aurora/app/services/memory_scene_policy.py)
- [memory_relevance_scorer.py](/C:/Users/ddd/Desktop/Aurora/app/services/memory_relevance_scorer.py)
- [memory_ranker.py](/C:/Users/ddd/Desktop/Aurora/app/services/memory_ranker.py)
- [memory_injection_builder.py](/C:/Users/ddd/Desktop/Aurora/app/services/memory_injection_builder.py)
- [memory_retrieval_trace.py](/C:/Users/ddd/Desktop/Aurora/app/services/memory_retrieval_trace.py)
- [memory_retriever.py](/C:/Users/ddd/Desktop/Aurora/app/services/memory_retriever.py)

链路接入文件：

- [chat.py](/C:/Users/ddd/Desktop/Aurora/app/api/chat.py)
- [rag_service.py](/C:/Users/ddd/Desktop/Aurora/app/services/rag_service.py)
- [memory.py](/C:/Users/ddd/Desktop/Aurora/app/api/routes/memory.py)

## 12. 总结

Aurora 第五特性的真正价值不在于“多检索一些 memory”，而在于建立了一条清晰、可控、可解释的 memory 进入回答链路：

- 先做可读性约束
- 再做场景相关性筛选
- 再做排序和限量注入

这样既能让 memory 在合适的时候发挥作用，又不会污染知识库主链路，也不会把 prompt 变成无限增长的背景堆积。

这就是当前第五特性的技术路线和实现原理。
