# AI Assistant Runbook

## 目标

这个 runbook 对应当前仓库已经落地的 MVP，用来说明：

- 怎么启动系统
- 怎么初始化数据库
- 怎么用 Web 和 CLI 提交任务
- 怎么处理审批
- 怎么查看日志
- 怎么跑 MVP 验收

## 1. 启动服务

在仓库根目录执行：

```bash
docker compose -f infra/compose/docker-compose.yml up -d --build
```

启动后默认端口：

- API: `http://localhost:8000`
- Web: `http://localhost:8080`
- Postgres: `localhost:5432`

## 2. 初始化数据库

第一次启动或数据库结构有更新时执行：

```bash
curl -X POST http://localhost:8000/init-db
```

预期返回：

```json
{"message":"database initialized"}
```

## 3. Web 使用方式

打开：

```text
http://localhost:8080
```

当前前端支持：

- 提交任务
- 查看任务状态
- 查看步骤详情
- 查看待审批项
- 在页面里批准/拒绝审批

## 4. CLI 使用方式

CLI 文件：

[`scripts/assistant_cli.py`](/opt/ai-assistant/scripts/assistant_cli.py)

直接运行示例：

```bash
./scripts/assistant_cli.py task list
./scripts/assistant_cli.py task create -i "读取文件 /workspace/test_note.txt 并整理要点"
./scripts/assistant_cli.py task show 1
./scripts/assistant_cli.py steps 1
./scripts/assistant_cli.py approvals list
./scripts/assistant_cli.py approvals list --status pending
./scripts/assistant_cli.py approvals list --task-id 1
./scripts/assistant_cli.py approvals decide 3 --approve --note "ok"
./scripts/assistant_cli.py approvals decide 3 --reject --note "不要执行"
```

如果 API 地址不是默认值，可通过环境变量覆盖：

```bash
API_BASE=http://localhost:8000 ./scripts/assistant_cli.py task list
```

## 5. 审批流说明

当前默认会要求审批的步骤：

- `shell_exec`：统一视为高风险执行
- `file_write` / `write_json`：以下情况会要求审批
  - 覆盖已有文件
  - 写入隐藏文件
  - 写入脚本/配置类文件，例如 `.py`、`.sh`、`.json`、`.yaml`、`.env`
  - 写入不在低风险清单内的扩展名
- `http_request`：所有非 `GET` 请求都要求审批
- `http_request GET`：如果目标域名是 `.local` 也会要求审批

当前默认可直通的低风险产出文件类型：

- `.txt`
- `.md`
- `.csv`
- `.log`

执行流程：

1. 任务运行到高风险步骤
2. 任务状态变为 `waiting_approval`
3. `approvals` 表新增一条 `pending` 记录
4. 你可以通过 Web 或 CLI 批准/拒绝
5. 批准后任务恢复执行；拒绝后任务标记为失败

CLI 审批示例：

```bash
./scripts/assistant_cli.py approvals list --status pending
./scripts/assistant_cli.py approvals decide 12 --approve --note "允许本次执行"
./scripts/assistant_cli.py approvals decide 12 --reject --note "拒绝写入"
```

风险策略查看/调整示例：

```bash
./scripts/assistant_cli.py risk list
./scripts/assistant_cli.py risk set approval_low_risk_write_extensions '[".txt",".md",".csv",".log",".html"]'
./scripts/assistant_cli.py risk set approval_allowed_http_methods '["GET","HEAD"]'
./scripts/assistant_cli.py risk set approval_require_for_hidden_files false
```

## 6. 日志位置

当前已补轻量日志，API 和 Worker 都会同时输出到控制台和日志文件。

宿主机日志目录：

```text
/opt/ai-assistant/logs
```

关键日志文件：

- `/opt/ai-assistant/logs/api.log`
- `/opt/ai-assistant/logs/worker.log`
- `/opt/ai-assistant/logs/acceptance_check_*.log`
- `/opt/ai-assistant/logs/approval_retry_check_*.log`

可直接查看：

```bash
tail -f /opt/ai-assistant/logs/api.log
tail -f /opt/ai-assistant/logs/worker.log
```

## 7. Stage 2 基础能力

当前仓库已经接入第一批 Stage 2 基础设施：

