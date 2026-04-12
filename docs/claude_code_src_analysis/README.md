# ClaudeCode `src` 源码分析沉淀

## 1. 分析目标

这份文档用于沉淀对 `D:\AI资源\ClaudeCode泄露源码\src` 的阶段性分析结果，重点不是复用具体实现，而是提炼其中适合 Aurora 的架构思想、调度策略和能力组织方式。

当前结论遵循两个原则：

- 优先吸收设计方法，不直接搬运实现细节。
- 优先保留对 Aurora 真实有帮助的能力模型，而不是泛化总结。

## 2. 本次重点查看的模块

### 2.1 Query / Agent 主链路

- `src/QueryEngine.ts`
- `src/query.ts`
- `src/Task.ts`
- `src/coordinator/coordinatorMode.ts`

### 2.2 Tools 调度与执行

- `src/tools.ts`
- `src/Tool.ts`
- `src/services/tools/toolExecution.ts`
- `src/services/tools/StreamingToolExecutor.ts`
- `src/services/tools/toolOrchestration.ts`
- `src/tools/ToolSearchTool/ToolSearchTool.ts`
- `src/utils/toolSearch.ts`

### 2.3 Skills / Workflow 能力包

- `src/tools/SkillTool/SkillTool.ts`
- `src/skills/loadSkillsDir.ts`
- `src/skills/bundledSkills.ts`
- `src/skills/bundled/verify.ts`
- `src/skills/bundled/remember.ts`

### 2.4 Memory / Compact / Summary

- `src/services/compact/autoCompact.ts`
- `src/services/compact/microCompact.ts`
- `src/memdir/findRelevantMemories.ts`
- `src/memdir/memoryScan.ts`
- `src/services/SessionMemory/sessionMemory.ts`
- `src/services/toolUseSummary/toolUseSummaryGenerator.ts`

### 2.5 MCP / Plugin / Commands 体系

- `src/commands.ts`
- `src/types/command.ts`
- `src/types/plugin.ts`
- `src/services/mcp/client.ts`
- `src/services/mcp/config.ts`
- `src/services/mcp/types.ts`
- `src/utils/plugins/pluginLoader.ts`
- `src/utils/plugins/loadPluginCommands.ts`
- `src/utils/plugins/mcpPluginIntegration.ts`
- `src/utils/plugins/schemas.ts`
- `src/plugins/builtinPlugins.ts`
- `src/commands/mcp/addCommand.ts`
- `src/services/plugins/pluginCliCommands.ts`
- `src/commands/createMovedToPluginCommand.ts`
- `src/utils/plugins/pluginPolicy.ts`
- `src/utils/plugins/validatePlugin.ts`

## 3. 核心观察

## 3.1 Query Engine 是状态机，不是单次 LLM 调用

ClaudeCode 不是简单地做一次 `retrieve -> prompt -> answer`，而是把整个执行流程做成了一个状态机：

- 先装配上下文、预算、系统能力。
- 再触发模型输出。
- 遇到 tool call 后进入调度器。
- 工具结果回填后决定是否继续下一轮。
- 上下文过长时会触发压缩、裁剪或降级。

这意味着它的主引擎是“可循环、可恢复、可分阶段”的。

对 Aurora 的启发：

- 知识库问答后续不应该停留在一次性 `RAG + 生成`。
- 更稳的做法是演进成 `Query Orchestrator`。
- Orchestrator 负责检索、工具路由、上下文治理、引用追踪和失败回退。

## 3.2 Tool 不是函数，而是正式协议对象

在 `Tool.ts` 一类文件里，工具被建模成具备明确元数据的运行时对象，而不是随意拼接的可调用函数。

一个成熟 Tool 通常包含：

- 名称和描述
- 输入输出 schema
- 权限要求
- 是否只读
- 是否可并发
- 是否应该延迟暴露
- 调用后的上下文写回方式

对 Aurora 的启发：

- 文档问答、数据库查询、联网搜索、索引重建都不应只是 service 方法。
- 应该统一抽象成 Tool，供 Router、策略层和审计层共同消费。

## 3.3 Tool Scheduler 的重点是并发安全，而不是“能并发就并发”

`toolOrchestration.ts` 和 `StreamingToolExecutor.ts` 最值得借鉴的点是并发分级：

- 只读工具可并发。
- 有副作用工具串行。
- 并发执行时仍保持结果顺序稳定。
- 某些工具失败可以取消同批次工具。
- 用户中断时只取消可取消的任务。

对 Aurora 的启发：

- `dense recall / sparse recall / web search / schema lookup` 可以并发。
- `写库 / 改权限 / 重建索引 / 删除文档` 必须串行。
- 工具执行器应成为单独一层，而不是散落在 API 或 service 中。

## 3.4 Tool Search 用于能力延迟暴露

当工具过多时，ClaudeCode 不会把所有工具一次性塞给主模型，而是先通过 `ToolSearchTool` 搜索候选能力，再引入真正需要的工具。

价值在于：

- 降低 prompt 体积
- 提高工具选择精度
- 避免“工具太多导致路由噪声”

对 Aurora 的启发：

- 后续如果有文档问答、SQL、联网、报表分析、审计等多个能力，不应该全部常驻暴露给 Router。
- 更好的方式是先做 `Capability Search`，再做精确能力装配。

## 3.5 Skill 不是 prompt 模板，而是“带元数据的工作流包”

