# 当前状态、下一步行动方案与最终目标

## 1. 这份文档解决什么问题

这份文档的目标，是把下面四件事一次说清楚：

- 当前项目已经完成到什么程度
- 当前项目现在真实能做什么
- 下一步准备做什么、准备怎么做
- 项目最终想达到的完成效果是什么

它不是替代路线图，也不是替代 runbook，而是给当前推进节奏提供一个统一、可执行、可汇报的口径。

---

## 2. 当前项目真实进度

截至当前仓库状态：

- Stage 1：已完成
- Stage 2：已完成
- Stage 3：已完成
- Stage 4：已完成
- Stage 5：已完成
- Stage 6：已完成
- Stage 7：已完成

当前版本口径以 `version.json` 为准：

- `current_version = stage7-safe-self-modification-mainline`
- `stage_1_mvp = completed`
- `stage_2_stabilization = completed`
- `stage_3_assistantization = completed`
- `stage_4_governance_foundation = completed`
- `stage_5_multi_agent_layer = completed`
- `stage_6_evaluation_and_self_improvement = completed`
- `stage_7_safe_self_modification_and_rollback = completed`

当前 `monitor/overview.readiness_metrics.stage7` 已经稳定返回：

- `groundwork_active = true`
- `groundwork_completed = true`
- `operational = true`
- `overall_completed = true`
- `completed = true`
- `completion_ratio = 1.0`
- `missing_completion_gates = []`

这意味着：

- 当前仓库不是“正在准备进入 Stage 7”
- 也不是“Stage 7 groundwork 完成但整体未完成”
- 而是 Stage 7 已经在当前仓库定义下完成收口

---

## 3. 当前项目现在真实能做什么

### 3.1 任务执行与恢复

当前系统已经可以：

- 接收自然语言任务
- 自动拆分步骤并执行工具
- 在高风险步骤触发审批
- 在审批后恢复执行
- 在失败后按策略重试
- 通过 checkpoint / interrupt / resume 恢复长任务
- 用 Web / CLI / API 三种方式操作任务

### 3.2 助理化能力

当前系统已经具备：

- sessions / state / review / daily review
- session working memory 的最小闭环
- review 与 state 的补齐、健康检查与脚本化验收

### 3.3 治理能力

当前系统已经具备：

- change request
- audit log
- access actors / quotas
- tool registry
- model providers / model routes
- risk policies
- 强制治理门禁

### 3.4 多 Agent / 评估 / 自改进

当前系统已经具备：

- runtime fan-out / execute / fan-in
- evaluator
- workflow proposal
- workflow proposal -> change request bridge
- shadow validation

### 3.5 受控自修改与回滚

当前系统已经具备：

- workflow-improvement change request
- task-scoped runtime overrides
- candidate overlay + `payload_hash` 精确门禁
- patch artifact / rollback artifact
- rollback draft / rollback apply
- `sandbox_file` source-copy / source-patch / apply / rollback
- acceptance / auto rollback
- workflow proposal -> `sandbox_file` bridge

一句话总结：

**当前项目已经是一个可运行、可治理、可恢复、可审计、可评估、可受控自修改的 AI Assistant 平台原型。**

---

## 4. 当前还没做完的，不是 Stage 7，而是下一轮平台增强

虽然 Stage 7 已完成，但这不代表平台终局已完成。

当前还没有进入系统化落地的能力主要是：

- 全量 trace / replay / prompt-model-tool 可回放体系
- MCP 一等公民接入
- Skill Registry 最小闭环
- 长期记忆与 retrieval 体系
- 更细粒度的 AuthZ / 审批策略分层
- 持续实验、收益评估与长期优化闭环

也就是说，下一步不是“继续补 Stage 7”，而是进入**新一轮平台能力建设**。

---

## 5. 下一步准备做什么

结合 `docs/updatedos` 下的执行版文档，下一步建议正式进入：

- P0：可观测 + MCP + 最小 Skill
- P1：最小记忆 + Retrieval + Skill 复用增强
- P2：可治理执行 + 权限模型 + 审批策略升级

