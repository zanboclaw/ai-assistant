# Stage 3 / Stage 4 Closure Checklist

这份清单的目标不是启动下一阶段，而是先把当前阶段收口到“可验证、可解释、可回归”。

## 收口判定规则

当下面三类条件同时满足时，可以认为当前 Stage 3 / Stage 4 已完成收口：

- 必跑脚本全部通过：
  - `bash scripts/session_memory_check.sh`
  - `bash scripts/daily_review_check.sh`
  - `bash scripts/governance_check.sh`
  - `bash scripts/stage_closure_check.sh`
- `monitor/overview` 中的 stage readiness 指标已稳定返回，并且满足各自的 must-have 阈值
- Web / CLI / API 三个入口的关键功能与脚本结果一致，没有只在单入口生效的“孤岛行为”

这里的“通过”指脚本退出码为 `0`，且日志中没有 `FAIL`；`WARN` 可以存在，但必须被明确记录并解释，不得影响收口结论。

## Stage 3：助理化收口

完成定义：

- `sessions / memories / state / reviews / daily review` 主链可稳定运行
- `session health` 可返回当前健康信号和建议动作
- Web、CLI、API 三个入口对 Stage 3 主能力的覆盖保持一致
- 有专项验收脚本，且覆盖自动记忆提炼、state 重建、review 和 health

检查项：

- [ ] `bash scripts/session_memory_check.sh` 通过
- [ ] `bash scripts/daily_review_check.sh` 通过
- [ ] `bash scripts/stage_closure_check.sh` 通过，且内部 Stage 3 子项没有 FAIL
- [ ] `GET /sessions/{id}/summary` 返回 `session_state` 与 `health`
- [ ] `GET /sessions/{id}/health` 返回：
  - `active_task_count`
  - `duplicate_memory_count`
  - `state_is_stale`
  - `total_reviews`
  - `recommended_actions`
- [ ] `./scripts/assistant_cli.py sessions health <id>` 可直接查看 Stage 3 健康信号
- [ ] Web 工作区的 Session 子页签能看到：
  - Session Reviews
  - Session State
  - Session Health
- [ ] Web 的 Sessions 工作台可直接查看并编辑 session state，不依赖任务详情页
- [ ] `scripts/web_console_check.sh` 能确认 Web 控制台包含：
  - 顶层主页签
  - 独立 Sessions 工作台
  - Session Health / 编辑 State
  - Stage Readiness / 治理结果指标
- [ ] `scripts/session_memory_check.sh` 覆盖：
  - 自动 `task_summary` memory
  - 自动 preference 提炼
  - 自动 follow-up 提炼
  - `state-rebuild`
  - `session health`
  - 手动 review 后 health 变化
- [ ] `scripts/daily_review_check.sh` 覆盖：
  - daily-run 创建 review
  - 同日去重
  - scheduler `RUN_ONCE` smoke

当前建议优先看：

- [scripts/session_memory_check.sh](/opt/ai-assistant/scripts/session_memory_check.sh)
- [apps/api/main.py](/opt/ai-assistant/apps/api/main.py)
- [apps/web/index.html](/opt/ai-assistant/apps/web/index.html)
- [scripts/assistant_cli.py](/opt/ai-assistant/scripts/assistant_cli.py)

## Stage 4：企业化预埋收口

完成定义：

- `access / quotas / tools / models / changes / risk` 都有稳定治理入口
- 高风险控制面已进入 change request / approval / apply / audit 轨道
- 监控概览能看到治理 readiness，而不只是原始数量
- 有专项验收脚本，且覆盖治理主闭环和 readiness 信号

检查项：

- [ ] `bash scripts/governance_check.sh` 通过，且至少覆盖一次完整的 `create -> approve -> apply` 闭环
- [ ] `GET /monitor/overview` 返回：
  - `change_metrics`
  - `access_metrics`
  - `readiness_metrics.stage3`
  - `readiness_metrics.stage4`
- [ ] `readiness_metrics.stage4` 至少包含：
  - `change_gate_coverage_ratio`
  - `access_actor_count`
  - `access_quota_count`
  - `actor_quota_alignment_ok`
  - `quota_pressure_count`
  - `change_request_applied_count`
  - `change_request_closure_ratio`
- [ ] `readiness_metrics.stage4` 的 must-have 闭环阈值：
  - `change_gate_coverage_ratio == 1.0`
  - `change_request_applied_count >= 1`
  - `change_request_closure_ratio >= 1.0` 或在当前无 pending 时保持 `1.0`
  - `actor_quota_alignment_ok == true`
  - `access_actor_count > 0`
  - `access_quota_count > 0`
  - `quota_pressure_count` 可非零，但必须可读且在回归日志中被显式报告
- [ ] Web 监控页能看到 `Stage Readiness`
- [ ] Web 治理页仍可完成 actor/quota/change/tool/model 主流程
- [ ] `scripts/governance_check.sh` 覆盖：
  - 工具 / 模型 / quota usage 可读取
  - 受门禁保护的直改接口被拒绝
  - 允许直改的 `access_actor / access_quota` 路径保持可写，且不应被误判为门禁失败
  - operator 创建 change request
  - admin approve/apply
  - 应用后目标生效
  - 审计链 create / approve / apply 存在
  - 监控概览 readiness 可读取

Stage 4 收口时，`governance_check.sh` 必须至少同时覆盖两类信号：

- 负向信号：`risk_policy / tool_registry / model_route / model_provider` 直改应被拒绝
- 结果信号：`change_request_applied_count` 和 `change_request_closure_ratio` 必须从 `monitor/overview` 中可读，并在回归中被检查

当前建议优先看：

- [scripts/governance_check.sh](/opt/ai-assistant/scripts/governance_check.sh)
- [apps/api/main.py](/opt/ai-assistant/apps/api/main.py)
- [apps/web/index.html](/opt/ai-assistant/apps/web/index.html)

## 总收口命令

优先跑这两条：

```bash
bash scripts/session_memory_check.sh
bash scripts/daily_review_check.sh
bash scripts/governance_check.sh
bash scripts/web_console_check.sh
```

需要连续跑完整收口时：

```bash
bash scripts/stage_closure_check.sh
```

## 进入 Stage 5 的门槛

只有下面几项同时满足，才进入 Stage 5：

- [ ] Stage 3 专项验收通过
- [ ] Stage 4 专项验收通过
- [ ] 至少做过一轮 Web 手工 smoke
- [ ] README / runbook / checklist 与当前行为一致
- [ ] 明确列出遗留问题，不带模糊状态进入下一阶段
