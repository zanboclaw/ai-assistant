# Multi-Agent Protocol v1

## 目标

这份文档冻结 Stage 5 的最小多 agent 协议边界，用来回答三件事：

- 当前 runtime 之上，第一版多 agent 协作到底要支持什么
- 哪些对象需要持久化，才能让 Web / CLI / audit 看得见
- manager / specialist / reviewer / operator 之间如何交换消息和工件

这是一份进入 Stage 5 前的协议草案，不代表已经切换主执行链。

## 设计原则

- 先在当前 `task_runs` 主链之上增加 manager-only orchestration
- 先支持最小 fan-out / fan-in，不急着做通用 agent graph
- reviewer 必须是独立角色，不只是 manager 的附加说明
- 所有 agent 活动都要落审计、状态和成本元数据
- 高风险动作仍沿用 Stage 4 的治理与审批边界

## 本版范围

本版只覆盖：

- 一个 `task_run` 下的多 agent 子运行
- 四类角色：`manager` / `specialist` / `reviewer` / `operator`
- 最小消息协议
- 最小 artifact 协议
- fan-out / fan-in 汇总
- reviewer 的独立评审结论

本版明确不覆盖：

- 任意深度的 agent graph
- agent 之间的长期自治协商
- 自动改代码与自动回滚
- 跨任务共享 agent 网络

## 角色定义

### manager

职责：

- 读取用户任务和上下文
- 产出任务拆解 brief 和执行计划
- 创建子 agent 运行
- 汇总 specialist 结果
- 决定重试、降级、升级审批或交给 reviewer
- 生成最终输出候选

限制：

- 不直接跳过治理边界
- 不把 reviewer 判断当作可选项

### specialist

职责：

- 在明确 brief 下完成某个子问题
- 产出 `draft` 或结构化结果
- 回传执行状态、失败原因、工件引用

限制：

- 不自行扩张任务范围
- 不直接提交最终结论

### reviewer

职责：

- 独立读取 brief、draft、evidence 和 manager 汇总
- 给出 `approved` / `rework_required` / `rejected`
- 记录判断理由和关键风险

限制：

- 不代替 specialist 执行主任务
- 不修改原始产物，只能追加 review artifact

### operator

职责：

- 表示人工或治理入口
- 在需要时批准、拒绝、介入或终止流程

限制：

- 不作为自动 fan-out 角色

## 持久化对象

本版建议新增三类对象。

### agent_runs

一条 `agent_run` 表示一个 `task_run` 下的单个 agent 执行实例。

建议字段：

- `id`
- `task_run_id`
- `parent_agent_run_id`
- `role`
- `status`
- `attempt`
- `brief_artifact_id`
- `output_artifact_id`
- `review_artifact_id`
- `assigned_model`
- `assigned_tool_profile`
- `started_at`
- `completed_at`
- `error_summary`
- `cost_tokens_in`
- `cost_tokens_out`
- `cost_usd_estimate`

状态建议：

- `planned`
- `queued`
- `running`
- `blocked`
- `completed`
- `failed`
- `canceled`

### agent_messages

一条 `agent_message` 表示 agent 间的一次协议化消息交换。

建议字段：

- `id`
- `task_run_id`
- `agent_run_id`
- `sender_role`
- `recipient_role`
- `message_type`
- `payload_json`
- `created_at`

消息类型建议：

- `brief`
- `progress`
- `request_clarification`
- `result`
- `review_decision`
- `handoff`
- `escalation`

### agent_artifacts

一条 `agent_artifact` 表示一个被协议引用的工件。

建议字段：

- `id`
- `task_run_id`
- `agent_run_id`
- `artifact_type`
- `content_json`
- `summary`
- `created_at`
- `version`

artifact 类型建议：

- `brief`
- `plan`
- `draft`
- `evidence`
- `review`
- `final`

## 最小消息协议

所有 agent 消息都应至少包含：

