# ai-assistant 完整落地方案

## 1. 目标与定位

本方案的目标，是在**保留现有 ai-assistant 控制面能力**的前提下，引入更强的执行面、记忆系统、工具生态、Skills 适配、可观测性与权限治理能力，把系统从：

- 可执行任务的平台
- 带审批、审计、checkpoint、proposal 的治理底座

推进成：

- **可治理的工作代理 runtime**
- **可承载专业 workflow pack 的平台**
- **具备最小长期记忆、MCP 工具生态、可观测性、细粒度权限和受控自扩展能力的系统**

### 1.1 设计原则

1. **保留现有控制面**
   - 不推翻现有 `task_runs / task_steps / approval / audit / checkpoint / tool registry` 主链。
   - PostgreSQL + Redis 继续作为唯一状态中心。

2. **增强执行面**
   - 引入 graph/state 风格执行模型。
   - 引入多轮 tool-use loop、memory injection、MCP、Skill Runtime。

3. **统一治理**
   - 所有新增能力都必须进入统一的风险控制、审批、审计、配额与权限体系。

4. **渐进演进**
   - 不做一次性重写。
   - 优先做高收益、低破坏的增强。

5. **Skill 一等公民化**
   - Skill 不是提示词模板，而是可复用、可版本化、可审计、可执行、可组合的能力包。

### 1.2 明确不做的事

- 不全量替换现有 worker 主链
- 不新建第二套状态中心
- 不一次做多个专业 pack
- 不一开始就做完全自动自修改
- 不提前做企业级全栈低代码平台

---

## 2. 总体架构

建议将系统拆为五层。

### 2.1 接入层

负责所有用户与系统入口：

- Web UI
- CLI
- API
- 消息平台入口（后续可接企业微信、Telegram、邮件）
- 定时任务触发器

### 2.2 控制层（保留并增强现有 ai-assistant）

负责流程治理与状态管理：

- Task API
- Approval API
- Audit API
- Tool Registry
- Skill Registry
- Risk Policy Engine
- Quota / Usage Control
- Task Scheduler
- Model Routing
- Checkpoint / Resume Orchestrator
- Change Request / Proposal Bridge

### 2.3 执行层（新增 Agent Runtime）

负责具体任务执行：

- Planner / Executor Graph
- Tool-use Loop
- Skill Invocation Router
- Skill Context Loader
- Memory Injection
- Retrieval Service
- MCP Tool Adapter
- Built-in Tool Runner
- Generated Tool Sandbox
- Self-check / Diagnose / Repair Worker

### 2.4 资源层

负责能力包与复用资产：

- Skill Packages
- Prompt Templates
- Tool Specs
- Reference Docs
- Policy Bundles
- Output Templates

### 2.5 基础设施层

- PostgreSQL
- Redis
- Object Storage
- Vector DB（推荐 Qdrant）
- Observability / Tracing（推荐 Langfuse）
- AuthZ Service（先 Casbin，后续可演进到 OpenFGA）

---

## 3. 设计目标拆解

### 3.1 执行可靠性

系统需要支持：

- 长任务执行
- 多步骤任务断点恢复
- 失败重试
- 审批中断后继续执行
- 定时任务发起标准任务流

### 3.2 Agent 能力增强

系统需要支持：

- 多轮 tool-use loop
- 更强的 planner / executor
- 结构化状态图执行
- 上下文检索注入
- 长期记忆召回
- MCP 工具生态接入
- Skill 驱动的任务复用

### 3.3 治理增强

系统需要支持：

- 高风险操作审批
- 工具级风险分级
- Skill 级权限与审批
- 细粒度访问控制
- 完整审计日志
- Prompt / Model / Tool / Skill 级追踪
- 配额与速率限制

### 3.4 可扩展性

系统需要支持：

- 新工具快速接入
- MCP Server 注册
- Skill 包注册与升级
- 运行时生成工具草稿
- 多模型提供商路由
- 多租户或多团队隔离

### 3.5 工作流复用

系统需要支持：

- 把高频任务固化成 Skills
- Skill 组合调用 Tool / MCP / Memory
- 不同团队共享受控 Skill
- Skill 版本升级与灰度启用
- Skill 结果格式标准化

---

## 4. 核心能力设计

### 4.1 Agent Runtime Graph

在 worker 内部引入 Graph 风格执行模型作为执行引擎。

典型节点：

