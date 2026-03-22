# 增强版 ai-assistant 方案（含 Skills 适配）

## 1. 目标

本方案的目标，是在保留现有 `ai-assistant` 控制面能力的前提下，引入更强的 Agent Runtime、记忆系统、工具生态、Skills 适配、可观测性与权限治理能力，使系统从“可执行任务的平台”升级为“可治理、可恢复、可扩展、可长期记忆、可复用工作流的智能助理平台”。

核心原则：

1. **保留现有控制面**  
   不推翻现有 `task_runs / task_steps / approval / audit / checkpoint / tool registry` 思路。

2. **增强执行面**  
   把更强的 tool-use loop、graph runtime、memory injection、MCP 工具、Skills 能力接入 worker 执行链路。

3. **统一治理**  
   所有新增能力都必须纳入统一的风险控制、审批、审计、权限与配额体系。

4. **渐进演进**  
   优先做高收益、低破坏的增强，不做一次性重写。

5. **Skill 一等公民化**  
   Skills 不只是提示词模板，而应成为受控、可版本化、可审计、可执行、可组合的平台能力。

---

## 2. 总体架构

增强版系统建议拆为五层：

### 2.1 接入层
负责所有用户与系统入口：

- Web UI
- CLI
- API
- 消息平台入口（未来可接企业微信、Telegram、邮件等）
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
负责持久化与支撑能力：

- PostgreSQL
- Redis
- Object Storage
- Vector DB（推荐 Qdrant）
- Observability / Tracing（推荐 Langfuse）
- AuthZ Service（推荐 OpenFGA，或先用 Casbin 过渡）

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
- MCP server 注册
- Skill 包注册与升级
- 运行时生成工具草稿
- 多种模型提供商路由
- 多租户或多团队隔离

### 3.5 工作流复用
系统需要支持：

- 把高频任务固化成 Skills
- Skill 组合调用 Tool/MCP/Memory
- 不同团队共享受控 Skill
- Skill 版本升级与灰度启用
- Skill 结果格式标准化

---

## 4. 建议引入的关键能力

## 4.1 Agent Runtime Graph

建议引入 Graph 风格执行模型作为 worker 内部执行引擎。

典型节点：

1. Load task context
2. Load working memory
3. Retrieve long-term memory
4. Detect applicable skill
5. Load skill instructions/resources
6. Plan next action
7. Evaluate risk
8. Request approval if needed
9. Execute skill/tool
10. Summarize result
11. Persist checkpoint
12. Decide continue / finish

这样做的好处：

- 执行路径清晰
- 更适合中断与恢复
- 更适合插入审批节点
- 更适合做 trace 和 replay
- 更适合把 Skill 纳入执行图，而不是外挂在对话外层

---

## 4.2 Tool-use Loop

在单个步骤内部，加入更强的多轮工具调用能力。

建议能力：

- 支持多轮工具调用
- 支持自动重试
- 支持工具失败回退
- 支持每轮输出写入 step trace
- 支持最大调用轮数控制
- 支持风险动作拦截

约束：

- 高风险工具必须先经过 Risk Policy
- 工具调用必须有 trace_id
- 所有输入输出要写审计或 trace

---

## 4.3 长期记忆系统

建议采用“三层记忆”：

### 层 1：Session Working Memory
短期工作记忆，和当前任务强相关。

内容：
- 当前任务摘要
- 最近几步执行结果
- 用户即时偏好
- 当前上下文缓存

### 层 2：Compressed Long-term Memory
长期摘要化记忆。

内容：
- 用户偏好
- 稳定事实
- 常用工作模式
- 历史任务经验总结
- 常用 Skill 触发偏好

### 层 3：Vector Retrieval Memory
语义检索记忆。

内容：
- 历史任务摘要
- 项目资料切片
- 常用工具调用范例
- 常用 Skill 样例
- 结构化知识片段

