# 运维动作手册

## 核心信号

- API 健康：`bash scripts/healthcheck.sh`
- 运行概览：`GET /monitor/overview`
- Web 控制台检查：`bash scripts/web_console_check.sh`
- Session / Memory 健康：`bash scripts/session_memory_check.sh`
- 治理链检查：`bash scripts/governance_check.sh`

## 日志定位

### API

- 默认文件：`logs/api.log`
- 关注关键词：
  - `task created`
  - `task resumed`
  - `shadow validation`
  - `change request`

### Worker

- 默认文件：`logs/worker.log`
- 关注关键词：
  - `task started`
  - `task failed`
  - `waiting_approval`
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

### 4. Session 健康度异常

- 执行 `bash scripts/session_memory_check.sh`
- 检查 `session_state` 是否陈旧
- 检查 `daily review` 是否当天已覆盖

### 5. 变更单无法 apply

- 检查 shadow validation 是否完成
- 检查 target_type 是否属于强制门禁目标
- 检查 rollback draft 是否可生成

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