`loadSkillsDir.ts` 一类实现显示，Skill 不是单纯的文本提示词，而是带 frontmatter 的工作流单元。

可声明的信息包括：

- 描述和适用场景
- 允许使用的工具
- 参数
- 使用的模型和推理强度
- 上下文约束
- agent 模式
- 路径条件
- shell 权限

这说明 Skill 更像是一个“业务工作流能力包”。

对 Aurora 的启发：

- 后续完全可以有 `policy-search`、`contract-review`、`financial-report-qa`、`knowledge-import-audit` 这样的 Workflow Skill。
- Skill 适合承载 prompt 规范、工具白名单、模型选择和工作流编排。

## 3.6 Conditional Skill Activation 非常适合知识域路由

ClaudeCode 允许 Skill 按路径或上下文条件动态激活。

对 Aurora 的映射非常自然：

- 命中 Excel 数据源时激活表格分析 Skill。
- 命中制度库时激活政策引用 Skill。
- 命中财务空间时激活财务审核 Skill。

这说明 Skill 不应该全量常驻，而应该按知识域和上下文动态出现。

## 3.7 Skill 可以 fork 子代理

`SkillTool.ts` 支持 Skill 以两种方式执行：

- Inline 执行
- Forked sub-agent 执行

Fork 的价值：

- 独立 token budget
- 独立上下文
- 复杂流程不会污染主对话
- 结果回传更干净

对 Aurora 的启发：

- 长文档摘要、多路检索、导入审计、复杂 SQL 解释都适合走独立工作流上下文。

## 3.8 MCP 的本质是“远程能力翻译器”

`services/mcp/client.ts` 最有价值的一点是，它会把远程能力翻译成本地统一对象：

- `tools/list` -> 内部 `Tool`
- `prompts/list` -> 内部 `Command`
- `resources/list` -> 内部 `Resource`

也就是说，MCP server 接入后不会形成新的异构分支，而是进入同一套能力模型。

对 Aurora 的启发：

- 外部数据库、企业搜索、BI、OA、网页抓取都可以走统一连接器模型。
- 连接器层的职责是把外部协议翻译成 Aurora 内部可调度对象。

## 3.9 Plugin 是分发单元，Tool / Command / Resource / Skill 是运行时单元

在 ClaudeCode 的设计里，Plugin 不是“一个工具”，而是一个扩展容器。

Plugin 可以声明：

- commands
- skills
- agents
- hooks
- MCP servers
- settings
- dependencies

这说明：

- Plugin 负责分发和装配
- Tool / Command / Resource / Skill 负责运行时执行

这是很成熟的职责边界。

## 3.10 配置合并做得非常生产化

MCP 和 Plugin 的配置并不是简单 merge，而是具备：

- 多来源合并
- 作用域区分
- 启用/禁用控制
- allowlist / denylist
- 签名级别判重
- 用户配置优先于默认配置

这对多租户、多来源外部连接器非常关键。

## 3.11 Memory / Summary 是单独的基础服务

ClaudeCode 没有把 Memory 和 Summary 塞进主链路里临时拼，而是单独做成服务：

- Session memory 负责长期会话摘要
- Tool use summary 负责工具批次的 UI 级概览
- Compact 服务负责上下文回收和降噪

对 Aurora 的启发：

- 长会话和多工具问答后续都需要上下文治理层。
- 记忆摘要、检索摘要、工具摘要应与主问答链路解耦。

## 4. 对 Aurora 最有价值的思想

综合当前分析，最适合 Aurora 先吸收的是以下几点：

1. Query Orchestrator 状态机
2. Tool 协议和 Tool Scheduler
3. Capability Search
4. Skill / Workflow Registry
5. MCP 风格的 Connector 翻译层
6. Session Memory / Tool Summary
7. 多来源配置合并与权限前置过滤

## 5. 不建议直接复用的部分

以下内容更适合借思想，不建议直接移植：

- CLI / shell / 本地文件编辑导向的执行逻辑
- 深度绑定当前运行时的 prompt 结构和消息块协议
- 产品内建 feature gate 和内部埋点体系
- 泄露源码中的编码异常文本

其中最后一点尤其需要注意：当前源码 dump 中能看到明显的编码污染痕迹，例如 `鈥?` 等异常字符，因此更应该以“设计提炼”为主，而不是做源码级复制。

## 6. 对 Aurora 的初步结论

Aurora 最值得借鉴的不是某一个工具实现，而是下面这条主线：

- 把“能力”抽象成统一对象
- 把“连接器”抽象成外部能力翻译层
- 把“插件”抽象成能力分发包
- 把“查询”抽象成状态机式执行过程
- 把“记忆和摘要”抽象成独立基础服务

换句话说，ClaudeCode 的价值不在于它用了多少工具，而在于它把“能力系统”本身设计成了一个可治理、可扩展、可审计的平台。

这正是 Aurora 后续演进成生产级知识工作台时最值得吸收的部分。

## 7. 后续建议

建议 Aurora 按以下顺序吸收这些思想：

1. 先建立 `Connector / Capability Registry` 的统一抽象。
2. 再把现有知识库问答、文档 ETL、索引重建能力注册成内建能力。
3. 再逐步引入外部连接器和 Skill / Workflow。
4. 最后再演进到多工具并发调度、上下文压缩和多代理编排。

对应的 Aurora 目标架构设计，见同级文档体系中的 `aurora_connector_capability_registry` 设计文档。
