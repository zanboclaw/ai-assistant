# 运维动作手册

## 核心信号

- API 健康：`bash scripts/healthcheck.sh`
- 运行概览：`GET /monitor/overview`
- 运行版本：`GET /runtime-metadata` 或 `bash scripts/runtime_version_check.sh`
- Web 控制台检查：`bash scripts/web_console_check.sh`
- Session / Memory 健康：`bash scripts/session_memory_check.sh`
- 治理链检查：`bash scripts/governance_check.sh`
- 分层检查入口：
  - 日常：`bash scripts/daily_checks.sh`
  - 回归：`RUN_E2E=1 bash scripts/regression_checks.sh`
  - 发布：`bash scripts/release_readiness_check.sh`

## 日志定位

### API

- 默认文件：`logs/api.log`
- 如果目录或文件不可写，API 会保留 stdout/stderr 日志并输出 `api file logger disabled ...` 告警，不会因为日志文件不可写直接中断服务启动。
- 关注关键词：
  - `task created`
  - `task resumed`
  - `shadow validation`
  - `change request`

### Worker

- 默认文件：`logs/worker.log`
- 如果目录或文件不可写，Worker 会保留 stdout/stderr 日志并输出 `worker file logger disabled ...` 告警，方便先恢复执行面再继续排查磁盘或权限问题。
- 关注关键词：
  - `task started`
  - `task failed`
  - `waiting_approval`
  - `waiting_clarification`
  - `claim lost`

### Scheduler

- 默认文件：`logs/`
- 关注关键词：
  - `daily review`
  - `session state rebuild`

## 常见故障与处理

### 1. API 能启动，但任务不执行

- 检查 `REDIS_URL`
- 检查 worker 是否在线
- 检查 `task_runs.status` 是否停在 `pending`
- 检查 `worker.log` 是否出现 claim / connection 错误
- 检查 `GET /runtime-metadata` 或 `bash scripts/runtime_version_check.sh`，确认当前容器确实在跑预期版本

### 1.1 API 容器启动后反复重启，并出现数据库密码错误

- 常见日志：
  - `password authentication failed for user "assistant"`
- 原因：
  - 当前 `.env` 里的 `POSTGRES_PASSWORD` 和已有本地 Postgres 数据卷初始化时的密码不一致
- 处理方式：

```bash
bash scripts/repair_local_postgres_auth.sh
docker compose -f infra/compose/docker-compose.yml restart api worker scheduler
```

- 修复后再检查：
  - `docker compose -f infra/compose/docker-compose.yml ps`
  - `bash scripts/healthcheck.sh`

### 2. 前端能打开，但控制台报接口失败

- 检查 API 端口是否映射
- 检查浏览器控制台中的请求路径是否指向 `:8000`
- 检查设置页里的当前 API Base、actor 和运行版本指纹是否与目标环境一致
- 如果前端和 API 不在默认同机端口组合，可使用：

```text
http://localhost:8080/?api_base=http://localhost:8000
```

- 执行 `bash scripts/web_console_check.sh`

### 3. 任务频繁卡在审批或恢复

- 检查 `GET /tasks/{id}/approvals`
- 检查 `validation_report_json`
- 检查 `recovery_action_json`
- 必要时走 `resume / clarify / apply-recovery-action`

### 3.1 任务显示 waiting_clarification

- 这是执行前的补信息阻断，优先级高，但不属于系统故障
- 重点看 `validation_report_json.source=task_runtime_preflight_v1`、`recovery_action_json.action=clarify`
- 让操作员补齐澄清信息后重新入队，不要按运行时失败告警处理

### 4. Session 健康度异常

- 执行 `bash scripts/session_memory_check.sh`
- 检查 `session_state` 是否陈旧
- 检查 `daily review` 是否当天已覆盖

### 5. 变更单无法 apply

- 检查 shadow validation 是否完成
- 检查 target_type 是否属于强制门禁目标
- 检查 rollback draft 是否可生成

### 6. 日志里出现 `file logger disabled`

- 这说明服务已退化到标准输出日志，主链通常仍可继续运行
- 先确认：
  - `LOG_DIR` 是否指向存在且可写的目录
  - 容器挂载目录权限是否允许当前用户写入
  - 宿主机磁盘是否已满
- 处理后重启相关服务，再检查 `logs/api.log` 或 `logs/worker.log` 是否恢复落盘

## 巡检建议

### 日常

- 查看 `monitor/overview`
- 看 pending approvals 数量
- 看 change request pending/applied 数量
- 看 daily review 是否正常执行

### 发布前

- 执行 `bash scripts/release_readiness_check.sh`
- 执行关键验收脚本
- 看 `CHANGELOG.md` 是否已更新

### 故障后

- 先保留日志与 checkpoints
- 再做人工恢复、回滚或变更单撤销
- 最后补记录到 `CHANGELOG.md` 或发布记录

## 值班记录模板

- 故障时间：记录开始时间、恢复时间、持续时长
- 影响范围：API / Worker / Web / Governance / Session 哪条主链受影响
- 版本指纹：记录 `current_version`、`git_commit`、`git_branch`、`git_dirty`
- 观测证据：相关日志关键词、`monitor/overview` 摘要、task id / change request id / session id
- 处理动作：恢复、回滚、补审批、重放、修配置或修权限
- 收尾动作：是否需要补回归、补 runbook、补审计说明