1. Load task context
2. Load working memory
3. Retrieve long-term memory
4. Detect applicable skill
5. Load skill instructions and resources
6. Plan next action
7. Evaluate risk
8. Request approval if needed
9. Execute skill or tool
10. Summarize result
11. Persist checkpoint
12. Decide continue or finish

#### 价值

- 执行路径清晰
- 更适合中断与恢复
- 更适合插入审批节点
- 更适合 trace 和 replay
- 更适合把 Skill 纳入执行图，而不是外挂在对话层

### 4.2 Tool-use Loop

在单个步骤内部支持多轮工具调用。

#### 能力要求

- 多轮工具调用
- 自动重试
- 工具失败回退
- 每轮输出写入 step trace
- 最大调用轮数控制
- 风险动作拦截

#### 约束

- 高风险工具必须经过 Risk Policy
- 工具调用必须带 trace_id
- 所有输入输出都要写 trace 或审计

### 4.3 长期记忆系统

采用三层记忆：

#### Layer 1: Session Working Memory

短期工作记忆，和当前任务强相关：

- 当前任务摘要
- 最近几步执行结果
- 用户即时偏好
- 当前上下文缓存

#### Layer 2: Compressed Long-term Memory

长期摘要化记忆：

- 用户偏好
- 稳定事实
- 常用工作模式
- 历史任务经验总结
- 常用 Skill 触发偏好

#### Layer 3: Vector Retrieval Memory

语义检索记忆：

- 历史任务摘要
- 项目资料切片
- 常用工具调用范例
- 常用 Skill 样例
- 结构化知识片段

统一由 `memory_service` 提供读写接口。

### 4.4 MCP 工具生态

把 MCP 工具纳入一等公民能力。

#### Tool Registry 扩展字段

- `provider_type`
- `transport`
- `server_name`
- `provider_config`
- `capabilities`
- `risk_level`
- `enabled`
- `owner`
- `approval_required`

#### 支持的工具类型

- `builtin`
- `local_python`
- `mcp_stdio`
- `mcp_http`
- `generated_tool`

#### 调用流程

1. Planner 产生工具意图
2. Tool Registry 查询工具元数据
3. Risk Engine 计算风险
4. 需要审批则暂停
5. 通过 adapter 调用 MCP 或本地工具
6. 写 trace 和审计日志

### 4.5 Skills 适配

Skill 被设计为平台内“可复用、可执行、可治理”的能力包，而不是单纯一段长 prompt。

#### Skill 的平台定位

Skill 应视为：

- 一组可复用指令
- 一组辅助资源（references / templates / scripts / assets）
- 一套触发条件
- 一组约束规则
- 一个可审计的执行单元

#### Skill 解决的问题

适合固化成 Skill 的任务：

- 周报 / 日报 / 复盘模板
- 客户沟通总结
- 文档起草规范
- 数据分析流程
- 合规审查流程
- 特定系统操作 SOP
- 多步执行且模式稳定的工作流

#### Skill Registry

建议新增 `Skill Registry`，与 `Tool Registry` 平行存在。

建议字段：

- `skill_id`
- `name`
- `display_name`
- `description`
- `version`
- `package_uri`
- `entrypoint`
- `trigger_rules`
- `owner`
- `team_id`
- `status`
- `risk_level`
- `required_tools`
- `required_connectors`
- `required_permissions`
- `tags`
- `created_at`
- `updated_at`

#### Skill Package 结构建议

```text
skill-name/
├── SKILL.md
├── agents/
│   └── openai.yaml
├── scripts/
├── references/
└── assets/
```

#### Skill Invocation Router

负责判断是否启用某个 Skill。判断维度：

- 用户意图
- 当前任务类型
- 历史偏好
- 团队上下文
- 可访问 Skill 范围
- 当前启用的工具 / 连接器
- 风险等级

#### Skill Runtime

Skill 被命中后采用渐进加载：

1. 先读 metadata
2. 再读 `SKILL.md`
3. 需要时加载 references
4. 需要时执行 scripts
5. assets 只在产物生成时使用

#### Skill 与 Tool 的关系

- Skill 可以调用 Tool
- Skill 可以引用 Memory
- Skill 可以指定输出模板
- Skill 可以要求特定审批策略
- Tool 不直接依赖 Skill
- Skill 不等于 Tool

#### Skill 权限与审批

控制项包括：

- 谁能创建 Skill
- 谁能编辑 Skill
- 谁能发布 Skill
- 谁能启用 Skill
- 哪些 Skill 仅团队内可用
- 哪些 Skill 调用高风险工具时必须双重审批