建议统一由 `memory service` 提供读写接口。

---

## 4.4 MCP 工具生态

建议把 MCP 工具纳入一等公民能力。

Tool Registry 增加字段：

- `provider_type`
- `transport`
- `server_name`
- `provider_config`
- `capabilities`
- `risk_level`
- `enabled`
- `owner`
- `approval_required`

支持的工具类型：

- builtin
- local_python
- mcp_stdio
- mcp_http
- generated_tool

调用流程：

1. Planner 产生工具意图
2. Tool Registry 查询工具元数据
3. Risk Engine 计算风险
4. 需要审批则暂停
5. 通过 adapter 调用 MCP 或本地工具
6. 写 trace 和审计日志

---

## 4.5 Skills 适配（新增重点）

Skills 应被设计为平台内“可复用、可执行、可治理”的能力包，而不是单纯一段长 prompt。

### 4.5.1 Skill 的平台定位

Skill 本质上应被视为：

- 一组可复用指令
- 一组辅助资源（references / templates / scripts / assets）
- 一套触发条件
- 一组约束规则
- 一个可审计的执行单元

Skill 在平台中的角色应介于：

- Prompt Template 之上
- Tool / MCP 之下
- Workflow Policy 之旁

更直白地说：

- **Tool** 负责“做一个原子动作”
- **Skill** 负责“教系统如何完成一类任务”
- **Task** 负责“承载一次具体请求”
- **Agent Runtime** 负责“把 Skill、Tool、Memory 和审批串起来执行”

### 4.5.2 Skill 能解决的问题

适合固化成 Skill 的任务：

- 周报 / 日报 / 复盘模板
- 客户沟通总结
- 文档起草规范
- 数据分析流程
- 合规审查流程
- 特定系统操作 SOP
- 需要多步执行但模式稳定的工作流

Skill 不适合承载的内容：

- 高度动态、一次性逻辑
- 应该直接写进 tool code 的确定性操作
- 纯权限策略
- 纯数据本体

### 4.5.3 Skill Registry

建议新增 `Skill Registry`，与 `Tool Registry` 平行存在。

Skill Registry 负责：

- Skill 注册与发现
- 版本管理
- 元数据管理
- 启用/停用
- 权限边界
- 风险标记
- 所属团队 / 所属项目
- 发布状态（draft / active / deprecated / archived）

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

### 4.5.4 Skill Package 结构建议

建议兼容技能包目录结构：

```text
skill-name/
├── SKILL.md
├── agents/
│   └── openai.yaml
├── scripts/
├── references/
└── assets/
```

平台侧可做两种接入方式：

1. **External Skill Import**
   - 导入外部标准 Skill 包
   - 校验结构合法性
   - 写入 Skill Registry
   - 存储包文件到 object storage

2. **Internal Skill Authoring**
   - 通过 Web UI / CLI 创建平台内 Skill
   - 在线编辑 `SKILL.md`
   - 上传 references / templates / scripts
   - 自动打包成内部 Skill Package

### 4.5.5 Skill Invocation Router

新增 `Skill Invocation Router` 负责判断是否应启用某个 Skill。

判断维度：

- 用户意图
- 当前任务类型
- 历史偏好
- 团队上下文
- 可访问的 Skill 范围
- 当前启用的工具/连接器
- 风险等级

触发策略：

- 显式调用：用户明确指定 skill
- 隐式匹配：根据描述和触发规则自动命中
- 推荐模式：系统给出可用 skill 建议，由用户确认
- 强制模式：某些合规任务必须经过指定 skill

### 4.5.6 Skill Runtime

Skill 被命中后，不应直接拼接整包内容进上下文，而应采用渐进加载：

1. 先读 metadata
2. 再读 `SKILL.md`
3. 需要时再加载 references
4. 需要时再执行 scripts
5. assets 只在产物生成时使用

这样做的好处：

