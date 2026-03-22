# Stage 7 Groundwork Readiness Checklist

这份清单的目标是把 Stage 7 从 groundwork 收口推进到 overall completed 的升级过程固定成可验证口径，并保留 groundwork 与 overall 两层判定的边界。

## 当前状态

当前判断：

- Stage 5：保持 `completed`
- Stage 6：保持 `completed`
- Stage 7：当前已 `completed`
- 当前 `monitor/overview` 快照（2026-03-21）：
  - `readiness_metrics.stage7.groundwork_active = true`
  - `readiness_metrics.stage7.operational = true`
  - `readiness_metrics.stage7.groundwork_completed = true`
  - `readiness_metrics.stage7.completed = true`
  - `readiness_metrics.stage7.groundwork_ratio = 1.0`
  - `readiness_metrics.stage7.missing_groundwork_gates = []`
  - `readiness_metrics.stage7.completion_ratio = 1.0`
  - `readiness_metrics.stage7.missing_completion_gates = []`
- `version.json` 当前保持：
  - `current_version = stage7-safe-self-modification-mainline`
  - `stage_5_multi_agent_layer = completed`
  - `stage_6_evaluation_and_self_improvement = completed`
  - `stage_7_safe_self_modification_and_rollback = completed`
- `sandbox_file` 实验通道，`readiness_metrics.stage7.sandbox_file_applied_count`、`sandbox_source_copy_applied_count`、`sandbox_source_patch_applied_count`、`sandbox_acceptance_passed_count` 与 `sandbox_auto_rollback_applied_count` 现在都已纳入 Stage 7 overall completed 判定

当前对外口径必须保持为：

- Stage 7 `completed`
- Stage 7 `groundwork_completed = true`
- Stage 7 `operational = true`
- Stage 7 `completed = true`

这四个条件缺一不可。  
也就是说：

- 可以确认 groundwork 已收口
- 也可以确认 Stage 7 overall completed 已完成升级

补充当前工程侧进展（2026-03-22）：

- proposal / shadow validation 主链继续完成入口层瘦身
- governance 写路由已分两轮收口到 helper 模块
- `main.py` 继续减噪，同时 readiness 已把 `sandbox_file + acceptance + auto rollback` 纳入 Stage 7 overall 判定

## 判定规则

Stage 7 当前要区分四个状态：

- `groundwork_active`：
  说明仓库里已经出现 Stage 7 相关对象和主链证据，例如 workflow-improvement change request、shadow validation、patch artifact、rollback artifact。
- `operational`：
  说明当前 Stage 7 groundwork 所定义的 must-have gate 已经都可观测、可回归、可脚本验证。
- `groundwork_completed`：
  说明 groundwork 范围内的 gate 已全部满足，`groundwork_ratio = 1.0`，并且 `missing_groundwork_gates = []`。
- `completed`：
  当前由 groundwork 加上 file-level `sandbox_file` apply/source-copy/source-patch、acceptance 与 auto rollback 共同组成；当前必须是 `true`。

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
- `completed == true`

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
- `bash scripts/stage7_sandbox_file_patch_check.sh`
  - 用于验证 `sandbox_file` target 的 `source_path + patch` / apply -> rollback 闭环
- `bash scripts/stage7_sandbox_file_bridge_check.sh`
  - 用于验证 workflow proposal 可显式桥接到 `sandbox_file` target，并完成 source-patch/apply -> rollback
  - 这条脚本与 acceptance/auto rollback 一起，为当前 Stage 7 overall completed 提供文件级闭环证据

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

## 当前 overall completed 判定补充门槛

除了 groundwork 外，还需要下面这些能力真正进入聚合：

- `sandbox_file_applied_count >= 1`
- `sandbox_source_copy_applied_count >= 1`
- `sandbox_source_patch_applied_count >= 1`
- `sandbox_acceptance_passed_count >= 1`
- `sandbox_acceptance_failed_count >= 1`
- `sandbox_auto_rollback_applied_count >= 1`

这些能力现在已成为当前仓库里 Stage 7 completed 的正式门槛。

## 最近一次脚本结果

- `bash scripts/stage7_sandbox_file_change_check.sh` -> `PASS=17 FAIL=0 WARN=0`
- `bash scripts/stage7_sandbox_file_patch_check.sh` -> `PASS=21 FAIL=0 WARN=0`
- `bash scripts/stage7_sandbox_file_bridge_check.sh` -> `PASS=25 FAIL=0 WARN=0`
- `bash scripts/stage7_mainline_check.sh` -> `PASS=10 FAIL=0`
- `bash scripts/stage7_readiness_check.sh` -> `PASS=11 FAIL=0 WARN=0`

## 当前建议优先看

- [version.json](/opt/ai-assistant/version.json)
- [apps/api/main.py](/opt/ai-assistant/apps/api/main.py)
- [scripts/stage7_model_route_override_check.sh](/opt/ai-assistant/scripts/stage7_model_route_override_check.sh)
- [scripts/stage7_web_search_route_override_check.sh](/opt/ai-assistant/scripts/stage7_web_search_route_override_check.sh)
- [scripts/stage7_mainline_check.sh](/opt/ai-assistant/scripts/stage7_mainline_check.sh)
- [scripts/stage7_readiness_check.sh](/opt/ai-assistant/scripts/stage7_readiness_check.sh)
- [docs/validation/stage7_groundwork_closure_checklist.md](/opt/ai-assistant/docs/validation/stage7_groundwork_closure_checklist.md)
