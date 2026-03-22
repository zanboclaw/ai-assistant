# Engineering Evidence Log

这份文档用于把“本轮看起来没问题”沉淀成可追溯、可复查的工程证据。

目标不是写成长日报，而是固定三件事：

- 什么时候验证过
- 当时跑了什么
- 为什么可以判断系统仍然真实可用

建议每轮较大推进至少记录一条。

## 建议填写规则

- 一条记录对应一轮相对完整的推进或收口
- 优先记录真实执行结果，不写计划中的事项
- 如果某项没有执行，明确写“未执行”而不是留空
- 若涉及 Stage 7，必须显式记录：
  - `groundwork_completed=true/false`
  - `completed=true/false`

## 记录模板

```md
## YYYY-MM-DD HH:MM

- 目标：
- 变更范围：
- 是否代码改动：

- 已跑脚本：
  - `bash scripts/healthcheck.sh` ->
  - `bash scripts/web_console_check.sh` ->
  - 其它：

- 关键接口抽检：
  - `GET /change-requests?limit=5` ->
  - `GET /change-requests/{id}` ->
  - `GET /workflow-proposals/{id}` ->
  - `GET /workflow-proposals/{id}/shadow-validation` ->
  - `GET /tools` ->
  - `GET /model-routes` ->
  - `GET /model-providers` ->
  - `GET /monitor/overview` ->

- 数据库事务健康：
  - `pg_stat_activity` 结论：

- Stage 7 口径：
  - `groundwork_completed=`
  - `completed=`
  - 说明：

- 结论：
  - 当前是否仍然真实可用：
  - 当前是否允许继续推进：
  - 备注：
```

## 推荐记录示例

## 2026-03-22 03:53

- 目标：继续瘦身 `workflow proposal / change request` 周边编排，并保持系统可用
- 变更范围：`apps/api/main.py`、`apps/api/workflow_proposal_store.py`、`apps/api/change_request_business.py`
- 是否代码改动：是

- 已跑脚本：
  - `bash scripts/healthcheck.sh` -> 通过
  - `bash scripts/web_console_check.sh` -> `PASS=33 FAIL=0 WARN=0`
  - 其它：编译校验通过

- 关键接口抽检：
  - `GET /change-requests?limit=5` -> 正常返回
  - `GET /change-requests/420` -> 正常返回
  - `GET /workflow-proposals/985` -> 正常返回
  - `GET /workflow-proposals/985/shadow-validation` -> 正常返回
  - `GET /tools` -> 正常返回
  - `GET /model-routes` -> 正常返回
  - `GET /model-providers` -> 正常返回
  - `GET /monitor/overview` -> 正常返回

- 数据库事务健康：
  - `pg_stat_activity` 结论：仅见当前检查 SQL 为 `active`，无新的 `idle in transaction`

- Stage 7 口径：
  - `groundwork_completed=true`
  - `completed=true`
  - 说明：groundwork 已收口，且 Stage 7 overall completed 已完成升级

- 结论：
  - 当前是否仍然真实可用：是
  - 当前是否允许继续推进：是
  - 备注：读接口未出现新的锁等待或事务残留

## 2026-03-22 05:11

- 目标：在保持系统可用的前提下，加速收口 proposal / shadow validation 编排与 governance 写路由
- 变更范围：`apps/api/main.py`、`apps/api/workflow_proposal_store.py`、`apps/api/governance_helpers.py`、`apps/api/access_control.py`、`apps/api/risk_policy_helpers.py`
- 是否代码改动：是

- 已跑脚本：
  - `bash scripts/healthcheck.sh` -> 通过
  - `bash scripts/web_console_check.sh` -> `PASS=33 FAIL=0 WARN=0`
  - 其它：`python3 -m py_compile ...` 通过；`docker compose -f infra/compose/docker-compose.yml restart api` 完成

- 关键接口抽检：
  - `GET /change-requests?limit=5` -> 正常返回
  - `GET /workflow-proposals/985` -> 正常返回
  - `GET /workflow-proposals/985/shadow-validation` -> 正常返回
  - `GET /workflow-proposals/985/change-request-draft` -> 正常返回
  - `GET /tools` -> 正常返回
  - `GET /model-routes` -> 正常返回
  - `GET /model-providers` -> 正常返回
  - `GET /risk-policies` -> 正常返回
  - `GET /access/actors` -> 正常返回
  - `GET /access/quotas` -> 正常返回
  - `GET /evaluator-runs?limit=5` -> 正常返回
  - `GET /monitor/overview` -> 正常返回

- 数据库事务健康：
  - `pg_stat_activity` 结论：仅见当前检查 SQL 为 `active`，未见新的长事务或 `idle in transaction`

- Stage 7 口径：
  - `groundwork_completed=true`
  - `completed=true`
  - 说明：本轮工程侧收口、路由瘦身与既有 sandbox acceptance/rollback 能力一起支撑 Stage 7 completed 口径

- 结论：
  - 当前是否仍然真实可用：是
  - 当前是否允许继续推进：是
  - 备注：已完成 governance 写路由两轮收口，proposal / shadow validation 主链进一步下沉

## 使用建议

- 若后续改动很小，可以多轮记录合并成一条“当日汇总”
- 若本轮出现回归，应保留失败记录，不要只保留最终修复后的成功记录
- 若本轮只做文档或治理事项，也建议保留记录，以说明口径为何发生变化
