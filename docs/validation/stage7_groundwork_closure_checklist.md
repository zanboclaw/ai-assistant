# Stage 7 Groundwork Closure Checklist

这份清单的目标是把 Stage 7 从 groundwork 已完成收口，进一步升级到全阶段 `completed` 的状态固定成可验证、可解释、可回归的闭环。

## 当前状态

当前判断：

- Stage 7 当前已经完成全阶段收口
- `monitor/overview.readiness_metrics.stage7` 固定表达为：
  - `groundwork_active=true`
  - `operational=true`
  - `groundwork_completed=true`
  - `completed=true`
  - `groundwork_ratio=1.0`
  - `completion_ratio=1.0`
- Stage 7 当前 closure 结论同时覆盖配置层 candidate overlay / payload hash gate / patch artifact / rollback 闭环，以及 `sandbox_file` file-level source-copy/source-patch/apply/rollback、workflow proposal bridge、acceptance / auto rollback

当前统一口径应固定表达为：

- Stage 7 groundwork 已完成收口
- Stage 7 groundwork 已可观测、可回归、可脚本验证
- Stage 7 整体已完成

补充当前工程侧进展（2026-03-22）：

- `workflow proposal / shadow validation` 路由入口继续下沉到 store helper
- governance 写接口已开始成组收口，减少 `main.py` 中重复的 seed / update / audit / serialize 流程
- readiness/closure 判定已把 `sandbox_file + acceptance + auto rollback` 纳入正式 completed gate

为了避免误解，后续任何 closure 结论都应显式保留：

- `groundwork_completed=true`
- `completed=true`

## 收口判定规则

当下面三类条件同时满足时，可以认为当前 Stage 7 已完成收口：

- 必跑脚本全部通过：
  - `bash scripts/web_console_check.sh`
  - `bash scripts/workflow_proposal_bridge_check.sh`
  - `bash scripts/stage7_shadow_validation_status_check.sh`
  - `bash scripts/stage7_model_route_override_check.sh`
  - `bash scripts/stage7_web_search_route_override_check.sh`
  - `bash scripts/stage7_sandbox_file_change_check.sh`
  - `bash scripts/stage7_sandbox_file_patch_check.sh`
  - `bash scripts/stage7_sandbox_file_acceptance_check.sh`
  - `bash scripts/stage7_sandbox_file_bridge_check.sh`
  - `bash scripts/change_request_rollback_check.sh`
  - `bash scripts/stage7_mainline_check.sh`
  - `bash scripts/stage7_closure_check.sh`
- `GET /monitor/overview` 中的 `readiness_metrics.stage7` 稳定返回，并明确区分：
  - groundwork 已完成
  - stage overall 已完成
- Web / CLI / API / 文档 对 Stage 7 的理解一致，没有只在单个 smoke 路径成立的“假收口”

这意味着当前 closure 结论是：

- groundwork closure 成立
- 当前仓库下的 Stage 7 overall closure 也成立

## 主链专项

完成定义：

- change request-scoped shadow validation 能表达 `requested -> completed`
- candidate overlay + `payload_hash` precision gate 已真正接入 apply 门禁
- `summarize_text` route override 已能在真实主链步骤输出里落盘
- `web_search_summary` route override 已能在真实 `web_search` 主链步骤输出里落盘
- patch artifact / rollback artifact / rollback change request 已形成闭环
- `sandbox_file` source-copy/source-patch/apply/rollback 已形成闭环
- `sandbox_file` acceptance / auto rollback 已形成闭环
- Web 监控页已能显示 Stage 7 overall completion 关键指标

检查项：

- [x] `bash scripts/stage7_shadow_validation_status_check.sh` 通过
- [x] `bash scripts/stage7_model_route_override_check.sh` 通过
- [x] `bash scripts/stage7_web_search_route_override_check.sh` 通过
- [x] `bash scripts/change_request_rollback_check.sh` 通过
- [x] `bash scripts/stage7_mainline_check.sh` 通过
- [x] `GET /change-requests/{id}/shadow-validation` 能返回最新 gate/report 同步结果
- [x] `readiness_metrics.stage7` 至少包含：
  - `workflow_improvement_change_request_count`
  - `shadow_completed_change_request_count`
  - `shadow_completion_ratio`
  - `candidate_overlay_validation_count`
  - `candidate_match_change_request_count`
  - `patch_artifact_ready_count`
  - `rollback_ready_count`
  - `rollback_applied_count`
  - `sandbox_file_applied_count`
  - `sandbox_source_copy_applied_count`
  - `sandbox_source_patch_applied_count`
  - `sandbox_acceptance_passed_count`
  - `sandbox_acceptance_failed_count`
  - `sandbox_auto_rollback_applied_count`
  - `groundwork_ratio`
  - `completion_ratio`
  - `groundwork_completed`
  - `operational`
  - `completed`

## 总收口命令

优先跑这条：

```bash
bash scripts/stage7_closure_check.sh
```

当前对齐后预期结果：

- `bash scripts/stage7_closure_check.sh` -> `PASS=10 FAIL=0`

最近一轮聚合结果（2026-03-22）：

- `bash scripts/stage7_mainline_check.sh` -> `PASS=10 FAIL=0`
- `bash scripts/stage7_readiness_check.sh` -> `PASS=11 FAIL=0 WARN=0`
- `bash scripts/stage7_closure_check.sh` -> `PASS=10 FAIL=0`
- `bash scripts/stage7_sandbox_file_change_check.sh` -> `PASS=17 FAIL=0 WARN=0`
- `bash scripts/stage7_sandbox_file_patch_check.sh` -> `PASS=21 FAIL=0 WARN=0`
- `bash scripts/stage7_sandbox_file_bridge_check.sh` -> `PASS=25 FAIL=0 WARN=0`

需要分别看 Stage 7 各个专项时，可单跑：

```bash
bash scripts/stage7_model_route_override_check.sh
bash scripts/stage7_web_search_route_override_check.sh
bash scripts/stage7_shadow_validation_status_check.sh
bash scripts/change_request_rollback_check.sh
bash scripts/stage7_mainline_check.sh
bash scripts/stage7_readiness_check.sh
```

## 后续增强

当前 Stage 7 closure 已完成，但后续仍值得继续增强：

- 把 `sandbox_file` 实验通道继续推进到 branch 级别自动化
- 补充代码层 patch proposal 与自动回滚验收
- 把 Stage 7 的 completed 口径从 file-level 继续推进到代码层受控自修改
