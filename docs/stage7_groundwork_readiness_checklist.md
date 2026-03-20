# Stage 7 Groundwork Readiness Checklist

这份清单的目标不是提前宣布 Stage 7 已完成，而是把“当前 Stage 7 groundwork 已打通到什么程度、为什么已经算 groundwork completed、为什么整体仍未 completed”固定成可验证口径。

## 当前状态

当前判断：

- Stage 5：保持 `completed`
- Stage 6：保持 `completed`
- Stage 7：当前是 `planned`，但 groundwork 已完成收口
- 当前 `monitor/overview` 快照（2026-03-21）：
  - `readiness_metrics.stage7.groundwork_active = true`
  - `readiness_metrics.stage7.operational = true`
  - `readiness_metrics.stage7.groundwork_completed = true`
  - `readiness_metrics.stage7.completed = false`
  - `readiness_metrics.stage7.groundwork_ratio = 1.0`
  - `readiness_metrics.stage7.missing_groundwork_gates = []`
- `version.json` 当前保持：
  - `current_version = stage7-groundwork-candidate-overlay-gated-mainline`
  - `stage_5_multi_agent_layer = completed`
  - `stage_6_evaluation_and_self_improvement = completed`
  - `stage_7_safe_self_modification_and_rollback = planned`
- 另外已补充 `sandbox_file` 实验通道，`readiness_metrics.stage7.sandbox_file_applied_count` 与 `sandbox_source_copy_applied_count` 现在可作为 file-level 补充信号；但它们都不参与当前 groundwork_completed 判定

## 判定规则

Stage 7 当前要区分四个状态：

- `groundwork_active`：
  说明仓库里已经出现 Stage 7 相关对象和主链证据，例如 workflow-improvement change request、shadow validation、patch artifact、rollback artifact。
- `operational`：
  说明当前 Stage 7 groundwork 所定义的 must-have gate 已经都可观测、可回归、可脚本验证。
- `groundwork_completed`：
  说明 groundwork 范围内的 gate 已全部满足，`groundwork_ratio = 1.0`，并且 `missing_groundwork_gates = []`。
- `completed`：
  保留给更完整的 Stage 7 目标，例如 sandbox / branch / code patch 自动化。当前必须仍然是 `false`。

## Groundwork Operational 基线

`monitor/overview.readiness_metrics.stage7` 至少要满足：

- `workflow_improvement_change_request_count >= 1`
- `shadow_completed_change_request_count >= 1`
- `candidate_overlay_validation_count >= 1`
- `candidate_match_change_request_count >= 1`
- `patch_artifact_ready_count >= 1`
- `rollback_ready_count >= 1`
- `rollback_applied_count >= 1`
- `operational == true`
- `groundwork_completed == true`
- `completed == false`

对应脚本：

- `bash scripts/stage7_model_route_override_check.sh`
- `bash scripts/stage7_web_search_route_override_check.sh`
- `bash scripts/stage7_shadow_validation_status_check.sh`
- `bash scripts/change_request_rollback_check.sh`
- `bash scripts/stage7_mainline_check.sh`
- `bash scripts/stage7_readiness_check.sh`

补充实验：

- `bash scripts/stage7_sandbox_file_change_check.sh`
  - 用于验证 `sandbox_file` target 的 file-level source-copy/apply -> rollback 闭环
- `bash scripts/stage7_sandbox_file_bridge_check.sh`
  - 用于验证 workflow proposal 可显式桥接到 `sandbox_file` target，并完成 source-copy/apply -> rollback
  - 这条脚本不影响当前 groundwork gate，只用于继续推进 Stage 7 从配置层走向文件级实验通道

## Groundwork Completed 门槛

除了 operational 基线外，还要额外满足：

- `groundwork_ratio == 1.0`
- `missing_groundwork_gates == []`
- `shadow_completion_ratio` 可读
- `version.json` 与 monitor 口径一致
- `stage7_mainline_check.sh` 已通过

当前 groundwork gate 对应的是这 6 项：

- `patch_artifact_ready`
- `workflow_shadow_gate_ready`
- `candidate_overlay_runtime_override_ready`
- `payload_hash_precision_gate_ready`
- `rollback_artifact_ready`
- `rollback_apply_ready`

## 最近一次脚本结果

- `bash scripts/stage7_sandbox_file_change_check.sh` -> `PASS=17 FAIL=0 WARN=0`
- `bash scripts/stage7_sandbox_file_bridge_check.sh` -> `PASS=23 FAIL=0 WARN=0`
- `bash scripts/stage7_mainline_check.sh` -> `PASS=8 FAIL=0`
- `bash scripts/stage7_readiness_check.sh` -> `PASS=8 FAIL=0 WARN=0`

## 当前建议优先看

- [version.json](/opt/ai-assistant/version.json)
- [apps/api/main.py](/opt/ai-assistant/apps/api/main.py)
- [scripts/stage7_model_route_override_check.sh](/opt/ai-assistant/scripts/stage7_model_route_override_check.sh)
- [scripts/stage7_web_search_route_override_check.sh](/opt/ai-assistant/scripts/stage7_web_search_route_override_check.sh)
- [scripts/stage7_mainline_check.sh](/opt/ai-assistant/scripts/stage7_mainline_check.sh)
- [scripts/stage7_readiness_check.sh](/opt/ai-assistant/scripts/stage7_readiness_check.sh)
- [docs/stage7_groundwork_closure_checklist.md](/opt/ai-assistant/docs/stage7_groundwork_closure_checklist.md)
