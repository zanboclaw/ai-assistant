# Stage 5 / Stage 6 Closure Checklist

这份清单的目标是把当前 Stage 5 / Stage 6 已完成的主链状态固定成可验证、可解释、可回归的闭环。

## 当前状态

当前判断：

- Stage 5：已在主链完成 `task_runtime_postrun_v1` 收口
- Stage 6：已在主链完成 `evaluator / workflow proposal / bridge / shadow validation` 收口
- `monitor/overview` 当前固定表达为：
  - Stage 5：`operational=true`、`completed=true`、`completion_ratio=1.0`
  - Stage 6：`operational=true`、`completed=true`、`completion_ratio=1.0`
- Stage 5 / Stage 6 当前 gate 已完成；后续增强不再阻塞当前 completed 结论

## 收口判定规则

当下面三类条件同时满足时，可以认为当前 Stage 5 / Stage 6 的“最小主链”已经完成收口：

- 必跑脚本全部通过：
  - `bash scripts/task_runtime_mainline_init_check.sh`
  - `bash scripts/task_runtime_mainline_fanout_check.sh`
  - `bash scripts/stage6_evaluator_check.sh`
  - `bash scripts/workflow_proposal_bridge_check.sh`
  - `bash scripts/stage56_mainline_check.sh`
  - `bash scripts/stage56_closure_check.sh`
- `GET /monitor/overview` 中的 `readiness_metrics.stage5` / `readiness_metrics.stage6` 稳定返回，并满足 must-have 阈值
- Web / CLI / API 三个入口对 Stage 5 / 6 主链结果的理解一致，没有只在 demo/seed 路径成立的“假闭环”

这里的“通过”指脚本退出码为 `0`，且日志中没有 `FAIL`；`WARN` 可以存在，但必须被明确记录并解释，不得影响当前收口结论。

## Stage 5：多 Agent 主链收口

完成定义：

- 普通任务在执行期就能暴露 `manager / specialist / reviewer` 主链骨架
- runtime specialists 会在执行期完成最小 fan-out
- manager 会在执行尾声完成 fan-in rollup
- 终态会补齐 final artifact、review artifact、evaluator source 与 workflow proposal

检查项：

- [x] `bash scripts/task_runtime_mainline_init_check.sh` 通过
- [x] `bash scripts/task_runtime_mainline_fanout_check.sh` 通过
- [x] `bash scripts/stage56_mainline_check.sh` 通过
- [x] `GET /tasks/{id}` 与 `GET /tasks/{id}/agent-runs/summary` 返回：
  - `implementation_status = task_runtime_postrun_v1`
  - `execution_backend = mainline`
  - `control_mode = observe_only`
  - `runtime_fanout_active = true`
  - `latest_evaluator_source = task_runtime_postrun_v1`
- [x] `readiness_metrics.stage5` 至少包含：
  - `mainline_task_count`
  - `runtime_fanout_task_count`
  - `role_skeleton_ready_count`
  - `terminal_mainline_task_count`
  - `terminal_ready_count`
  - `runtime_fanout_ratio`
  - `role_skeleton_ratio`
  - `terminal_readiness_ratio`
  - `operational`
- [x] `readiness_metrics.stage5` 的 must-have 阈值：
  - `runtime_fanout_ratio >= 0.9`
  - `role_skeleton_ratio == 1.0`
  - `terminal_readiness_ratio >= 0.9`
  - `operational == true`
  - `completion_ratio == 1.0`
  - `completed == true`
  - `missing_completion_gates == []`
  - `mainline_task_count >= 1`
  - `terminal_mainline_task_count >= 1`

## Stage 6：Evaluator / Proposal / Bridge 收口

完成定义：

- 主链终态会写入独立 `evaluator_run`
- evaluator 会稳定生成 `workflow_proposal`
- proposal 可以进入列表、监控与 task summary
- 至少一条主链 proposal 能桥接进入 change request 治理流程

检查项：

- [x] `bash scripts/stage6_evaluator_check.sh` 通过
- [x] `bash scripts/workflow_proposal_bridge_check.sh` 通过
- [x] `bash scripts/stage56_closure_check.sh` 通过
- [x] `GET /tasks/{id}/evaluator-runs/latest`、`GET /tasks/{id}/workflow-proposals/latest`、`GET /workflow-proposals` 可读取主链 proposal
- [x] `GET /workflow-proposals/{id}/change-request-draft` 可返回自动映射建议
- [x] `POST /workflow-proposals/{id}/change-request-draft` 可生成 pending change request，并进入 audit
- [x] `readiness_metrics.stage6` 至少包含：
  - `mainline_evaluator_run_count`
  - `mainline_workflow_proposal_count`
  - `workflow_proposal_coverage_ratio`
  - `auto_mapped_proposal_count`
  - `mainline_bridged_change_request_count`
  - `bridge_activation_ratio`
  - `operational`
- [x] `readiness_metrics.stage6` 的 must-have 阈值：
  - `workflow_proposal_coverage_ratio == 1.0`
  - `auto_mapped_proposal_count >= 1`
  - `mainline_bridged_change_request_count >= 1`
  - `operational == true`
  - `completion_ratio == 1.0`
  - `completed == true`
  - `missing_completion_gates == []`
  - `shadow_validation_count >= 1`

## 总收口命令

优先跑这条：

```bash
bash scripts/stage56_closure_check.sh
```

当前对齐后预期结果：

- `bash scripts/stage56_closure_check.sh` -> `PASS=9 FAIL=0`

需要分别看主链 init / fanout / evaluator / bridge 时，可单跑：

```bash
bash scripts/task_runtime_mainline_init_check.sh
bash scripts/task_runtime_mainline_fanout_check.sh
bash scripts/stage6_evaluator_check.sh
bash scripts/workflow_proposal_bridge_check.sh
bash scripts/stage56_mainline_check.sh
```

## 后续增强

当前 completed 结论已经成立，但后续仍值得继续增强：

- manager 多轮自动重试与更稳定的 fan-in 决策
- 更丰富的 specialist 工具级子任务覆盖
- 更独立的 reviewer pipeline，而不只是主要依赖 terminal postrun
- evaluator 结果更稳定地反哺 workflow/runtime，而不只是生成 proposal
- shadow validation 从单条主链扩到更多 workflow 改动类型