- 节省上下文
- 便于审计“到底用了哪些资源”
- 更适合权限检查
- 更适合失败排查

### 4.5.7 Skill 与 Tool 的关系

建议明确分层：

- Skill 可以调用 Tool
- Skill 可以引用 Memory
- Skill 可以指定输出模板
- Skill 可以要求特定审批策略
- Tool 不直接依赖 Skill
- Skill 不直接等于 Tool

推荐执行链路：

1. Task 创建
2. Runtime 匹配 Skill
3. Skill 载入指令与资源
4. Skill 指导 Planner 生成动作
5. Planner 调用 Tool / MCP / Retrieval
6. 高风险操作进入审批
7. 输出按 Skill 指定格式收敛

### 4.5.8 Skill 权限与审批

Skill 也要纳入治理，而不是“只要导入就能跑”。

建议控制项：

- 谁能创建 Skill
- 谁能编辑 Skill
- 谁能发布 Skill
- 谁能启用某个 Skill
- 哪些 Skill 只能在某团队内使用
- 哪些 Skill 调用高风险工具时必须双重审批

Skill 审批场景：

- 新 Skill 发布
- Skill 升级版本
- Skill 引入新 connector
- Skill 引入新 script
- Skill 请求高风险工具权限
- Skill 从私有变共享

### 4.5.9 Skill Trace 与审计

建议新增 Skill 级 trace：

- 命中了哪个 Skill
- 加载了哪些 Skill 文件
- 执行了哪些 Skill 脚本
- Skill 引导了哪些 Tool 调用
- 最终输出是否使用 Skill 模板
- Skill 是否触发审批

这对调试很关键，因为以后你会需要回答：

- 为什么这次系统用了这个 Skill？
- 这个 Skill 为什么会跑偏？
- 哪个版本的 Skill 导致输出质量下降？

### 4.5.10 Skill 与 Memory 的协同

可以把 Skill 也纳入长期记忆生态：

- 记录用户常用 Skill
- 记录某类任务常配 Skill
- 对 Skill 成功率做统计
- 让 planner 根据历史成功案例推荐 Skill

还可以做：

- Skill few-shot 样例向量化
- 历史高质量执行结果反哺 Skill 推荐
- 对不同团队维护不同 Skill 使用偏好

---

## 4.6 可观测性

现有审计日志不足以替代 LLM 可观测系统，建议单独建设 tracing 与 eval 层。

建议观测对象：

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

建议支持：

- 失败任务回放
- prompt 版本对比
- Skill 版本对比
- 模型路由效果对比
- 工具成功率统计
- Skill 成功率统计
- 审批耗时统计
- retrieval 命中质量评估

---

## 4.7 权限治理

建议把权限体系从“角色枚举”提升到“关系型授权”。

控制对象：

- user
- team
- assistant
- task
- approval request
- tool
- skill
- model provider
- memory space
- document source

控制动作：

- read
- create
- execute
- approve
- reject
- manage
- route
- register_tool
- register_skill
- publish_skill
- access_memory

这样可以做：

- 谁能审批哪个任务
- 哪个 agent 能用哪个工具
- 哪个团队能读哪个 memory space
- 哪些模型只能由管理员启用
- 哪些 Skill 只能在指定项目或团队中使用

---

## 5. 增强版目录设计

