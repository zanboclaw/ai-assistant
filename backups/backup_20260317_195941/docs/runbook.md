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

- `shell_exec`
- `file_write`
- `write_json`
- `http_request` 的 `POST`

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

## 7. MVP 验收

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

## 8. 常见排查

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

