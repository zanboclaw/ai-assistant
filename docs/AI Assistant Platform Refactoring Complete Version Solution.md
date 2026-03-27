# AI Assistant 平台重构完整版方案

## 一、方案目标

本次重构不是为了“代码更漂亮”，而是为了把项目从：

**可运行的平台底座**

重构为：

**可持续维护、可控发布、可治理、可扩展、可小规模稳定使用的平台产品工程**。

这个目标之所以成立，是因为当前仓库已经具备任务输入、正式任务、Fast Path、记忆、治理、多 Agent、回滚与前端工作台等完整平台雏形，但作者也明确指出它尚未完全收口为终态产品。([github.com](https://github.com/zanboclaw/ai-assistant)) ([raw.githubusercontent.com](https://raw.githubusercontent.com/zanboclaw/ai-assistant/master/docs/next_ai.md))

---

## 二、核心问题定义

结合当前仓库现状，本次重构要解决的不是单点 bug，而是以下几类系统性问题。

### 1. 结构复杂度过度集中

当前 API 装配、Worker 运行时和前端主逻辑都存在明显的大文件集中现象。作者在现状文档中明确点出 `api_app_context.py`、`worker_runtime_context.py`、`dashboard.js` 等文件仍承担大量真实复杂度。([raw.githubusercontent.com](https://raw.githubusercontent.com/zanboclaw/ai-assistant/master/docs/next_ai.md))

### 2. 工程化护栏不足

仓库已存在 pytest、Playwright、CI、Compose 和运维文档，但作者明确给出的覆盖率基线仍只有约 21%，说明当前仍缺少足够的重构护栏。([raw.githubusercontent.com](https://raw.githubusercontent.com/zanboclaw/ai-assistant/master/docs/next_ai.md)) ([github.com](https://github.com/zanboclaw/ai-assistant/tree/master/tests))

### 3. schema 生命周期未完全收口

现状文档明确指出 migration-first 尚未真正完成，运行时 `ensure_*table / ensure_*columns` 逻辑仍大量存在。([raw.githubusercontent.com](https://raw.githubusercontent.com/zanboclaw/ai-assistant/master/docs/next_ai.md))

### 4. 平台能力已形成，但产品闭环未完全收口

从前端首页与 README 可看出，系统已经朝“任务工作台 + 治理控制台 + 监控台”演进，但仍偏工程控制台，不完全像成熟产品。([raw.githubusercontent.com](https://raw.githubusercontent.com/zanboclaw/ai-assistant/master/apps/web/index.html)) ([github.com](https://github.com/zanboclaw/ai-assistant))

### 5. 治理概念存在，但边界未被系统性固化

README 中已经明确出现 actor、quota、risk policy、tool registry、change request、shadow validation、rollback 等治理能力，但现状文档也提示：是否覆盖所有高风险接口，仍需系统盘点。([github.com](https://github.com/zanboclaw/ai-assistant)) ([raw.githubusercontent.com](https://raw.githubusercontent.com/zanboclaw/ai-assistant/master/docs/next_ai.md))

---

## 三、重构总体原则

## 原则 1：先把系统变成“可控资产”，再继续扩能力

当前系统最大风险不是功能不够，而是功能已经很多，但工程约束和结构边界还没完全跟上。([raw.githubusercontent.com](https://raw.githubusercontent.com/zanboclaw/ai-assistant/master/docs/next_ai.md))

## 原则 2：按职责与状态机拆分，不按文件长度拆分

特别是 Worker，不能只因为文件大就横切拆成一堆 util，而必须按：

* 任务载入
* 规划
* 执行
* 工具调用
* 恢复
* 交付
* 多 Agent
* workflow / rollback
  这些运行阶段去拆。

## 原则 3：先建立新骨架，再迁逻辑，再下线旧入口

必须采用兼容式迁移，而不是推倒重来。

## 原则 4：所有重构必须有测试护栏

不允许“边拆边猜”。

## 原则 5：治理是平台核心能力，不是附加功能

这个项目不是普通聊天应用，治理、权限、风险控制、审计与回滚是平台定位的一部分。README 已明确证明这一点。([github.com](https://github.com/zanboclaw/ai-assistant))

---

## 四、目标架构总览

目标架构应从“按应用文件堆积”重构为“按职责分层 + 按业务域分区”。

### 目标分层

* **Presentation / Entry Layer**：API routes、Web 页面入口
* **Application Layer**：用例编排
* **Domain Layer**：任务、会话、治理、工作流等核心领域模型
* **Runtime Layer**：Worker 状态机与执行内核
* **Policy Layer**：权限、配额、风险、审批
* **Infrastructure Layer**：DB、Redis、LLM Provider、工具运行时、审计、文件系统
* **Contracts Layer**：前后端、API、Worker 间共享 schema 与状态字典

---

# 五、API 重构方案

## 5.1 API 重构目标

把当前 API 从“路由 + 装配 + 部分业务 + 部分治理 + 部分基础设施混合体”，重构成**清晰的用例层 + 领域层 + 基础设施层**。

README 已表明 API 不只是 CRUD，而是包含 intake、confirm、tasks、fast-path、sessions、memories、governance、workflow 等多域能力。([github.com](https://github.com/zanboclaw/ai-assistant))

## 5.2 API 目标目录结构

```text
apps/api/
  main.py

  bootstrap/
    app_factory.py
    container.py
    dependencies.py
    config.py

  routes/
    intake_routes.py
    task_routes.py
    chat_routes.py
    session_routes.py
    memory_routes.py
    governance_routes.py
    workflow_routes.py
    health_routes.py

  application/
    intake/
      analyze_input.py
      create_draft.py
      confirm_draft.py
      fast_path_chat.py
    task/
      create_task.py
      get_task.py
      list_tasks.py
      get_task_workspace.py
    session/
      get_session_state.py
      review_session.py
    memory/
      search_memory.py
      write_memory.py
    governance/
      get_actor_status.py
      get_quota_status.py
      manage_risk_policy.py
      manage_tool_registry.py
    workflow/
      propose_workflow.py
      validate_shadow_run.py
      rollback_workflow.py

  domain/
    task/
      entities.py
      enums.py
      repository.py
      policies.py
    session/
      entities.py
      repository.py
    memory/
      entities.py
      repository.py
    governance/
      entities.py
      repository.py
    workflow/
      entities.py
      repository.py

  infrastructure/
    db/
      connection.py
      task_repo_pg.py
      session_repo_pg.py
      memory_repo_pg.py
      governance_repo_pg.py
      workflow_repo_pg.py
    cache/
      redis_client.py
    providers/
      llm_provider.py
      search_provider.py
    audit/
      audit_logger.py
    tooling/
      registry_loader.py

  policy/
    permission_guard.py
    actor_policy.py
    quota_policy.py
    risk_policy.py

  schemas/
    intake.py
    task.py
    session.py
    memory.py
    governance.py
    workflow.py
    common.py
```

## 5.3 API 各层职责

### `bootstrap/`

只负责应用初始化、依赖注入、配置和生命周期管理，不承载业务。

### `routes/`

只负责：

* 请求解析
* 调用 application 用例
* 返回 schema

禁止在路由层：

* 直接写 SQL
* 直接拼 Redis 逻辑
* 手写复杂权限判断
* 拼装任务执行状态

### `application/`

作为 API 的真正业务编排层。
例如 `confirm_draft.py` 要负责：

* 校验输入
* 转正式任务
* 写审计
* 调起后续执行准备
* 返回任务标识

### `domain/`

沉淀核心业务对象：

* Task
* Session
* MemoryRecord
* GovernanceDecision
* WorkflowProposal

### `infrastructure/`

收口外部依赖：

* PostgreSQL
* Redis
* LLM Provider
* 搜索/工具 registry
* 审计

### `policy/`

把 actor、quota、risk、approval 从散乱逻辑中抽出来，变成统一规则引擎。

## 5.4 API 重构硬规则

* route 中不允许出现业务 SQL
* application 中不允许拼 HTTP response
* domain 中不允许依赖 FastAPI / Redis / HTTP request
* policy 必须可单独单测
* 所有高风险接口必须经过统一 permission / risk hook

---

# 六、Worker 重构方案

这是整个方案最关键的一部分。

## 6.1 Worker 重构目标

把当前 Worker 从“大一统后台执行脚本”，重构成**可分阶段理解、可局部测试、可单独治理的运行时内核**。

作者在现状总结中明确指出 Worker 的真实复杂度仍集中在 `worker_runtime_context.py`，规模在 4000 行量级，是主要技术债中心。([raw.githubusercontent.com](https://raw.githubusercontent.com/zanboclaw/ai-assistant/master/docs/next_ai.md))

## 6.2 Worker 目标目录结构

```text
apps/worker/
  worker.py

  bootstrap/
    worker_factory.py
    runtime_container.py
    config.py

  runtime/
    task_loading/
      load_task.py
      load_actor_context.py
      hydrate_session.py
      inject_memory.py
      prepare_workspace.py

    planning/
      build_intent_plan.py
      build_execution_plan.py
      revise_plan.py
      plan_schema.py

    execution/
      execute_plan.py
      execute_step.py
      step_state_machine.py
      checkpoint.py
      task_state_machine.py

    tools/
      tool_registry.py
      tool_dispatcher.py
      tool_validation.py
      tool_risk.py
      tool_audit.py

    recovery/
      interrupt_handler.py
      resume_handler.py
      clarify_handler.py
      recovery_actions.py
      recovery_decider.py

    delivery/
      assemble_deliverable.py
      validate_deliverable.py
      evaluator_bridge.py
      final_response_builder.py

    agents/
      agent_selector.py
      specialist_profiles.py
      agent_orchestrator.py
      agent_result_merger.py

    workflow/
      proposal_runtime.py
      shadow_validation.py
      rollback_runtime.py

  application/
    run_task.py
    recover_task.py
    rerun_task.py
    review_deliverable.py

  domain/
    task_runtime.py
    step_runtime.py
    deliverable.py
    recovery.py
    agent_run.py

  infrastructure/
    db/
      runtime_repo_pg.py
      queue_repo_pg.py
    queue/
      redis_queue.py
    providers/
      llm_runtime.py
    files/
      workspace_fs.py
    sandbox/
      shell_executor.py

  policy/
    execution_guard.py
    tool_permission_guard.py
    runtime_risk_guard.py
```

## 6.3 Worker 运行阶段模型

### 阶段 1：Task Loading

回答一个核心问题：
**开始执行前，系统到底拥有什么上下文？**

包括：

* 任务本体
* actor / governance context
* session state
* long-term memory
* 工作空间
* 工具上下文

README 已明确存在 session 与 long-term memory 相关能力，这里必须在 Worker 运行前显式注入，而不是临时散落读取。([github.com](https://github.com/zanboclaw/ai-assistant))

### 阶段 2：Planning

必须区分：

* **Intent Plan**：用户目标是什么
* **Execution Plan**：系统准备怎么执行

这两类 plan 不能混为一谈，否则恢复和重规划会非常混乱。

### 阶段 3：Execution

要定义显式步骤状态机，例如：

* pending
* ready
* running
* blocked
* waiting_clarification
* waiting_approval
* failed
* recoverable
* completed
* skipped

状态迁移必须对象化，不能散落在一堆 `if/else` 中。

### 阶段 4：Tools

工具调用必须升级为一个独立的“工具子平台”，具备：

* registry
* validation
* dispatch
* risk tagging
* audit

因为这个平台最终不是聊天机器人，而是执行系统。README 里也已把 tool registry 作为治理能力的一部分写清楚。([github.com](https://github.com/zanboclaw/ai-assistant))

### 阶段 5：Recovery

恢复必须被对象化。建议显式支持：

* retry current step
* regenerate plan
* request clarification
* request approval
* skip step
* fallback provider
* switch agent
* manual handoff

README 中的中断、恢复、clarify、apply-recovery-action 主链已经存在，这里应把它们沉淀为标准恢复机制。([github.com](https://github.com/zanboclaw/ai-assistant))

### 阶段 6：Delivery

要明确区分：

* execution result
* deliverable
* evaluator result

只有这样前端工作区才能真正展示“最终交付”，而不是只展示日志流。

### 阶段 7：Agents

多 Agent 必须与普通单任务执行解耦。
分成：

* selector
* orchestrator
* merger

README 已明确存在 multi-agent、evaluator、workflow proposal、shadow validation、rollback 等主干能力。([github.com](https://github.com/zanboclaw/ai-assistant))

### 阶段 8：Workflow / Rollback

workflow proposal、shadow validation、rollback 是治理链，不应混在普通执行逻辑中。

## 6.4 Worker 重构硬规则

* 任务状态机与步骤状态机必须文档化
* 工具调用必须带风险分类与审计
* 恢复动作必须有对象模型
* 多 Agent 不允许绕过普通治理链
* evaluator 结果必须能回溯到 deliverable

---

# 七、Web 前端重构方案

## 7.1 Web 重构目标

把当前前端从“工程控制台式大页面”，重构成**多域任务工作台**。

首页结构已清楚表明其方向是：

* 工作台
* 任务起草器
* 任务/工作区
* Sessions
* 治理
* 监控
* 设置
  并明确强调普通用户先完成任务，高权限用户再进入治理和运维。([raw.githubusercontent.com](https://raw.githubusercontent.com/zanboclaw/ai-assistant/master/apps/web/index.html))

## 7.2 Web 目标目录结构

```text
apps/web/
  index.html

  assets/
    styles/
      base.css
      layout.css
      components.css
      theme.css
    icons/

  js/
    app/
      bootstrap.js
      router.js
      state.js
      api_client.js
      event_bus.js

    domains/
      composer/
        composer_page.js
        composer_state.js
        composer_api.js
      workspace/
        workspace_page.js
        workspace_state.js
        workspace_api.js
      sessions/
        sessions_page.js
        sessions_state.js
        sessions_api.js
      governance/
        governance_page.js
        governance_state.js
        governance_api.js
      monitor/
        monitor_page.js
        monitor_state.js
        monitor_api.js
      settings/
        settings_page.js
        settings_state.js
        settings_api.js

    components/
      task_card.js
      task_timeline.js
      delivery_panel.js
      memory_hit_list.js
      actor_badge.js
      quota_meter.js
      risk_badge.js
      empty_state.js
      error_state.js
      loading_state.js
      confirm_dialog.js

    shared/
      formatters.js
      validators.js
      constants.js
```

## 7.3 前端域模型

### Composer

负责：

* 任务输入
* 澄清
* 草稿确认
* 正式任务转化

### Workspace

负责：

* 执行状态
* 步骤时间线
* 中断与恢复
* 最终交付
* reviewer / evaluator 结果

### Sessions

负责：

* session 浏览
* session state
* 会话回顾
* 任务关联

### Governance

负责：

* actor
* quota
* risk policy
* model routes
* tool registry
* rollback / change request

### Monitor

负责：

* runtime 概览
* worker / queue 健康度
* 关键指标

### Settings

负责：

* 环境
* 配置
* 版本信息

## 7.4 前端统一机制

前端必须统一以下 5 个基础机制：

### `api_client`

统一：

* base URL
* headers
* actor identity
* 错误处理
* retry 规则

### `state`

统一：

* 当前 actor
* 当前 task
* 当前选中的工作区视图
* 当前环境

### `router`

哪怕仍是静态页面，也必须有正式路由。

### 错误态 / 空态 / 加载态

统一组件化。

### 权限态

按钮、入口、页面都要统一处理权限不足与风险受限状态。

---

# 八、领域模型与共享契约方案

当前平台最大的长期风险之一，是 API、Worker、Web、DB 各自理解一套状态和字段。

因此必须建立统一共享契约。

## 8.1 建议沉淀的核心领域对象

* Task
* Step
* Session
* MemoryRecord
* Deliverable
* RecoveryAction
* GovernanceDecision
* WorkflowProposal
* AgentRun

## 8.2 共享内容

* 状态枚举
* API request / response schema
* Worker runtime payload schema
* Deliverable schema
* 审计事件 schema

## 8.3 契约放置位置

建议新增：

```text
core/
  contracts/
    task_contracts.py
    session_contracts.py
    governance_contracts.py
    workflow_contracts.py

  shared/
    enums.py
    exceptions.py
    ids.py
    result.py
    time.py
```

---

# 九、数据库与迁移方案

## 9.1 目标

彻底完成 migration-first 收口。

现状文档已经明确指出，这仍是当前重要缺口。([raw.githubusercontent.com](https://raw.githubusercontent.com/zanboclaw/ai-assistant/master/docs/next_ai.md))

## 9.2 目标结构

```text
db/
  migrations/
    0001_init_core_tables.sql
    0002_sessions.sql
    0003_long_term_memory.sql
    0004_governance_core.sql
    0005_workflow_runtime.sql
    0006_agent_runtime.sql
    0007_indexes.sql
    0008_constraints.sql
    0009_backfill_runtime_columns.sql

  seeds/
    seed_actor_roles.sql
    seed_tool_registry.sql
    seed_model_routes.sql

  schema_docs/
    task_model.md
    session_model.md
    governance_model.md
    workflow_model.md
```

## 9.3 数据治理规则

* migration 按业务域管理，不按零散修补命名
* 运行时只允许做 schema version 检查
* 禁止再做隐式 ensure
* 每张核心表必须有 owner
* 历史兼容列必须通过 migration/backfill 处理，不允许长期 runtime patch

---

# 十、测试体系重构方案

## 10.1 目标

把测试从“存在”升级为“能给重构提供护栏”。

当前仓库已经有 pytest、E2E、Playwright 和 CI，但覆盖率仍偏低。([github.com](https://github.com/zanboclaw/ai-assistant/tree/master/tests)) ([raw.githubusercontent.com](https://raw.githubusercontent.com/zanboclaw/ai-assistant/master/docs/next_ai.md))

## 10.2 目标结构

```text
tests/
  unit/
    api/
      application/
      policy/
    worker/
      planning/
      execution/
      recovery/
      delivery/
      agents/
    domain/
      task/
      session/
      governance/

  integration/
    api/
      test_intake_flow.py
      test_task_flow.py
      test_fast_path.py
      test_governance_flow.py
    worker/
      test_task_execution_flow.py
      test_recovery_flow.py
      test_deliverable_validation.py

  e2e/
    test_task_journey.spec.js
    test_recovery_journey.spec.js
    test_governance_journey.spec.js

  fixtures/
    tasks/
    sessions/
    memories/
    governance/
```

## 10.3 测试策略

### 单元测试

测纯逻辑：

* 状态机迁移
* policy 判断
* plan 生成
* deliverable 校验

### 集成测试

测模块协作：

* API + DB + Redis
* Worker + Queue + DB
* Governance + Workflow

### E2E

测真实旅程：

* 任务起草到交付
* 中断到恢复
* change request 到 rollback

## 10.4 测试准入规则

* 任何改动状态机的 PR 必须补对应测试
* 任何改动 schema 的 PR 必须补 migration 测试
* 任何新增高风险工具的 PR 必须补风险与权限测试
* 任何前端关键旅程改动必须补 E2E

---

# 十一、治理与安全方案

## 11.1 治理目标

把治理从“概念存在”重构成“全链路受控”。

README 已明确说明系统包含 actor、quota、risk policy、tool registry、change request、shadow validation、rollback。([github.com](https://github.com/zanboclaw/ai-assistant))

## 11.2 需要固化的治理对象

* Actor
* Role
* Permission
* Quota
* RiskLevel
* ApprovalRequirement
* AuditEvent
* ChangeRequest
* RollbackRecord

## 11.3 治理落地点

### API 层

* 所有高风险接口必须走 permission guard
* 所有变更类接口必须写审计
* CORS 与开放策略必须环境化，不允许默认无限开放

### Worker 层

* 工具调用必须经过风险守卫
* 受限动作必须可审批/可拒绝
* 恢复动作必须审计
* 多 Agent 执行不得绕过治理

### 前端层

* 权限不足按钮统一态
* 高风险动作必须有显式确认
* 审批与回滚必须可解释

---

# 十二、观测与运维方案

## 12.1 目标

把“系统能跑”升级为“系统可观测、可诊断、可发布”。

仓库已经具备 Compose、CI、运维文档、release checklist、runtime version check 等基础，但现状文档点出了部署一致性仍需收口。([github.com](https://github.com/zanboclaw/ai-assistant)) ([raw.githubusercontent.com](https://raw.githubusercontent.com/zanboclaw/ai-assistant/master/docs/next_ai.md))

## 12.2 必须补齐的能力

* `/healthz`
* `/readyz`
* `/version`
* build metadata 输出
* schema version 输出
* queue / worker 健康指标
* 审计事件检索
* 任务执行链 tracing

## 12.3 核心指标

### 产品指标

* 任务完成率
* 平均恢复次数
* Fast Path 使用率
* 交付采纳率

### 技术指标

* Worker 失败率
* 恢复成功率
* 平均执行时长
* 高风险动作审批率
* rollback 触发率

---

# 十三、文档与 ADR 方案

当前 docs 已经很多，但要从“资料多”变成“架构知识可继承”。([github.com](https://github.com/zanboclaw/ai-assistant/tree/master/docs))

## 建议新增结构

```text
docs/
  architecture/
    system_context.md
    api_architecture.md
    worker_architecture.md
    web_architecture.md
    runtime_state_machine.md
    governance_model.md

  adr/
    0001_runtime_state_machine.md
    0002_migration_first.md
    0003_policy_layer.md
    0004_frontend_domain_split.md
```

## 文档要求

* 状态机必须文档化
* 目录边界必须文档化
* 高风险动作流必须文档化
* 关键 ADR 必须和代码同步更新

---

# 十四、建议的整仓目标结构

```text
ai-assistant/
  apps/
    api/
      bootstrap/
      routes/
      application/
      domain/
      infrastructure/
      policy/
      schemas/
      main.py

    worker/
      bootstrap/
      runtime/
      application/
      domain/
      infrastructure/
      policy/
      worker.py

    web/
      assets/
      js/
        app/
        domains/
        components/
        shared/
      index.html

    scheduler/
      jobs/
      bootstrap/
      scheduler.py

  core/
    shared/
      enums.py
      exceptions.py
      ids.py
      time.py
      result.py
    contracts/
      task_contracts.py
      session_contracts.py
      governance_contracts.py
      workflow_contracts.py

  db/
    migrations/
    seeds/
    schema_docs/

  docs/
    architecture/
    adr/
    runbooks/
    release/

  tests/
    unit/
    integration/
    e2e/
    fixtures/

  scripts/
    dev/
    release/
    migration/
    verify/

  docker/
    api/
    worker/
    web/
    scheduler/
```

---

# 十五、实施顺序方案

你不要理解成时间线，而是理解成**依赖顺序**。
也就是哪些必须先做，哪些必须后做。

## 第一层：先立骨架

先建立：

* API 新分层骨架
* Worker runtime 分区骨架
* Web domain 分区骨架
* core/contracts 与 shared
* db migration 规范骨架

这一步先不追求迁完业务，只追求新结构成立。

## 第二层：迁主链

优先迁：

* intake
* confirm
* task
* fast-path
* worker task loading / planning / execution / recovery
* governance 的高风险接口

因为这些是平台闭环的核心。

## 第三层：迁增强链

再迁：

* session
* long-term memory
* deliverable
* evaluator
* agents
* workflow proposal / shadow validation / rollback

## 第四层：清旧逻辑

最后才做：

* runtime ensure 下线
* 旧装配胶水删除
* dashboard 大脚本主逻辑删除
* 历史兼容入口删除

---

# 十六、完成标准

只有满足下面这些条件，这次重构才算成功。

## 16.1 架构完成标准

* API 不再以超级装配文件承载主要复杂度
* Worker 状态机被拆成显式运行阶段
* Web 不再由单一主脚本承载跨域逻辑
* Domain / Policy / Infrastructure 边界清晰

## 16.2 工程完成标准

* migration-first 完整落地
* 运行时不再隐式补表补列
* 核心链路具备自动化回归护栏
* 发布不再依赖人工同步容器代码

## 16.3 产品完成标准

* 用户可以顺畅完成：输入 → 确认 → 执行 → 恢复 → 交付
* 治理角色可以顺畅完成：审批 → 风险控制 → 回滚
* 工作台不再像工程面板，而是像任务系统

## 16.4 治理完成标准

* 高风险接口全量受控
* 工具调用全量可审计
* 恢复与回滚可回溯
* 多 Agent 受治理规则约束

---

# 十七、必须避免的反模式

## 1. 继续往超级文件里加逻辑

这是当前最大技术债来源之一。([raw.githubusercontent.com](https://raw.githubusercontent.com/zanboclaw/ai-assistant/master/docs/next_ai.md))

## 2. 用 `utils/helpers/common/misc` 吞掉复杂度

这会让目录重构失效。

## 3. 一边重构，一边继续大规模横向加新功能

这会导致结构永远收不住。

## 4. 不建立共享契约，继续各层各自理解状态

这会让前后端与 Worker 越来越难协同。

## 5. 不做审计和权限矩阵，就继续扩工具能力

这会直接削弱平台的“治理型执行系统”定位。

---

# 十八、最终结论

这次重构方案的本质不是“整理代码”，而是完成四件事：

**第一，把平台主链变成可控资产。**
当前系统已经具备平台能力雏形，但还需要通过测试、迁移、权限和发布一致性，把它变成可放心演进的系统。([github.com](https://github.com/zanboclaw/ai-assistant)) ([raw.githubusercontent.com](https://raw.githubusercontent.com/zanboclaw/ai-assistant/master/docs/next_ai.md))

**第二，把复杂度从几个超级文件里释放出来。**
当前真正危险的不是功能少，而是复杂度集中。([raw.githubusercontent.com](https://raw.githubusercontent.com/zanboclaw/ai-assistant/master/docs/next_ai.md))

**第三，把执行平台的状态机与治理边界显式化。**
这个项目不是普通 CRUD 系统，必须按执行状态机和治理链来设计。([github.com](https://github.com/zanboclaw/ai-assistant))

**第四，把前端从工程控制台推进成产品工作台。**
当前前端方向已经正确，但仍需结构化产品化收口。([raw.githubusercontent.com](https://raw.githubusercontent.com/zanboclaw/ai-assistant/master/apps/web/index.html))