建议目录结构如下：

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
│  │  ├─ skills/
│  │  │  ├─ router.py
│  │  │  ├─ loader.py
│  │  │  ├─ runtime.py
│  │  │  └─ validator.py
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
│  │  ├─ packaging/
│  │  ├─ storage/
│  │  ├─ authoring/
│  │  └─ publishing/
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
│  ├─ policies/
│  └─ skills/
├─ scripts/
├─ docs/
└─ tests/
```

---

## 6. 数据模型建议

## 6.1 现有核心表继续保留

- `task_runs`
- `task_steps`
- `approval_requests`
- `audit_logs`
- `tools`
- `tool_versions`
- `model_routes`
- `quota_usage`

## 6.2 新增表建议

### memory 相关
- `memory_items`
- `memory_embeddings`
- `memory_facts`
- `memory_preferences`
- `memory_summaries`

### trace 相关
- `task_traces`
- `step_traces`
- `model_traces`
- `tool_traces`
- `skill_traces`
- `retrieval_traces`

### 调度相关
- `scheduled_jobs`
- `job_runs`

### 工具治理相关
- `tool_providers`
- `tool_capabilities`
- `generated_tool_drafts`
- `change_requests`

### skill 相关
- `skills`
- `skill_versions`
- `skill_packages`
- `skill_bindings`
- `skill_permissions`
- `skill_usage_stats`

### 诊断相关
- `diagnostic_reports`
- `repair_actions`

---

## 7. 核心流程设计

## 7.1 标准任务执行流程

1. API 创建 `task_run`
2. 写入 Redis 队列
3. Worker claim 任务
4. 加载任务上下文
5. 注入 working memory
6. 检索长期记忆
7. 匹配可用 Skill
8. 加载 Skill 元信息与必要资源
9. Planner 生成下一步动作
10. Risk Engine 评估风险
11. 若高风险则创建 `approval_request`
12. 若通过，则执行 Tool / Skill / MCP
13. 写 step trace / tool trace / skill trace
14. 更新 checkpoint
15. 判断继续执行或完成
16. 写最终摘要与审计日志

---

## 7.2 审批中断恢复流程

1. Worker 执行到高风险步骤
2. 生成 approval request
3. 任务状态变为 `waiting_approval`
4. 保存 runtime state snapshot
5. 记录当前 Skill 状态与资源指针
6. 审批通过后发 resume signal
7. Worker 重新加载 snapshot
8. 从中断节点继续执行
9. 补写 audit 和 trace

关键要求：
- snapshot 必须可重建执行状态
- prompt、tool context、retrieval context、skill context 要可复原
- 审批前后要有强一致的 task state 更新

---

## 7.3 定时任务流程

1. `scheduled_jobs` 保存 cron 规则
2. 调度器触发时不直接执行逻辑
3. 只创建标准 `task_run`
4. 之后完全走普通任务链路
5. 继续经过 skill / risk / approval / audit / checkpoint

这样可以避免调度任务绕开治理体系。

---

## 7.4 Skill 发布流程

1. 创建 Skill draft
2. 上传 `SKILL.md` 与相关资源
3. 运行结构校验
4. 运行脚本安全扫描
5. 绑定所需工具和 connector
6. 风险分级
7. 进入发布审批
8. 审批通过后生成新版本
9. 写入 Skill Registry
10. 按团队/环境启用

---

## 8. 分阶段实施路线

## 阶段 1：最小高收益增强
目标：在不破坏现有系统的情况下，提升执行表达力、工具扩展力与可观测性。

工作项：
- 新增 `core/agent_runtime`
- 把 worker 中的执行逻辑包装成 graph / state 驱动
- 增加 tool trace / model trace
- 增加 prompt version 记录
- Tool Registry 增加 MCP 类型支持
- 新增最小 Skill Registry
- 先支持只读式 Skill 导入与调用

交付结果：
- 任务执行可追踪
- 工具调用链更清晰
- 支持 MCP 工具接入
- 支持基础 Skill 发现与调用
- 为后续记忆与权限扩展打基础

---

## 阶段 2：记忆系统与 Skill 适配增强
目标：让助理具备长期记忆和 Skill 驱动复用能力。

工作项：
- 引入 memory service
- 增加 working / long-term / retrieval 三层记忆
- 接入向量库
- 为用户、团队、项目建立 memory scope
- 在 planner 执行前自动注入 Top-K memory
- Skill 支持渐进加载 references / scripts
- 记录 Skill usage stats

交付结果：
- 系统能记住用户偏好
- 历史任务经验可召回
- Skill 与记忆协同增强任务复用

---

## 阶段 3：权限与审批治理升级
目标：把治理能力做扎实。

工作项：
- 引入关系型授权服务或 Casbin 过渡方案
- 为 tool / skill / memory / approval 建立细粒度权限模型
- 为工具和模型增加风险等级和访问限制
- Skill 发布流程纳入审批
- Skill 升级、共享、跨团队使用纳入治理

交付结果：
- 不同角色拥有不同执行边界
- 高风险工具真正做到受控调用
- Skill 变成真正可治理的共享能力包

---

## 阶段 4：自修复与受控自扩展
目标：增强平台韧性与进化能力。

工作项：
- 新增 self-check 任务
- 新增 failed task diagnose
- 新增 generated tool draft 流程
- 新增 generated skill draft 流程
- 增加 change request + test + approval 上线机制
- 支持受控的 runtime tool / skill generation

交付结果：
- 平台可以自动发现故障
- 工具扩展能力更强
- Skill 体系能持续演进
- 自我进化被纳入治理闭环

---

## 9. 风险控制原则

### 9.1 不做双状态中心
不能让 Agent Runtime 自己再维护一套任务状态机。  
唯一状态中心应继续是 PostgreSQL + Redis + `task_runs/task_steps/checkpoint`。

### 9.2 不允许绕过审批
任何高风险工具，即使来自 MCP、generated tool、generated skill 或 builtin tool，也必须先过风险门禁。

### 9.3 不允许直接上线生成工具或 Skill
运行时生成工具或 Skill 只能先形成 draft。  
必须经过：
- 静态检查
- 单元测试
- 风险评级
- 人工审批
- 注册发布

### 9.4 不把 observability 和 audit 混为一谈
审计日志面向合规与追责。  
trace / eval 面向调试与性能优化。  
两者都需要，但职责不同。

### 9.5 Skill 不能直接突破平台边界
Skill 只能在平台允许的 Tool、Connector、Memory 和权限边界内执行。  
Skill 不是越权机制，只是能力封装机制。

---

## 10. 推荐技术栈

### 必选
- PostgreSQL
- Redis
- Python worker stack
- Web UI
- 标准化 audit logs

### 强烈建议
- Qdrant：向量检索
- Langfuse：LLM tracing / prompt / eval
- OpenFGA：细粒度授权
- MCP adapters：工具生态扩展
- Skill package validator：技能包校验与导入

### 视阶段引入
- Graph runtime
- Durable workflow 方案
- Generated tool sandbox
- Generated skill sandbox
- Internal skill authoring UI

---

## 11. 最终形态

增强版 `ai-assistant` 的最终形态，不应只是“一个能跑任务的平台”，而应具备以下特征：

- 像任务平台一样可治理
- 像 agent 一样有执行力
- 像长期助理一样有记忆
- 像技能平台一样能复用工作流
- 像工程系统一样可追踪
- 像生产系统一样可恢复
- 像受控平台一样可审计、可审批、可扩展

简化理解：

- **ai-assistant 继续做控制面**
- **增强模块负责执行面**
- **Skill / Tool / Memory / 权限 / 可观测构成平台化能力底座**

---

## 12. 建议的下一步输出

在这份方案基础上，下一步最适合继续产出的文档有三类：

1. **数据库表结构草案**
   - 各新增表字段设计
   - 主外键关系
   - 索引建议
   - 审批 / trace / memory / skill 表拆分方案

2. **目录级重构任务清单**
   - 先创建哪些目录
   - 先改哪些模块
   - 每阶段的 PR 切分建议
   - 回滚策略

3. **Skill 适配专项设计**
   - Skill Registry 设计
   - Skill Package 校验流程
   - Skill Runtime 执行流程
   - Skill 与 Tool / MCP / Memory / Approval 的边界协议
