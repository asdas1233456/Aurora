# Aurora Python 后端重分类与核心代码保护建议

更新日期：2026-04-04

## 1. 先说结论

Aurora 现在的 Python 后端不适合再继续“边写边堆”了，原因不是功能不够，而是目录语义已经开始漂移：

- `app/services/` 同时承担了业务服务、仓储、策略、审计、ETL、基础设施适配
- `memory` 已经拆出 `read / write / governance` 子目录，但根层还保留了一整套兼容转发文件
- `schemas.py` 承担了过多跨域数据结构
- `providers/`、`llm.py`、`storage_service.py`、`session_repository.py` 这类基础设施能力没有明确归位

建议不要做“纯学术式 DDD 重构”，而是按 Aurora 当前最合适的形态，收敛到：

- 模块化单体
- 按业务域分目录
- 基础设施单独收口
- HTTP 接入层单独收口
- 兼容层短期保留，分阶段删除

## 2. 当前主要问题

### 2.1 根层 `services/` 混放

当前 `app/services/` 里同时存在：

- 业务服务：`document_service.py`、`knowledge_base_service.py`、`rag_service.py`
- 仓储：`memory_repository.py`、`session_repository.py`、`message_repository.py`
- 治理策略：`memory_access_policy.py`、`retention_policy.py`
- 基础设施：`storage_service.py`、`local_index_service.py`
- 系统能力：`settings_service.py`、`log_service.py`、`observability_service.py`

这会带来两个问题：

- 新人很难判断一个文件到底属于业务层还是基础设施层
- 后续权限、审计、任务恢复一旦扩展，会越来越难拆

### 2.2 `memory` 处于半迁移状态

现在 `memory` 相关能力已经有更合理的新目录：

- `app/services/memory/read/`
- `app/services/memory/write/`
- `app/services/memory/governance/`

但根层还保留了大量兼容入口，例如：

- `app/services/memory_retriever.py`
- `app/services/memory_repository.py`
- `app/services/memory_write_service.py`
- `app/services/retention_policy.py`

这些文件本质上只是 re-export 兼容层。短期能保旧引用，长期会制造真假入口并存的问题。

### 2.3 `schemas.py` 过大

当前 [schemas.py](/C:/Users/ddd/Desktop/Aurora/app/schemas.py) 同时承载：

- 聊天结果
- 认证用户
- 审计记录
- 配置 DTO
- 知识库任务
- memory 作用域模型

这会导致：

- 任一模块调整数据结构，都会扩大合并冲突范围
- 模块边界在类型层面不清晰

### 2.4 HTTP 层与业务层边界还不够稳定

现在 `api/routes` 已经是正确方向，但仍有一部分辅助逻辑散在：

- `app/api/*.py`
- `app/api/routes/*.py`
- `app/auth.py`
- `app/server.py`

建议继续收紧成“纯接入层 + 纯业务层”，避免把策略和基础设施细节留在 HTTP 入口附近。

## 3. 推荐目标结构

建议把 Aurora 后端重分类为下面这套结构：

```text
app/
  bootstrap/
    http_app.py

  core/
    config.py
    auth.py
    logging.py
    security.py

  presentation/
    http/
      dependencies.py
      request_context.py
      request_models.py
      serializers.py
      routes/
        chat.py
        documents.py
        knowledge_base.py
        knowledge_graph.py
        logs.py
        memory.py
        providers.py
        settings.py
        system.py

  modules/
    chat/
      service.py
      session_service.py
      recovery_service.py
      repository.py
      models.py

    documents/
      service.py
      catalog_service.py
      materialization_service.py
      taxonomy.py
      etl/

    knowledge/
      base_service.py
      job_service.py
      graph_service.py
      retrieval_service.py
      rag_service.py
      access_policy.py

    memory/
      governance/
      read/
      write/

    system/
      settings_service.py
      log_service.py
      audit_service.py
      observability_service.py
      health_service.py
      connectivity_service.py
      system_service.py

    orchestration/
      capabilities/

  infrastructure/
    ai/
      llm.py
      providers/

    persistence/
      sqlite.py
      state_storage.py
      persistence_utils.py
      session_repository.py
      message_repository.py

    indexing/
      local_index_service.py

  shared/
    contracts/
      auth.py
      chat.py
      documents.py
      knowledge.py
      memory.py
      settings.py
      system.py
```