- Redis 服务已加入 Compose
- 新任务会写入 Redis 队列
- Worker 会使用 Redis claim token + 锁续租，避免多 worker 时重复领取同一任务
- 每个任务会把 checkpoint 写到 `data/checkpoints/`
- API 提供 checkpoint 查询接口
- worker 会定期把“无锁且卡住太久”的运行中任务重新回队
- 风控策略已落库到 `risk_policies`，可通过 API / CLI 调整

### Claim / 续租验收

可运行新的验收脚本验证 Redis claim、worker 续租和 stale requeue 的闭环：

```
bash scripts/claim_lease_check.sh
```

脚本会先确认 API+Redis 可用，再创建任务检测 `task_claim:<task_id>` 的 TTL 是否有效，最后手动标记一个任务为 stale，确认 worker 记录 `stale task requeued task_id=<id>` 日志，并让任务脱离陈旧运行态。

Compose 服务里 Redis 默认地址：

```text
redis://redis:6379/0
```

查看单个任务的 checkpoint：

```bash
curl http://localhost:8000/tasks/500/checkpoint
./scripts/assistant_cli.py checkpoint 500
```

任务详情接口现在还会返回：

- `current_step`
- `checkpoint_path`

恢复执行接口：

```bash
curl -X POST http://localhost:8000/tasks/500/resume \
  -H "Content-Type: application/json" \
  -d '{"note":"resume after fix","from_step":3}'

./scripts/assistant_cli.py task resume 500 --from-step 3 --note "resume after fix"
```

说明：

- 只允许恢复 `failed` 或 `waiting_approval` 任务
- 如果任务还有 `pending approvals`，需要先处理审批，不能直接 resume
- 不传 `--from-step` 时，会优先从 `current_step` 恢复

暂停/中断接口：

```bash
curl -X POST http://localhost:8000/tasks/500/interrupt \
  -H "Content-Type: application/json" \
  -d '{"note":"pause for manual inspection"}'

./scripts/assistant_cli.py task interrupt 500 --note "pause for manual inspection"
```

说明：

- `running` 任务会先变成 `interrupt_requested`，Worker 会在步骤边界安全落到 `paused`
- `pending` 或 `waiting_approval` 任务会直接变成 `paused`
- `completed` / `failed` 任务不能 interrupt

## 8. 运维辅助脚本

新增脚本：

- [`scripts/backup.sh`](/opt/ai-assistant/scripts/backup.sh)
- [`scripts/healthcheck.sh`](/opt/ai-assistant/scripts/healthcheck.sh)

备份脚本会把关键目录打到 `backups/backup_<timestamp>/`：

```bash
bash scripts/backup.sh
```

健康检查脚本会检查：

- `http://localhost:8000/`
- `http://localhost:8080/`
- `api` 服务状态
- `worker` 服务状态
- `redis` 服务状态

运行方式：

```bash
bash scripts/healthcheck.sh
```

## 9. MVP 验收

### 基础结构化流程验收

```bash
bash scripts/acceptance_check.sh
```

说明：

- 当前脚本默认会在测试时自动批准待审批步骤
- 可通过 `AUTO_APPROVE_APPROVALS=0` 关闭自动批准

### 审批 + 重试专项验收

```bash
bash scripts/approval_retry_check.sh
```

这个脚本会验证：

- 新字段是否已经出现在 `steps` 接口里
- 写文件任务是否进入 `waiting_approval`
- 批准后任务是否恢复执行
- `http_request` 失败后是否出现重试痕迹

## 10. 常见排查

### API 正常但前端没有数据

- 确认 API 是否已启动：`curl http://localhost:8000/`
- 确认浏览器访问的是 `http://localhost:8080`

### 任务一直不动

- 看 Worker 日志：`tail -f /opt/ai-assistant/logs/worker.log`
- 看任务状态：`./scripts/assistant_cli.py task show <id>`

### 任务卡在 waiting_approval

- 查看审批：`./scripts/assistant_cli.py approvals list --status pending`
- 处理审批后再次查看任务状态

### 数据库字段未更新

- 重新执行：`curl -X POST http://localhost:8000/init-db`

### checkpoint 没写出来

- 确认 `data/checkpoints/` 已挂载
- 查看 Worker 日志：`tail -f /opt/ai-assistant/logs/worker.log`
- 查看任务详情里的 `checkpoint_path`