```json
{
  "protocol_version": "multi-agent-v1",
  "task_run_id": 0,
  "agent_run_id": 0,
  "sender_role": "manager",
  "recipient_role": "specialist",
  "message_type": "brief",
  "payload": {}
}
```

### brief payload

```json
{
  "objective": "要完成的子任务目标",
  "success_criteria": [
    "最小成功标准 1",
    "最小成功标准 2"
  ],
  "constraints": [
    "边界 1"
  ],
  "inputs": [
    {
      "artifact_id": 101,
      "label": "shared_context"
    }
  ]
}
```

### result payload

```json
{
  "status": "completed",
  "summary": "结果摘要",
  "artifact_ids": [201, 202],
  "risks": [
    "仍存在的风险"
  ],
  "needs_human_review": false
}
```

### review_decision payload

```json
{
  "decision": "approved",
  "reasoning_summary": "为什么通过或驳回",
  "blocking_issues": [],
  "follow_up_actions": []
}
```

## 最小 artifact 协议

### brief

用途：

- manager 发给 specialist / reviewer 的正式任务说明

最小字段：

- `objective`
- `scope`
- `constraints`
- `success_criteria`
- `input_refs`

### plan

用途：

- manager 的拆解结果

最小字段：

- `subtasks`
- `fan_out_strategy`
- `fallback_strategy`

### draft

用途：

- specialist 的工作结果草稿

最小字段：

- `summary`
- `output`
- `evidence_refs`
- `known_gaps`

### review

用途：

- reviewer 的独立结论

最小字段：

- `decision`
- `reasoning_summary`
- `blocking_issues`
- `follow_up_actions`

### final

用途：

- manager 汇总后的最终候选输出

最小字段：

- `summary`
- `final_output`
- `source_artifact_refs`
- `review_status`

## 协作流程

本版最小 happy path：

1. `manager` 读取 `task_run`，创建 `plan` artifact
2. `manager` 为 1-N 个 `specialist` 创建 `agent_run`
3. 每个 `specialist` 收到 `brief` 并产出 `draft`
4. `manager` 汇总 `draft`，生成 `final` 候选
5. `reviewer` 读取 `brief + draft + final`，产出 `review`
6. `manager` 根据 review 决定：
   - 通过并结束
   - 返工给某个 specialist
   - 降级成单 agent
   - 升级审批给 operator

失败分支最小要求：

- specialist 失败时，manager 必须显式记录：
  - `retry_same_role`
  - `retry_with_new_specialist`
  - `degrade_to_single_agent`
  - `escalate_to_operator`

## 与现有系统的衔接

本版协议默认复用现有能力：

- 任务入口仍然是 `task_runs`
- 风险控制仍然是 `risk_policies`
- 变更门禁仍然是 `change_requests`
- 监控和审计延续当前 `monitor/overview` 与 `audit_logs`

也就是说，Stage 5 第一版应该是“在当前平台上叠一层 manager orchestration”，而不是重写 API 或 worker 主链。

## Web / CLI 最小可见性要求

进入实现时，至少要让下面这些信息可见：

- 一个 `task_run` 下有哪些 `agent_runs`
- 每个 agent 的角色、状态、开始/结束时间
- 每个 agent 产出了哪些 artifact
- reviewer 的决策是什么
- manager 最终采用了哪条汇总路径

## 进入实现前的检查项

- Stage 3 / Stage 4 收口条件仍然保持通过
- 本文档与 [personal_ai_os_roadmap.md](/opt/ai-assistant/docs/archive/personal_ai_os_roadmap.md) 一致
- reviewer 角色不被弱化成普通注释
- 数据模型字段足够支撑 Web / CLI / audit 展示

## 下一步建议

建议按下面顺序推进：

1. 新增 `agent_runs / agent_messages / agent_artifacts` 数据模型
2. 先支持 `manager + 2 specialist + 1 reviewer` 的固定编排
3. 先做 1 条可重复跑通的 fan-out / fan-in 示例任务
4. 再把监控、审计、Web、CLI 接上 agent 维度视图