#### Skill Trace

新增 Skill 级 trace：

- 命中了哪个 Skill
- 加载了哪些文件
- 执行了哪些脚本
- 引导了哪些 Tool 调用
- 是否使用输出模板
- 是否触发审批

#### Skill 与 Memory 协同

- 记录用户常用 Skill
- 记录某类任务常配 Skill
- 统计 Skill 成功率
- 根据历史成功案例推荐 Skill
- Skill few-shot 样例向量化

### 4.6 可观测性

审计日志不能替代 LLM 可观测系统。建议单独建设 tracing 与 evaluation 层。

#### 观测对象

- task trace
- step trace
- model call trace
- prompt version
- tool call trace
- skill invocation trace
- skill resource loading trace
- retrieval trace
- approval wait trace
- retry trace

#### 支持能力

- 失败任务回放
- prompt 版本对比
- Skill 版本对比
- 模型路由效果对比
- 工具成功率统计
- Skill 成功率统计
- 审批耗时统计
- retrieval 命中质量评估

### 4.7 权限治理

采用分阶段策略。

#### Phase 1

先用 Casbin 做最小权限控制：

- `user / team / assistant / task / tool / skill / memory_space`
- `read / create / update / execute / approve / reject / publish / manage`

#### Phase 2

后续演进到 OpenFGA，支持关系型授权：

- 用户属于团队
- 团队拥有 Skill
- Skill 引用 Tool
- Task 继承 Assistant 权限
- Memory scope 与 Team / Project / User 关联

### 4.8 Generated Tool 与 Generated Skill

必须受控，不能直通生产。

#### Generated Tool

仅允许：

- 生成草稿
- 静态检查
- sandbox 测试
- 风险评估
- 审批后上线

#### Generated Skill

仅允许：

- 生成 draft 包
- 人工补充 metadata / policy / risk level
- 测试通过后发布
- 版本升级必须经过审批

### 4.9 Self-check / Diagnose / Repair

建立最小自修复链路：

1. 失败任务进入诊断队列
2. Diagnose Worker 汇总失败模式
3. 生成 `diagnostic_report`
4. 提供 repair action 建议
5. 允许提交 change request / generated tool / generated skill draft
6. 审批后进入 sandbox 验证

---

## 5. 核心数据模型

### 5.1 保留现有表

- `task_runs`
- `task_steps`
- `approval_requests`
- `audit_logs`
- `tools`
- `tool_versions`
- `model_routes`
- `quota_usage`
- `change_requests`

### 5.2 新增表

#### 记忆相关

- `memory_items`
- `memory_embeddings`
- `memory_preferences`
- `memory_facts`
- `memory_summaries`

#### 可观测相关

- `task_traces`
- `step_traces`
- `model_traces`
- `tool_traces`
- `skill_traces`
- `retrieval_traces`

#### 调度相关

- `scheduled_jobs`
- `job_runs`

#### Skill 相关

- `skills`
- `skill_versions`
- `skill_usage_stats`
- `skill_resources`

#### 工具治理相关

- `tool_providers`
- `tool_capabilities`
- `generated_tool_drafts`
- `generated_skill_drafts`

#### 诊断修复相关

- `diagnostic_reports`
- `repair_actions`

---

## 6. 关键执行流程

### 6.1 标准任务执行流程

1. API 创建 `task_run`
2. 写入 Redis 队列
3. Worker claim 任务
4. 加载任务上下文
5. 注入 session working memory
6. 检索 long-term / retrieval memory
7. 匹配适用 Skill
8. 载入 Skill metadata / instructions
9. Planner 生成下一步动作
10. Risk Engine 评估风险
11. 若高风险，创建 `approval_request`
12. 审批通过后执行 tool / skill action
13. 写入 trace
14. 更新 checkpoint
15. 判断继续或完成
16. 生成最终摘要
17. 写入审计与 memory sink

### 6.2 审批中断恢复流程

1. 执行到高风险动作
2. 任务状态切换为 `waiting_approval`
3. 保存 runtime snapshot
4. 人工审批通过
5. Worker 收到 resume signal
6. 从 snapshot 恢复上下文
7. 从中断节点继续执行
8. 补写审计和 trace

### 6.3 定时任务流程

1. `scheduled_jobs` 保存 cron
2. 调度器触发时只创建标准 `task_run`
3. 后续完全走普通任务主链
4. 同样经过 risk / approval / audit / checkpoint

### 6.4 Tool-use Loop