但从当前产品正确性优先级来看，后续实际实施主线建议统一收敛到：

- 先完成文档与口径统一
- 再进入 `TaskIntent + DeliverableSpec + deliverable-first planner + validator`
- 对话层增强与长期平台增强放在后续阶段推进

统一执行方案见：

- `docs/unified_delivery_execution_plan.md`

当前最建议先做的是 **P0**。

原因很简单：

- 没有 trace，后面的 MCP / Skill / Memory 很容易变成黑盒
- 没有最小 MCP registry，平台扩展能力无法真正落地
- 没有最小 Skill registry，复用能力还停留在文档层

当前 P0 进度已经不是从 0 开始：

- P0.1 Trace 底座：已落地第一刀
- P0.2 Trace 查询与最小 UI：已落地第一刀
- P0.3 MCP Tool Registry：已落地第一刀
- P0.4 Minimal Skill Registry：已落地第一刀

当前已进一步推进：

- P0 Trace 第二刀：已补更细粒度 trace 展示与只读 replay
- P0 Minimal Skill Registry 第二刀：已补治理台可视化、task UI skill 选择与更细 skill trace

---

## 6. 下一步准备怎么做

## 6.1 P0 的目标

在不破坏现有 task / approval / audit / checkpoint / change request / Stage 7 主链的前提下，让系统先具备：

- 可观测
- 可扩展
- 可复用

## 6.2 P0 的拆解顺序

### P0.1 Trace 底座

先补最小 trace 体系：

- `task_traces`
- `step_traces`
- `model_traces`
- `tool_traces`
- `skill_traces`（先最小版）
- `retrieval_traces`（先预留）

目标：

- 任意任务都能解释“怎么执行的”
- 每个 step 都知道用了哪个模型、哪个 prompt、哪些工具
- 所有 trace 都能关联 `task_run_id`

当前已完成的第一刀：

- 后端已落地 `task_traces` / `step_traces` / `model_traces` / `tool_traces`
- `skill_traces` / `retrieval_traces` 已建表预留扩展位
- 当前真实写入已覆盖 task / step / tool trace
- 当前真实 model trace 已覆盖 `planner` / `summarize_text` / `web_search_summary`

### P0.2 Trace 查询与最小 UI

补只读查询与展示：

- `GET /tasks/{task_id}/traces`
- `GET /tasks/{task_id}/steps/{step_id}/traces`
- 任务详情页最小 Trace 面板

目标：

- Web / API 可见
- 不要求第一版很漂亮，但必须真实可看

当前已完成的第一刀：

- API 已提供 `GET /tasks/{task_id}/traces`
- API 已提供 `GET /tasks/{task_id}/steps/{step_id}/traces`
- Web `任务详情` 已新增 `Traces` 子页签
- 当前可直接查看 task / step / model / tool traces 的最小面板

### P0.3 MCP Tool Registry

扩展 Tool Registry，补最小 MCP 支持：

- `builtin`
- `mcp_stdio`
- `mcp_http`

第一版只需要：

- 能注册
- 能执行
- 能治理
- 能 trace

当前已完成的第一刀：

- Tool Registry 已扩展 `provider_type / transport / server_name / provider_config / approval_required`
- 已兼容 `builtin / mcp_stdio / mcp_http` 三类工具元数据
- API `GET /tools` 与治理页已能看到 MCP 字段
- CLI `tools set` 已支持写入 MCP 配置
- worker 已接入最小 MCP adapter，可执行 `mcp_stdio / mcp_http`
- 已通过正式 `change request -> approve -> apply` 主链注册 `mcp_stdio_echo`
- 已通过 `bash scripts/mcp_tool_registry_check.sh` 完成真实 smoke：注册、查询、容器内执行全部通过

### P0.4 Minimal Skill Registry

先补 Skill 最小闭环：

- Skill metadata 注册
- Skill package 导入
- Skill discovery
- 显式 skill invocation
- 最小 skill trace

第一版暂时不做：

- Skill marketplace
- generated skill
- team publishing workflow

当前已完成的第一刀：

