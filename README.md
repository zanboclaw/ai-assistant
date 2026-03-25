# AI Assistant

[![CI](https://github.com/zanboclaw/ai-assistant/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/zanboclaw/ai-assistant/actions/workflows/ci.yml)

一个面向本地运行、持续演进和受控治理场景的 AI 助理执行平台。当前仓库已经打通了从自然语言输入、任务分流、结构化执行、审批恢复、会话记忆、长期记忆、治理控制面，到 Stage 5/6/7 多 Agent、评估提案、变更单、影子验证与回滚的主干能力。

需要明确的是：当前仓库更接近“平台型可运行底座”，而不是已经完全收口的终态产品。它已经能运行、能验证、能治理，但仍处于持续工程化和产品化推进阶段。

## 项目定位

这个仓库主要解决几类问题：

- 在正式执行前先做输入分流、草稿理解与确认，避免模糊输入直接误执行
- 把自然语言任务转成可执行的结构化步骤，并支持审批、恢复、回放和追踪
- 用 session / state / review / long-term memory 形成最小助理化闭环
- 把工具、模型、权限、配额、风险策略、变更与回滚纳入统一治理
- 为多 Agent、评估、workflow proposal 和受控自改进提供工程底座

## 当前能力

当前仓库已经实现的主要能力包括：

- 任务主链：
  - `POST /intake/route`
  - `POST /intake/confirm`
  - `POST /tasks`
  - `GET /tasks/*`
  - `interrupt / resume / clarify / apply-recovery-action`
- 轻量问答：
  - `POST /chat/fast-path`
  - 用于不进入完整任务持久化链的轻量回答
- 结构化执行：
  - 结构化步骤执行
  - 工具调用
  - 审批门禁
  - checkpoint / retry / resume
- 记忆与会话：
  - `sessions`
  - `session state`
  - `session reviews`
  - `daily review`
  - `long_term_memories`
  - `/memories/search`
- 治理控制面：
  - `access actors / quotas`
  - `risk policies`
  - `tool registry`
  - `model routes / providers`
  - `change requests`
  - `shadow validation`
  - `rollback`
- 可观测性：
  - `task traces`
  - `replay`
  - `monitor/overview`
  - readiness metrics
- Stage 5 / 6 / 7：
  - `agent_runs`
  - `evaluator_runs`
  - `workflow_proposals`
  - `sandbox_file`
  - rollback / shadow validation 主链

## 架构概览

系统当前采用“控制面 + 执行面 + 状态中心 + 静态控制台”的结构：

- Web 控制台：
  - [apps/web/index.html](/opt/ai-assistant/apps/web/index.html)
  - 原生 JavaScript / CSS 静态页面
- API 控制面：
  - [apps/api/main.py](/opt/ai-assistant/apps/api/main.py)
  - [apps/api/intake_task_routes.py](/opt/ai-assistant/apps/api/intake_task_routes.py)
- Worker 执行面：
  - [apps/worker/worker.py](/opt/ai-assistant/apps/worker/worker.py)
  - [apps/worker/task_payloads.py](/opt/ai-assistant/apps/worker/task_payloads.py)
  - [apps/worker/task_execution_runtime.py](/opt/ai-assistant/apps/worker/task_execution_runtime.py)
- Core 运行时：
  - [core/task_runtime.py](/opt/ai-assistant/core/task_runtime.py)
  - [core/long_term_memory.py](/opt/ai-assistant/core/long_term_memory.py)
  - [core/fast_path_runtime.py](/opt/ai-assistant/core/fast_path_runtime.py)
- 基础设施：
  - PostgreSQL 16
  - Redis 7
- 调度器：
  - [scripts/daily_review_scheduler.py](/opt/ai-assistant/scripts/daily_review_scheduler.py)

## 目录结构

```text
.
├── apps/
│   ├── api/
│   ├── web/
│   └── worker/
├── core/
├── docs/
├── infra/compose/
├── migrations/
├── requirements/
├── scripts/
├── skills/
├── tests/
├── package.json
├── playwright.config.js
├── RELEASE_CHECKLIST.md
└── README.md
```

## 快速开始

### 1. 准备环境变量

本地开发建议从模板开始：

```bash
cp .env.example .env
```

如果你想按环境分层配置，可以参考：

- [env.sample.local](/opt/ai-assistant/env.sample.local)
- [env.sample.validation](/opt/ai-assistant/env.sample.validation)
- [env.sample.production](/opt/ai-assistant/env.sample.production)

### 2. 启动服务

```bash
docker compose -f infra/compose/docker-compose.yml up -d --build
```

默认端口：

- Web: `http://localhost:8080`
- API: `http://localhost:8000`
- Postgres: `localhost:5432`

### 3. 初始化数据库

首次启动后执行：

```bash
python3 scripts/run_migrations.py
curl -X POST http://localhost:8000/init-db
```

发布后或容器重建后，可继续执行：

```bash
bash scripts/runtime_version_check.sh
```

这样可以把运行中的 `/runtime-metadata` 与当前仓库 `version.json` / git commit 做对比，避免“代码修了但服务跑的不是这版”。

### 4. 打开控制台

浏览器访问：

```text
http://localhost:8080
```

如果前端和 API 不在默认同机端口组合，或者你通过反向代理访问控制台，可以显式指定：

```text
http://localhost:8080/?api_base=http://localhost:8000
```

如果本地重建容器后 API 启动日志出现 `password authentication failed for user "assistant"`，通常说明当前 `.env` 里的 `POSTGRES_PASSWORD` 和已有 Postgres 数据卷初始化时的密码不一致。可以执行：

```bash
bash scripts/repair_local_postgres_auth.sh
docker compose -f infra/compose/docker-compose.yml restart api worker scheduler
```

当前 Web 控制台支持：

- 六域导航：
  - 工作台
  - 任务起草器
  - 任务
  - 工作区
  - Sessions
  - 治理
  - 监控
  - 设置
- 首页工作台：
  - 待处理事项与最近交付
  - 全局运行状态条
- 任务起草器：
  - 独立页面
  - 输入分流与草稿确认
  - fast_path 轻量回答
  - 多轮任务对话
  - 开始新任务对话
  - 每个任务对话绑定独立 session
- 任务域：
  - 任务运营视图
  - 状态 / 动作筛选
  - 任务驾驶舱
  - 步骤时间线
  - traces / replay
  - approvals / recovery / clarify
- Session 域：
  - sessions / reviews / state / health
  - 长期记忆检索与引用说明
- 治理与监控：
  - governance / monitor
  - actor、quota、change request、tool registry、model providers/routes
- 设置：
  - 当前 API Base
  - 当前 Actor
  - 自动刷新与界面偏好
  - 模型路由快照

## 常用命令

### 运行与健康检查

```bash
bash scripts/healthcheck.sh
bash scripts/acceptance_check.sh
bash scripts/governance_check.sh
bash scripts/session_memory_check.sh
bash scripts/approval_retry_check.sh
bash scripts/claim_lease_check.sh
bash scripts/daily_review_check.sh
```

### CLI

CLI 入口：

- [scripts/assistant_cli.py](/opt/ai-assistant/scripts/assistant_cli.py)

常用示例：

```bash
./scripts/assistant_cli.py task list
./scripts/assistant_cli.py task create -i "读取 /workspace/test_note.txt 并整理要点"
./scripts/assistant_cli.py task show 1
./scripts/assistant_cli.py steps 1
./scripts/assistant_cli.py sessions list
./scripts/assistant_cli.py sessions summary 1
./scripts/assistant_cli.py approvals list --status pending
```

### 工程化检查

```bash
bash scripts/py_compile_check.sh
bash scripts/daily_checks.sh
RUN_E2E=1 bash scripts/regression_checks.sh
python3 -m pytest -q
npm run check:web
bash scripts/release_readiness_check.sh
```

## 浏览器 E2E

仓库已经接入 Playwright 浏览器级回归。

相关文件：

- [package.json](/opt/ai-assistant/package.json)
- [playwright.config.js](/opt/ai-assistant/playwright.config.js)
- [tests/e2e/dashboard.spec.js](/opt/ai-assistant/tests/e2e/dashboard.spec.js)
- [tests/e2e/mock_api_server.py](/opt/ai-assistant/tests/e2e/mock_api_server.py)

执行方式：

```bash
npm ci
npx playwright install --with-deps chromium
npm run test:e2e
```

说明：

- 当前 E2E 默认走仓库内 mock API，以保证前端交互回归可重复、可在 CI 稳定执行
- API 真链路验证仍由 `pytest`、shell 检查脚本和 compose 验证补充覆盖

## CI / 质量门禁

仓库已接入 GitHub Actions CI：

- [ci.yml](/opt/ai-assistant/.github/workflows/ci.yml)

当前 CI 包含：

- Python 编译检查
- 前端脚本语法检查
- `pytest` + `pytest-cov`
- Playwright 浏览器 E2E
- Docker Compose 配置校验
- API / Worker / Scheduler 镜像构建

## 多环境配置

环境分层说明见：

- [docs/environment_matrix.md](/opt/ai-assistant/docs/environment_matrix.md)

当前建议区分：

- Local
- Validation / CI
- Production

API / Worker 在非容器本地运行时，默认会把运行目录回退到仓库内：

- `logs/`
- `data/checkpoints/`
- `data/artifacts/`
- `data/workspace/`

## 发布与回滚

发布前优先执行：

```bash
bash scripts/release_readiness_check.sh
```

发布与回滚手册见：

- [docs/release_runbook.md](/opt/ai-assistant/docs/release_runbook.md)
- [RELEASE_CHECKLIST.md](/opt/ai-assistant/RELEASE_CHECKLIST.md)
- [CHANGELOG.md](/opt/ai-assistant/CHANGELOG.md)

## 文档导航

如果你刚进入这个仓库，推荐按下面顺序阅读：

1. 项目运行与使用：
   - [docs/README.md](/opt/ai-assistant/docs/README.md)
   - [docs/runbook.md](/opt/ai-assistant/docs/runbook.md)
2. 接口与数据模型：
   - [docs/api_data_model_index.md](/opt/ai-assistant/docs/api_data_model_index.md)
3. 发布与运维：
   - [docs/release_runbook.md](/opt/ai-assistant/docs/release_runbook.md)
   - [docs/operations_runbook.md](/opt/ai-assistant/docs/operations_runbook.md)
4. 协议与执行路线：
   - [docs/structured_step_protocol_v1.md](/opt/ai-assistant/docs/structured_step_protocol_v1.md)
   - [docs/multi_agent_protocol_v1.md](/opt/ai-assistant/docs/multi_agent_protocol_v1.md)
   - [docs/execution_roadmap.md](/opt/ai-assistant/docs/execution_roadmap.md)

## 当前边界与说明

当前仓库已经具备较完整的平台能力，但仍要注意：

- `apps/api/main.py` 和 `apps/worker/worker.py` 仍然偏大，虽然已经开始继续拆分
- 平台能力已打通，不等于产品交付闭环已经完全收口
- 浏览器 E2E 已接入，但本地执行仍依赖 Playwright/Chromium 运行环境
- `main.py` 与 `worker.py` 现在已经收口为薄兼容入口，主要运行时上下文分别位于 `apps/api/api_app_context.py` 与 `apps/worker/worker_runtime_context.py`
- 覆盖率统计已接入，但深层治理链和 worker 主链仍有继续补测空间

## 相关文件

- 贡献规范：[CONTRIBUTING.md](/opt/ai-assistant/CONTRIBUTING.md)
- 安全说明：[SECURITY.md](/opt/ai-assistant/SECURITY.md)
- 当前版本：[version.json](/opt/ai-assistant/version.json)