在单个 step 内支持多轮调用：

- 最大轮数限制
- 每轮写 trace
- 工具失败自动重试
- 高风险动作强制过 risk gate
- 允许 fallback tool
- 超限时退出并总结

### 6.5 Memory 流程

- 任务中写 working memory
- 任务结束抽取 summary / preference / facts
- review 压缩为 long-term summary
- 检索时向 vector memory 取 top-k 注入

### 6.6 Skill 调用流程

1. 用户请求进入任务
2. Intent Router 判断任务模式
3. Skill Invocation Router 匹配候选 Skill
4. 权限系统判断是否允许调用
5. Runtime 按渐进加载策略载入 Skill
6. Skill 指导 planner 生成动作
7. Tool / MCP 调用受 risk policy 控制
8. 输出按 Skill 模板收敛
9. Skill 调用结果计入 usage stats / trace / audit

---

## 7. 技术选型

### Runtime

先保持自研 graph/state 驱动，不做全量 LangGraph 替换。

### Vector DB

Qdrant

### Observability

Langfuse

### AuthZ

第一阶段 Casbin，后续评估 OpenFGA。

### MCP

先支持 `mcp_stdio` 和 `mcp_http`。

---

## 8. 建议目录结构

```text
ai-assistant/
├─ apps/
│  ├─ api/
│  ├─ worker/
│  ├─ web/
│  └─ cli/
├─ core/
│  ├─ agent_runtime/
│  │  ├─ graph/
│  │  ├─ planner/
│  │  ├─ executor/
│  │  ├─ risk_gate/
│  │  ├─ resume/
│  │  └─ state.py
│  ├─ memory/
│  │  ├─ working_memory.py
│  │  ├─ long_term_memory.py
│  │  ├─ retrieval_memory.py
│  │  └─ memory_service.py
│  ├─ tools/
│  │  ├─ builtin/
│  │  ├─ mcp/
│  │  ├─ generated/
│  │  ├─ registry/
│  │  └─ sandbox/
│  ├─ skills/
│  │  ├─ registry/
│  │  ├─ runtime/
│  │  ├─ importer/
│  │  ├─ authoring/
│  │  └─ packaging/
│  ├─ approvals/
│  ├─ audit/
│  ├─ authz/
│  ├─ observability/
│  ├─ routing/
│  ├─ scheduling/
│  └─ diagnostics/
├─ infra/
│  ├─ compose/
│  ├─ migrations/
│  ├─ prompts/
│  └─ policies/
├─ docs/
├─ scripts/
└─ tests/
```

---

## 9. 风险与取舍

### 9.1 绝不允许双状态中心

不能让新 runtime 再维护一套任务状态机。唯一状态中心继续是 PostgreSQL + Redis + `task_runs/task_steps/checkpoint`。

### 9.2 高风险工具不能绕过审批

无论 builtin、MCP、generated tool、Skill，均必须经过 risk gate。

### 9.3 Skill 不得越权

Skill 只是能力封装，不是权限绕过机制。Skill 只能在允许的 Tool、Connector、Memory 和策略边界内执行。

### 9.4 三层记忆先做最小可用

先跑通 working memory、long-term summary、vector retrieval，再扩展。

### 9.5 Generated Tool / Skill 必须先 draft

不能让系统直接生成工具或 Skill 后直通生产。

### 9.6 不要同时做多个专业 pack

先证明一个，再扩展。

---

## 10. 专业 pack 选择建议

建议优先做 **Research / Analysis pack**，不要先做金融交易，也不要先做全自动 App Builder。

### 原因

- 最容易体现“模糊任务 -> workflow -> 治理”的价值
- 对 memory、retrieval、approval、citation 的需求天然强
- 比 App Builder 风险低
- 比金融交易更容易先做出可信效果

### 最小流程

1. 用户输入模糊问题
2. 系统澄清范围
3. 检索资料
4. 汇总分析
5. 生成结构化报告
6. 高风险领域触发人工复核
7. 写入记忆与复盘

等这个 pack 打稳，再做 App Builder pack。

---

## 11. 实施顺序建议

按照下面顺序推进最稳：

1. **先 tracing 和 MCP**
2. **再最小 memory**
3. **再 authz 和审批策略**
4. **最后做 generated tool / generated skill / self-healing**

也就是：

- **P0：可观测**
- **P1：可记忆**
- **P2：可治理**
- **P3：可进化**

这个顺序最适合当前项目，也最适合单人开发的现实节奏。
