# Stage 7 Groundwork Closure Checklist

这份清单的目标是把当前 Stage 7 groundwork 已完成收口的状态固定成可验证、可解释、可回归的闭环，同时明确它还不是 Stage 7 全阶段完成。

## 当前状态

当前判断：

- Stage 7 当前已经完成 groundwork 收口
- `monitor/overview.readiness_metrics.stage7` 固定表达为：
  - `groundwork_active=true`
  - `operational=true`
  - `groundwork_completed=true`
  - `completed=false`
  - `groundwork_ratio=1.0`
- Stage 7 当前 closure 结论只覆盖配置层的 candidate overlay / payload hash gate / patch artifact / rollback 闭环
- `sandbox_file` file-level source-copy/source-patch/apply/rollback 与 workflow proposal bridge 实验通道已落地，但它们都是追加进展，不改变当前 groundwork closure 判定边界
- sandbox / branch / code patch 自动化尚未纳入当前 closure 结论

## 收口判定规则

当下面三类条件同时满足时，可以认为当前 Stage 7 groundwork 已完成收口：

- 必跑脚本全部通过：
  - `bash scripts/web_console_check.sh`
  - `bash scripts/workflow_proposal_bridge_check.sh`
  - `bash scripts/stage7_shadow_validation_status_check.sh`
  - `bash scripts/stage7_model_route_override_check.sh`
  - `bash scripts/stage7_web_search_route_override_check.sh`
  - `bash scripts/change_request_rollback_check.sh`
  - `bash scripts/stage7_mainline_check.sh`
  - `bash scripts/stage7_closure_check.sh`
- `GET /monitor/overview` 中的 `readiness_metrics.stage7` 稳定返回，并明确区分：
  - groundwork 已完成
  - stage overall 仍未完成
- Web / CLI / API / 文档 对 Stage 7 groundwork 的理解一致，没有只在单个 smoke 路径成立的“假收口”

## 主链专项

完成定义：

- change request-scoped shadow validation 能表达 `requested -> completed`
- candidate overlay + `payload_hash` precision gate 已真正接入 apply 门禁
- `summarize_text` route override 已能在真实主链步骤输出里落盘
- `web_search_summary` route override 已能在真实 `web_search` 主链步骤输出里落盘
- patch artifact / rollback artifact / rollback change request 已形成闭环
- Web 监控页已能显示 Stage 7 groundwork 关键指标

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
  - `groundwork_ratio`
  - `groundwork_completed`
  - `operational`
  - `completed`

## 总收口命令

优先跑这条：

```bash
bash scripts/stage7_closure_check.sh
```

当前对齐后预期结果：

- `bash scripts/stage7_closure_check.sh` -> `PASS=8 FAIL=0`

最近一轮聚合结果（2026-03-21）：

- `bash scripts/stage7_mainline_check.sh` -> `PASS=9 FAIL=0`
- `bash scripts/stage7_readiness_check.sh` -> `PASS=9 FAIL=0 WARN=0`
- `bash scripts/stage7_closure_check.sh` -> `PASS=8 FAIL=0`
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

当前 groundwork closure 结论已经成立，但后续仍值得继续增强：

- 继续把 `sandbox_file` 实验通道从 sandbox 路径推进到 branch / code patch 自动化
- 补充代码层 patch proposal 与自动回滚验收
- 把 Stage 7 的“阶段完成”门槛从配置层收口推进到代码层受控自修改