## 4. 当前文件到目标目录的映射建议

### 4.1 核心启动与平台基础

| 当前文件 | 建议目标 |
| --- | --- |
| [server.py](/C:/Users/ddd/Desktop/Aurora/app/server.py) | `app/bootstrap/http_app.py` |
| [config.py](/C:/Users/ddd/Desktop/Aurora/app/config.py) | `app/core/config.py` |
| [auth.py](/C:/Users/ddd/Desktop/Aurora/app/auth.py) | `app/core/auth.py` |
| [logging_config.py](/C:/Users/ddd/Desktop/Aurora/app/logging_config.py) | `app/core/logging.py` |
| [api/security.py](/C:/Users/ddd/Desktop/Aurora/app/api/security.py) | `app/core/security.py` 或 `presentation/http/security.py` |

### 4.2 HTTP 接入层

| 当前文件 | 建议目标 |
| --- | --- |
| [api/dependencies.py](/C:/Users/ddd/Desktop/Aurora/app/api/dependencies.py) | `app/presentation/http/dependencies.py` |
| [api/request_context.py](/C:/Users/ddd/Desktop/Aurora/app/api/request_context.py) | `app/presentation/http/request_context.py` |
| [api/request_models.py](/C:/Users/ddd/Desktop/Aurora/app/api/request_models.py) | `app/presentation/http/request_models.py` |
| [api/serializers.py](/C:/Users/ddd/Desktop/Aurora/app/api/serializers.py) | `app/presentation/http/serializers.py` |
| [api/routes/*.py](/C:/Users/ddd/Desktop/Aurora/app/api/routes) | `app/presentation/http/routes/*.py` |

### 4.3 文档与知识库域

| 当前文件 | 建议目标 |
| --- | --- |
| [document_service.py](/C:/Users/ddd/Desktop/Aurora/app/services/document_service.py) | `app/modules/documents/service.py` |
| [catalog_service.py](/C:/Users/ddd/Desktop/Aurora/app/services/catalog_service.py) | `app/modules/documents/catalog_service.py` |
| [document_materialization_service.py](/C:/Users/ddd/Desktop/Aurora/app/services/document_materialization_service.py) | `app/modules/documents/materialization_service.py` |
| [document_taxonomy.py](/C:/Users/ddd/Desktop/Aurora/app/services/document_taxonomy.py) | `app/modules/documents/taxonomy.py` |
| [services/etl/*](/C:/Users/ddd/Desktop/Aurora/app/services/etl) | `app/modules/documents/etl/*` |
| [knowledge_base_service.py](/C:/Users/ddd/Desktop/Aurora/app/services/knowledge_base_service.py) | `app/modules/knowledge/base_service.py` |
| [knowledge_base_job_service.py](/C:/Users/ddd/Desktop/Aurora/app/services/knowledge_base_job_service.py) | `app/modules/knowledge/job_service.py` |
| [knowledge_graph_service.py](/C:/Users/ddd/Desktop/Aurora/app/services/knowledge_graph_service.py) | `app/modules/knowledge/graph_service.py` |
| [retrieval_service.py](/C:/Users/ddd/Desktop/Aurora/app/services/retrieval_service.py) | `app/modules/knowledge/retrieval_service.py` |
| [rag_service.py](/C:/Users/ddd/Desktop/Aurora/app/services/rag_service.py) | `app/modules/knowledge/rag_service.py` |
| [knowledge_access_policy.py](/C:/Users/ddd/Desktop/Aurora/app/services/knowledge_access_policy.py) | `app/modules/knowledge/access_policy.py` |

### 4.4 聊天与会话域

| 当前文件 | 建议目标 |
| --- | --- |
| [chat_session_service.py](/C:/Users/ddd/Desktop/Aurora/app/services/chat_session_service.py) | `app/modules/chat/session_service.py` |
| [session_recovery_service.py](/C:/Users/ddd/Desktop/Aurora/app/services/session_recovery_service.py) | `app/modules/chat/recovery_service.py` |
| [session_repository.py](/C:/Users/ddd/Desktop/Aurora/app/services/session_repository.py) | `app/modules/chat/repository.py` 或 `app/infrastructure/persistence/session_repository.py` |
| [message_repository.py](/C:/Users/ddd/Desktop/Aurora/app/services/message_repository.py) | `app/modules/chat/repository.py` 或 `app/infrastructure/persistence/message_repository.py` |

### 4.5 Memory 域

这一部分其实已经有目标结构，建议保留现有子目录方向：

- `app/services/memory/governance/*`
- `app/services/memory/read/*`
- `app/services/memory/write/*`

下一步不是再重设计，而是：

- 所有新引用直接改到子目录
- 根层兼容 re-export 文件只保留一个过渡周期
- 最终删除根层重复入口

### 4.6 系统与治理域

| 当前文件 | 建议目标 |
| --- | --- |
| [settings_service.py](/C:/Users/ddd/Desktop/Aurora/app/services/settings_service.py) | `app/modules/system/settings_service.py` |
| [log_service.py](/C:/Users/ddd/Desktop/Aurora/app/services/log_service.py) | `app/modules/system/log_service.py` |
| [application_audit_service.py](/C:/Users/ddd/Desktop/Aurora/app/services/application_audit_service.py) | `app/modules/system/audit_service.py` |
| [observability_service.py](/C:/Users/ddd/Desktop/Aurora/app/services/observability_service.py) | `app/modules/system/observability_service.py` |
| [persistence_health_service.py](/C:/Users/ddd/Desktop/Aurora/app/services/persistence_health_service.py) | `app/modules/system/health_service.py` |
| [connectivity_service.py](/C:/Users/ddd/Desktop/Aurora/app/services/connectivity_service.py) | `app/modules/system/connectivity_service.py` |
| [system_service.py](/C:/Users/ddd/Desktop/Aurora/app/services/system_service.py) | `app/modules/system/system_service.py` |
| [abuse_guard.py](/C:/Users/ddd/Desktop/Aurora/app/services/abuse_guard.py) | `app/core/security.py` 或 `app/modules/system/abuse_guard.py` |

### 4.7 AI 与基础设施

| 当前文件 | 建议目标 |
| --- | --- |
| [llm.py](/C:/Users/ddd/Desktop/Aurora/app/llm.py) | `app/infrastructure/ai/llm.py` |
| [providers/*](/C:/Users/ddd/Desktop/Aurora/app/providers) | `app/infrastructure/ai/providers/*` |
| [storage_service.py](/C:/Users/ddd/Desktop/Aurora/app/services/storage_service.py) | `app/infrastructure/persistence/state_storage.py` |
| [persistence_utils.py](/C:/Users/ddd/Desktop/Aurora/app/services/persistence_utils.py) | `app/infrastructure/persistence/persistence_utils.py` |
| [local_index_service.py](/C:/Users/ddd/Desktop/Aurora/app/services/local_index_service.py) | `app/infrastructure/indexing/local_index_service.py` |
| [services/capabilities/*](/C:/Users/ddd/Desktop/Aurora/app/services/capabilities) | `app/modules/orchestration/capabilities/*` |

## 5. 建议的重构顺序

不要一次性大迁移。建议按下面顺序做：

### 第 1 步：先建目标目录，不动业务逻辑

- 新建 `core / presentation / modules / infrastructure / shared`
- 先把新文件放进去，不立即删旧文件
- 旧入口继续保留 compatibility import

### 第 2 步：优先收 `memory` 重复入口

- 所有新引用统一改到 `app.services.memory.*`
- 根层 `memory_*` re-export 文件标记为 deprecated
- 测试稳定后删除根层兼容层

这是最值的第一刀，因为现在重复最严重。

### 第 3 步：拆 `schemas.py`

优先拆成：

- `shared/contracts/auth.py`
- `shared/contracts/chat.py`
- `shared/contracts/knowledge.py`
- `shared/contracts/memory.py`
- `shared/contracts/settings.py`
- `shared/contracts/system.py`

### 第 4 步：把仓储和基础设施从 `services` 里抽出去

优先迁移：

- `storage_service.py`
- `session_repository.py`
- `message_repository.py`
- `local_index_service.py`
- `providers/*`
- `llm.py`

### 第 5 步：最后整理 import 和删除兼容层

- 全仓搜索旧路径引用
- 改成新路径
- 删除 re-export 文件
- 补充单元测试和 API 集成测试

## 6. 关于“核心代码加密不泄露”的现实结论

可以先直接说结论：

### 6.1 Python 代码没有真正意义上的“绝对加密不泄露”

只要代码需要在你的服务器上执行，就一定会以某种形式被加载、被解释、被运行。

所以：

- 你可以提高还原成本
- 你可以减少接触面
- 你可以降低内部扩散概率
- 但你不能保证“拿到机器的人永远看不到核心逻辑”

如果有人拥有：

- 服务器 root 权限
- 运行时进程访问权
- 构建产物和调试能力

那“彻底不可见”基本做不到。

### 6.2 真正有效的是“分层保护”，不是单点加密

对 Aurora 这种内网部署项目，更现实的方案是五层一起做：

1. 不让核心逻辑进入前端
2. 源码仓库权限最小化
3. 交付物只发构建产物，不发完整源码
4. 对少量核心模块做编译混淆
5. 用审计、部署和人员权限控制泄露面

## 7. Aurora 可执行的保护方案

### 方案 A：只在服务端保留核心算法

这是必须做的，不是可选项。

Aurora 的核心逻辑应始终只存在于后端：

- 权限判断
- 检索排序策略
- memory 写入治理
- 审计规则
- provider 路由逻辑

浏览器绝不保存这些规则实现。

### 方案 B：交付时不直接分发源码

内部部署时建议优先交付：

- wheel
- 私有容器镜像
- 编译后的可执行部署包

而不是把整仓源码直接发给每个部署节点。

### 方案 C：对少量核心模块做编译保护

如果你确实想提高核心代码逆向门槛，可对这几类模块使用：

- `Cython`
- `Nuitka`

适合编译保护的 Aurora 核心模块：

- memory 治理策略
- 检索排序与打分
- 权限 / 审计核心规则
- provider 路由与能力保护

不建议全量编译整个项目，维护成本太高。更适合“只编译最核心的 10% 模块”。

### 方案 D：把高敏感规则从源码挪到受控配置

如果某些内容比代码本身更敏感，可以进一步拆出：

- 高价值 prompt 模板
- provider 路由规则
- 审计规则
- 风控阈值

这些内容可以放在：

- 运维注入配置
- 受控数据库表
- 私有配置中心

这样即使有人拿到普通源码，也不等于拿到全部关键策略。

### 方案 E：仓库和部署权限分级

这是比“代码加密”更实用的手段：

- 不是所有开发者都需要生产分支写权限
- 不是所有运维都需要源码仓库读权限
- 不是所有测试环境都需要完整生产规则
- 部署机器禁止随意登录和下载构建物

### 方案 F：增加审计与泄露追踪

建议同时做：

- Git 仓库审计
- 制品下载审计
- 运维操作审计
- 配置读取审计

如果未来真要做更强控制，可以在构建产物和导出文档里加入：

- 构建批次标记
- 环境标记
- 使用方标记

## 8. 不同保护方式的现实效果

| 方式 | 能否防普通使用者 | 能否防有服务器权限的人 | 维护成本 | 推荐度 |
| --- | --- | --- | --- | --- |
| 前后端分离，核心只放后端 | 高 | 低 | 低 | 很高 |
| 私有镜像 / wheel 交付 | 中 | 低 | 低 | 很高 |
| Cython / Nuitka 编译关键模块 | 中 | 中低 | 中 | 高 |
| 全量源码混淆 | 低 | 低 | 高 | 低 |
| 把关键规则移到受控配置 | 中高 | 中 | 中 | 高 |
| 纯“代码加密壳” | 低 | 低 | 中高 | 低 |

## 9. 对 Aurora 的具体建议

如果目标是“尽量不泄露核心代码”，我建议 Aurora 按下面这套组合：

1. 先完成后端目录重分类，明确哪些是核心域代码
2. 核心代码只保留在后端，不再出现浏览器透传密钥或前端规则实现
3. 交付时优先使用私有镜像或 wheel，不直接分发完整源码
4. 对 `memory / retrieval / policy / provider-routing` 这几个核心模块做 Cython 或 Nuitka 编译
5. 把最敏感的 prompt、路由规则、阈值改成服务端受控配置
6. 用仓库、制品、部署权限和审计来补上管理侧防泄露

## 10. 最后一句判断

如果你的目标是：

- “让普通使用者拿不到核心代码”，可以做到，且效果不错
- “让拿到服务器权限的人也完全看不到核心代码”，基本做不到

所以正确目标不是“绝对加密不泄露”，而是：

- 不把核心逻辑暴露到不该暴露的位置
- 提高逆向和复制成本
- 控制谁能接触源码、制品和运行环境
- 让泄露有审计、有痕迹、有追责路径
