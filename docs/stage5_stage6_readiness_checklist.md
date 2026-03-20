# Stage 5 / Stage 6 Readiness Checklist

这份清单的目标不是提前宣布 Stage 5 / Stage 6 已完成，而是把“主链已经打通到什么程度、离 completed 还差什么”固定成可验证口径。

## 当前状态

当前判断：

- Stage 5：主链 `runtime fan-out/fan-in + terminal postrun` 已 completed
- Stage 6：主链 `evaluator + workflow proposal + bridge + shadow validation` 已 completed
- 当前 `monitor/overview` 快照（2026-03-21）：
  - Stage 5：`completion_ratio=1.0`、`completed=true`、`missing_completion_gates=[]`
  - Stage 6：`completion_ratio=1.0`、`completed=true`、`missing_completion_gates=[]`
- `version.json` 继续保持：
  - `current_version = stage7-groundwork-candidate-overlay-gated-mainline`
  - `stage_5_multi_agent_layer = completed`
  - `stage_6_evaluation_and_self_improvement = completed`

## 判定规则

Stage 5 / Stage 6 现在分两层判断：

- `operational`：
  当前主链已经真实可跑，并且有监控 / 脚本 / 文档三方对齐的证据。
- `completed`：
  说明当前 roadmap 里定义的 must-have gate 已全部满足。

当前这三者现在已经统一为：

- `operational = true`
- `completed = true`
- `version.json` 标记为 completed

补充说明：

- `stage56_readiness_check.sh` 不再要求仓库版本永久停在 Stage 6 命名；只要 `stage_5` / `stage_6` 仍保持 `completed`，并且当前版本是已知的前进版本（例如当前的 Stage 7 groundwork 版本），就视为口径仍然成立。
- `readiness_metrics.stage5.non_readonly_specialist_task_count` 现在按累计主链证据聚合，而不是只看最近一小段任务窗口；这样后续 Stage 7 验收持续追加新任务时，不会把 Stage 5 的 completed 口径错误挤回 `false`。

## Stage 5 Operational 基线

`monitor/overview` 中的 `readiness_metrics.stage5` 至少要满足：

- `mainline_task_count >= 1`
- `runtime_fanout_task_count >= 1`
- `runtime_fanout_event_count >= 1`
- `runtime_fanin_event_count >= 1`
- `terminal_ready_count >= 1`
- `operational == true`

对应脚本：

- `bash scripts/stage56_mainline_check.sh`
- `bash scripts/stage56_readiness_check.sh`

## Stage 5 Completed 门槛

除了 operational 基线外，还要额外满足：

- `completed == true`
- `missing_completion_gates` 为空
- `non_readonly_specialist_task_count >= 1`

这条 gate 对应 roadmap 里“specialist 还没有扩到更真实的受限工具级子任务”。

## 最近一次脚本结果

- `bash scripts/stage56_mainline_check.sh` -> `PASS=7 FAIL=0`
- `bash scripts/stage56_readiness_check.sh` -> `PASS=12 FAIL=0 WARN=0`

## Stage 6 Operational 基线

`monitor/overview` 中的 `readiness_metrics.stage6` 至少要满足：

- `mainline_evaluator_run_count >= 1`
- `mainline_workflow_proposal_count >= 1`
- `mainline_bridged_change_request_count >= 1`
- `failure_taxonomy_count >= 1`
- `operational == true`

对应脚本：

- `bash scripts/stage6_evaluator_check.sh`
- `bash scripts/workflow_proposal_bridge_check.sh`
- `bash scripts/stage56_readiness_check.sh`

## Stage 6 Completed 门槛

除了 operational 基线外，还要额外满足：

- `completed == true`
- `missing_completion_gates` 为空
- `shadow_validation_count >= 1`

## 当前建议优先看

- [version.json](/opt/ai-assistant/version.json)
- [docs/personal_ai_os_roadmap.md](/opt/ai-assistant/docs/personal_ai_os_roadmap.md)
- [scripts/stage56_mainline_check.sh](/opt/ai-assistant/scripts/stage56_mainline_check.sh)
- [scripts/stage56_readiness_check.sh](/opt/ai-assistant/scripts/stage56_readiness_check.sh)
- [apps/api/main.py](/opt/ai-assistant/apps/api/main.py)
- [apps/web/index.html](/opt/ai-assistant/apps/web/index.html)