- 已新增 `skills / skill_versions` 最小 registry 表
- API 已提供 `POST /skills/import`、`GET /skills`、`GET /skills/{skill_id}`
- CLI 已提供 `skills import / list / show`
- task 创建已支持显式 `skill_id / skill_version / skill_args`
- worker 已支持从 `runtime_overrides.skill_invocation` 加载 skill 包并生成结构化 steps
- 已写入最小 `skill_trace`，并可通过 `/tasks/{task_id}/traces` 查看
- 已通过 `bash scripts/skill_registry_check.sh` 完成真实 smoke：导入 skill、显式调用、产出文件、trace 写入全部通过

### P0.5 验收与回归

P0 落地后，至少要补：

- trace smoke
- MCP tool smoke
- skill import / invoke smoke
- 现有 healthcheck / readiness / Stage 7 聚合回归

当前已完成的回归验证：

- `bash scripts/healthcheck.sh`
- `bash scripts/stage7_mainline_check.sh`
- `bash scripts/web_console_check.sh`
- `GET /tasks/2420/traces` 已确认返回 task / step / tool traces

---

## 6.3 P0 之后的主线建议：通用任务架构

在 P0 的 trace / skill / MCP 基础能力基本成型后，下一条主线建议切换到：

- Deliverable-first Universal Task Architecture

核心不是继续堆单点执行能力，而是补齐“交付闭环”：

- `TaskIntent`
- `DeliverableSpec`
- deliverable-first planner
- `ValidationReport`
- `RecoveryAction`

目标是把系统从：

- 会执行任务

升级为：

- 能稳定交付用户真正要的最终产物

相关执行方案已整理到：

- `docs/universal_task_architecture_execution_plan.md`

推荐顺序：

1. Phase 1：`TaskIntentResolver + DeliverableSpecResolver`
2. Phase 2：交付导向 planner（强制 `generate + validate`）
3. Phase 3：validator + retry / replan / clarify
4. Phase 4：pattern memory

---

## 7. 完成 P0 / P1 / P2 后的阶段效果

### P0 完成后

系统将从“会执行”升级到：

- 看得清执行过程
- 可以安全接入 MCP 工具
- 可以开始沉淀与复用 Skill

### P1 完成后

系统将从“会执行”升级到：

- 能记住用户偏好
- 能复用历史经验
- 能通过 retrieval 增强任务质量

### P2 完成后

系统将从“有治理”升级到：

- 谁能执行什么更加明确
- 哪些动作自动批、哪些人工批更加清晰
- Skill / Tool / Memory 都进入统一权限边界

---

## 8. 项目最终想达到的成果

这个项目的最终成果，不应该只是一个“能聊天的助手”，而应该是：

**一个面向真实工作场景的、可执行、可治理、可复用、可持续演进的 AI Assistant Platform。**

最终目标包括：

- 能执行真实任务，而不只是回答问题
- 能把成熟做法沉淀成可复用 Skill
- 能接入本地工具、内置工具与 MCP 工具
- 能记住用户、项目和历史经验
- 能在权限、审批、审计边界内安全运行
- 能做评估、提案、实验、回滚与持续优化

更长远地说，项目最终会从：

- 本地个人 AI 助理

逐步走向：

- 团队级 AI 工作平台
- 可治理的 AI 操作系统

---

## 9. 当前推荐执行口径

对外或对内汇报时，建议统一使用下面这套表述：

- 当前 Stage 1-7 已完成
- 当前系统已经具备任务执行、治理、评估、自改进与受控回滚能力
- 下一阶段不是继续补 Stage 7，而是进入 P0 / P1 / P2 的平台增强
- 当前最优先做的是 P0：Trace + MCP + Minimal Skill
- 项目最终目标是成为可治理、可复用、可持续演进的 AI Assistant Platform

---

## 10. 建议优先阅读

- `README.md`
- `version.json`
- `docs/personal_ai_os_roadmap.md`
- `docs/unified_delivery_execution_plan.md`
- `docs/current_status_and_next_execution_plan.md`
- `docs/updatedos/ai-assistant-p0-p1-p2-execution-plan.md`
- `docs/runbook.md`
