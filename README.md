# AI Assistant

一个本地运行的个人 AI 助理系统，目标是把“自然语言任务 -> 规划 -> 工具执行 -> 审批 -> 恢复执行 -> 审计”这条链路先跑通，再逐步稳定化、助理化、企业化。

当前仓库已经不是纯骨架，而是一个可运行、可治理的个人 AI 助理系统：

- Web UI 提交任务、查看步骤、处理审批、查看 session/review/state、触发 daily review
- Web UI 已补齐 actor 上下文切换，并可查看 change requests、tool registry、model routes/providers、quota usage 等治理面板
- CLI 提交任务、查询任务、查看 checkpoint、处理审批、管理 sessions / reviews / access / tools / models / changes
- API + Worker + PostgreSQL 的任务执行链路
- Redis 队列、任务 claim、锁续租、stale requeue
- checkpoint 持久化、interrupt / resume
- 高风险步骤审批、失败重试、审计日志
- session working memory、自动记忆沉淀、daily review scheduler
- 多角色权限、任务配额、工具注册中心、多模型路由、正式变更管理与强制门禁
- 最小模型 Provider 注册中心，为后续多 provider 路由预留治理边界

## 当前进展

按本文后面的路线图来看，当前状态大致是：

- 阶段 1：已完成
- 阶段 2：已完成
- 阶段 3：大部分完成
- 阶段 4：持续推进中

阶段对照：

| 阶段 | 状态 | 说明 |
| --- | --- | --- |
| 阶段 1：最小可用版 MVP | 已完成 | Web/CLI、Planner、状态表、审批、日志、重试、审批页都已具备 |
| 阶段 2：稳定化 | 已完成 | checkpoint、interrupt/resume、Redis 队列、风控、白名单、备份脚本、监控概览面板、structured step adapter 化均已落地；当前保留自研 runtime，LangGraph 化暂缓。 |
| 阶段 3：助理化 | 大部分完成 | `sessions`、`session_memories`、`session_state`、`state-rebuild`、自动记忆沉淀、session review、daily review scheduler、session 工作台均已落地；更深层记忆质量和技能体系仍可继续扩展。 |
| 阶段 4：企业化预埋 | 持续推进中 | `audit_logs`、多角色权限、actor 级任务配额、工具注册中心、最小多 provider/多模型治理、正式变更管理都已落地；`model_route / model_provider / tool_registry / risk_policy` 已切入强制变更门禁，MCP 工具服务化仍未开始。 |

### 当前焦点

当前的实现重点已经不再是 Stage 2 收口，而是：

- 维持现有 runtime、session 与 scheduler 主链稳定
- 继续补强 Stage 4 的治理能力
- 让高风险控制面逐步进入正式变更流程
- 为后续的多 provider 路由或 MCP 工具服务化预留接口

从“可运行平台”继续走向“更像个人 AI 助理操作系统”的后续设计见：

- [docs/personal_ai_os_roadmap.md](/opt/ai-assistant/docs/personal_ai_os_roadmap.md)

### Step Request 协议

当前 structured runner 使用两层 request 协议，当前冻结版本记为 `stage2-v1`：

- `StepExecutionRequest`
  - `step_order`
  - `current_status`
  - `tool_name`
  - `raw_input`
  - `run_if`
  - `skip_if`
  - `error_strategy`
  - `max_retries`
  - `retry_count`
- `EnrichedStepExecutionRequest`
  - 继承 `StepExecutionRequest`
  - 追加 `should_run`
  - 追加 `skip_reason`
  - 追加 `resolved_input`
  - 追加 `approval_required`
  - 追加 `approval_reason`
  - 追加 `effective_retry_count`
  - 追加 `effective_max_retries`
  - 追加可选 `result`

这份协议是当前 runtime 的稳定边界。现在默认它的字段集合保持稳定，除非后续真的进入新一轮执行引擎升级。

运行时也可以直接查询这份协议：

```bash
curl -sS "http://localhost:8000/runtime-metadata"
./scripts/assistant_cli.py runtime show
```

## 仓库现在能做什么

- 接收自然语言任务并写入任务表
- 由 Worker 规划步骤并按顺序执行工具
- 在高风险步骤触发人工审批
- 在失败后按步骤级策略进行重试
- 在任务中断、暂停、审批后进行恢复执行
- 通过 checkpoint 追踪当前进度
- 通过 `audit_logs` 追踪审批、恢复、中断、风险策略变更等关键事件
- 通过风险策略表动态调整风控规则，而不是改代码
- 通过监控概览面板查看任务状态、队列深度、待审批数、最近审计事件
- 通过 `access_actors` 对敏感操作做第一版角色控制
- 通过 `sessions` 把多条任务归到同一会话容器下，作为 Stage 3 的入口

## Access Control

Stage 4 的第一刀已经落地为一个很克制的多角色权限模型：

- `viewer`
  - 只允许只读查询
- `operator`
  - 允许创建任务、处理审批、维护 session state / memories / reviews
- `admin`
  - 额外允许初始化数据库、修改风险策略、执行批量 `daily-run`、维护 actor 角色

当前角色信息保存在 `access_actors` 表，默认会种下三条本地 actor：

- `local_admin`
- `local_operator`
- `local_viewer`

API 通过请求头 `X-Actor-Name` 识别当前 actor；如果不传，会兼容地默认成 `local_admin`，这样不会打断现有脚本和前端。

CLI 也已经支持通过环境变量切换 actor：

```bash
AI_ACTOR=local_viewer ./scripts/assistant_cli.py task list
AI_ACTOR=local_operator ./scripts/assistant_cli.py task create -i "读取 /workspace/test_note.txt 并整理要点"
AI_ACTOR=local_admin ./scripts/assistant_cli.py actors list
AI_ACTOR=local_admin ./scripts/assistant_cli.py actors set-role audit_bot viewer --description "审计专用只读角色"
```

当前监控概览里也会显示：

- `Actors`
- `Quotas`
- 角色分布 `admin / operator / viewer`

## Tool Registry

Stage 4 这条线现在也有了第一版工具注册中心，目标是把“当前有哪些工具可用、哪些被禁用、每个工具的风险级别是什么”从代码常量推进成可治理状态。

当前工具注册信息保存在 `tool_registry_entries` 表，对外仍然通过 `/tools` 暴露。

现在支持：

- `GET /tools`
- `PUT /tools/{tool_name}`
- worker 执行前检查工具是否启用
- 监控概览显示：
  - `注册工具数`
  - `禁用工具数`

CLI 用法：

```bash
AI_ACTOR=local_admin ./scripts/assistant_cli.py tools list
AI_ACTOR=local_admin ./scripts/assistant_cli.py tools set web_search --enabled false --risk-level low --description "临时禁用联网搜索"
AI_ACTOR=local_admin ./scripts/assistant_cli.py tools set web_search --enabled true --risk-level low --description "执行联网搜索。"
```

当前这一版的行为重点是：

- API 侧可查询、可切换启用状态
- worker 侧会在真正执行工具前拦截被禁用的工具
- 工具配置变更会写入 `audit_logs`

## Model Routes

Stage 4 现在也有了第一版多模型路由，而且已经开始拆成 `provider + route` 两层治理，只先覆盖当前最关键的 3 类模型调用：

- `planner`
- `summarize_text`
- `web_search_summary`

当前模型路由信息保存在 `model_routes` 表。每条路由包含：

- `provider`
- `model_name`
- `temperature`
- `max_tokens`
- `enabled`

当前模型 provider 信息保存在 `model_providers` 表。每条 provider 包含：

- `driver`
- `base_url`
- `api_key_env`
- `enabled`

对外接口：

- `GET /model-providers`
- `PUT /model-providers/{provider_name}`
- `GET /model-routes`
- `PUT /model-routes/{route_name}`

CLI 用法：

```bash
AI_ACTOR=local_admin ./scripts/assistant_cli.py models list
AI_ACTOR=local_admin ./scripts/assistant_cli.py models providers
AI_ACTOR=local_admin ./scripts/assistant_cli.py models provider-set deepseek_default --driver openai_compatible --base-url https://api.deepseek.com --api-key-env DEEPSEEK_API_KEY --enabled true --description "默认 DeepSeek provider"
AI_ACTOR=local_admin ./scripts/assistant_cli.py models set planner --provider deepseek_default --enabled true --model-name deepseek-chat --temperature 0.2 --max-tokens 1500 --description "任务规划模型"
AI_ACTOR=local_admin ./scripts/assistant_cli.py models set summarize_text --provider deepseek_default --enabled true --model-name deepseek-chat --temperature 0.2 --max-tokens 800 --description "文本摘要模型"
```

当前这一版的目标不是立刻上复杂多 provider 编排，而是先把“provider 在哪里、路由指向哪个 provider、不同调用场景用哪个模型、温度和 token 上限是什么”从代码常量收进治理面。

## Change Management

Stage 4 现在也有了第一版正式变更管理。当前重点不是强制所有入口都必须走变更单，而是先把“可提交、可审批、可应用、可审计”的治理外壳立起来。

当前变更单保存在 `change_requests` 表，支持这些目标类型：

- `risk_policy`
- `tool_registry`
- `model_route`
- `model_provider`
- `access_quota`
- `access_actor`

对外接口：

- `GET /change-requests`
- `POST /change-requests`
- `POST /change-requests/{id}/approve`
- `POST /change-requests/{id}/reject`
- `POST /change-requests/{id}/apply`

CLI 用法：

```bash
AI_ACTOR=local_admin ./scripts/assistant_cli.py changes list
AI_ACTOR=local_operator ./scripts/assistant_cli.py changes create access_actor change_bot '{"role":"viewer","description":"变更管理 smoke actor"}' --rationale "新建只读 actor"
AI_ACTOR=local_admin ./scripts/assistant_cli.py changes approve 1 --note "批准"
AI_ACTOR=local_admin ./scripts/assistant_cli.py changes apply 1
```

当前监控概览也会显示：

- `变更单总数`
- `待处理变更单`
- `强制门禁目标`

当前也已经有一层“可配置强制门禁”：

- 环境变量：`CHANGE_GATE_ENFORCED_TARGET_TYPES`
- 取值是逗号分隔的 target type 列表，例如：
  - `risk_policy,tool_registry,model_route`

默认不强制，所以现有直改入口仍然兼容。  
当前 compose 默认已经先对 `model_route,model_provider,tool_registry,risk_policy` 启用强制门禁。  
一旦把某类 target type 加进这个环境变量，对应直改接口就会返回 `409`，并提示改走 change request 流程；通过 `change-requests/{id}/apply` 落地的变更不受影响。

## Task Quotas

Stage 4 现在也有了第一版 actor 级任务配额，目标是先拦住最直接的“过量提交”风险。

当前配额保存在 `access_quotas` 表，按 actor 生效，先控制两个维度：

- `daily_task_limit`
  - 单个 actor 当天最多能创建多少任务
- `active_task_limit`
  - 单个 actor 同时最多能持有多少个未结束任务

默认配额：

- `local_admin`
  - `daily_task_limit=1000`
  - `active_task_limit=200`
- `local_operator`
  - `daily_task_limit=50`
  - `active_task_limit=20`
- `local_viewer`
  - `daily_task_limit=0`
  - `active_task_limit=0`

超额时，`POST /tasks` 会返回 `429`，并拒绝继续创建任务。

CLI 用法：

```bash
AI_ACTOR=local_admin ./scripts/assistant_cli.py quotas list
AI_ACTOR=local_admin ./scripts/assistant_cli.py quotas usage
AI_ACTOR=local_admin ./scripts/assistant_cli.py quotas set local_operator --daily-task-limit 30 --active-task-limit 10
```

同时现在也可以通过 `GET /access/quota-usage` 或 `quotas usage` 查看每个 actor 的：

- `daily_task_count`
- `active_task_count`
- `daily_remaining`
- `active_remaining`

监控概览里也会显示一个 `配额压力` 指标，用来提示当前有多少 actor 已经触达或超过自己的配额边界。

## Sessions

Stage 3 已经从“最小会话容器”推进到“会话级 working memory”的第一版。

现在你可以：

- 创建 session
- 列出 session
- 查看单个 session
- 查看某个 session 的摘要
- 向某个 session 手动写入 memory
- 查看某个 session 下的 memories
- 任务完成后自动沉淀 `task_summary` memory
- 查看某个 session 下的任务
- 创建任务时附带 `session_id`
- 手动触发一次 session review / 复盘

`GET /sessions/{id}/summary` 现在除了返回 `total_memories`，还会返回 `memory_metrics.by_category`，方便直接观察当前 session 的记忆构成。

最短示例：

```bash
./scripts/assistant_cli.py sessions create demo --description "stage3 session"
./scripts/assistant_cli.py sessions list
./scripts/assistant_cli.py sessions show 1
./scripts/assistant_cli.py sessions summary 1
./scripts/assistant_cli.py sessions remember 1 --category preference --content "偏好简洁回答" --importance 4
./scripts/assistant_cli.py sessions memories 1
./scripts/assistant_cli.py sessions state 1
./scripts/assistant_cli.py sessions state-set 1 --summary-text "当前在收口 Stage 3" --preferences '["偏好简洁回答"]' --open-loops '["设计自动记忆提炼"]'
./scripts/assistant_cli.py sessions state-rebuild 1
./scripts/assistant_cli.py sessions review-create 1 --review-kind daily --note "阶段复盘"
./scripts/assistant_cli.py sessions reviews 1
./scripts/assistant_cli.py reviews daily-run --review-kind daily --session-limit 20 --active-within-hours 24
./scripts/daily_review_run.sh
docker compose -f infra/compose/docker-compose.yml up -d scheduler
./scripts/assistant_cli.py sessions tasks 1
./scripts/assistant_cli.py task create -i "读取 /workspace/test_note.txt 并整理要点" --session-id 1
```

当前 memory 已经不是纯手动模型：

- 先挂在 `session` 下
- 支持人工写入和查看
- 成功完成的 session 任务会自动沉淀 `task_summary`
- 对带明显偏好提示的任务，会自动提炼 `preference`
- 会附带生成一条轻量 `fact` memory，作为后续更结构化提炼的过渡
- 字段只保留 `category`、`content`、`importance`、`source_task_id`
- `preference` / `open_loop` / `todo` / `follow_up` 写入后会自动并入 `session_state`
- 还没有模型驱动提炼、偏好学习强化和分层检索

在此之上，当前也新增了一层最小 `session state`，用于承载会话级 working memory：

- `summary_text`
- `preferences`
- `open_loops`

这一层现在已经支持两种自动维护方式：

- 写入 `preference` / `open_loop` / `todo` / `follow_up` memory 时自动同步
- session 任务完成后自动沉淀 `task_summary`
- 对带明显偏好提示的任务自动提炼 `preference`
- 每次自动沉淀后都会重建该 session 的 working memory state

同时也保留了第一版自动重建接口，会从该 session 的 `tasks + memories` 规则化生成 working memory state，但还不是模型驱动总结。

在此之上，现在也有了第一版 `session review`：

- `POST /sessions/{id}/reviews`
- `GET /sessions/{id}/reviews`
- `POST /reviews/daily-run`

当前 review 先走规则聚合，会汇总该 session 的：

- 任务状态分布
- memory 分类构成
- 当前偏好
- 最近完成事项
- open loops

`/reviews/daily-run` 会批量扫描最近活跃的 sessions，默认按“同一 session + 同一 review_kind + 同一天”去重，适合作为后续 cron/定时任务入口。

现在仓库里也已经接入了真正的 scheduler 服务：

- compose 服务名：`scheduler`
- 进程脚本：[daily_review_scheduler.py](/opt/ai-assistant/scripts/daily_review_scheduler.py)
- 默认每小时触发一次 `daily` review 批跑

最重要的环境变量有：

- `DAILY_REVIEW_INTERVAL_SECONDS`
- `DAILY_REVIEW_STARTUP_DELAY_SECONDS`
- `DAILY_REVIEW_KIND`
- `DAILY_REVIEW_SESSION_LIMIT`
- `DAILY_REVIEW_ACTIVE_WITHIN_HOURS`
- `DAILY_REVIEW_FORCE`
- `DAILY_REVIEW_NOTE`

监控概览面板现在也会直接显示：

- `Session Reviews`
- `今日 Daily Reviews`
- `最近 Daily Review`
- `最近 Reviews`

选中一个绑定了 `session_id` 的任务后，页面里还会显示该 session 最近的 review 历史。

现在同一个区域里也会显示该 session 的 working memory state，包括：

- `summary_text`
- `preferences`
- `open_loops`

Web 工作台现在还支持两个直接操作：

- 手动创建一次 `session review`
- 手动触发一次 `state rebuild`
- 手动触发一次全局 `daily review` 批跑

可以使用这条专项验收脚本验证 Stage 3 当前能力：

```bash
bash scripts/session_memory_check.sh
```

## 目录结构

当前仓库的核心目录：

```text
apps/
  api/       FastAPI 控制面
  worker/    后台任务执行器
  web/       Web 面板
docs/
  runbook.md 运行手册
infra/
  compose/   Docker Compose
scripts/
  assistant_cli.py
  acceptance_check.sh
  approval_retry_check.sh
  claim_lease_check.sh
  governance_check.sh
  healthcheck.sh
  backup.sh
data/
  artifacts/
  checkpoints/
  workspace/
logs/
```

## 架构概览

系统当前是一个以 PostgreSQL 为状态中心、以 Redis 为队列与锁协调层的任务执行平台。

主链路：

1. 用户通过 Web 或 CLI 提交任务
2. API 写入 `task_runs`
3. API 把任务推入 Redis 队列
4. Worker 抢占任务 claim，开始执行
5. Worker 规划步骤，逐步执行工具
6. 每一步写入 `task_steps`，并持续更新 checkpoint
7. 高风险步骤进入 `waiting_approval`
8. 审批通过后任务继续执行；拒绝则失败
9. 关键动作写入 `audit_logs`

## 核心组件

### API

入口文件：[apps/api/main.py](/opt/ai-assistant/apps/api/main.py)

职责：

- 创建任务
- 查询任务 / 步骤 / 审批 / checkpoint / 审计日志
- 审批通过或拒绝
- interrupt / resume
- 风险策略查询与更新
- 初始化数据库结构

### Worker

入口文件：[apps/worker/worker.py](/opt/ai-assistant/apps/worker/worker.py)

职责：

- 从 Redis / 数据库领取任务
- 进行 claim / 续租 / 释放
- 检测 stale running task 并重新入队
- 规划任务步骤
- 执行工具
- 写 checkpoint、步骤状态、产物
- 触发审批与重试
- 写 worker 侧审计事件

### Web

入口文件：[apps/web/index.html](/opt/ai-assistant/apps/web/index.html)

能力：

- 任务列表与任务详情
- 步骤详情
- 待审批列表与批准/拒绝
- 风险策略查看与编辑

### CLI

入口文件：[scripts/assistant_cli.py](/opt/ai-assistant/scripts/assistant_cli.py)

能力：

- `task list/create/show/resume/interrupt`
- `steps`
- `checkpoint`
- `approvals list/decide`
- `risk list/set`
- `actors list`
- `actors set-role`
- `quotas list`
- `quotas usage`
- `quotas set`
- `tools list`
- `tools set`
- `models list`
- `models set`
- `changes list`
- `changes create`
- `changes approve`
- `changes reject`
- `changes apply`

## 数据模型

当前最关键的几张表：

- `task_runs`：任务主表
- `task_steps`：任务步骤表
- `approvals`：审批表
- `risk_policies`：数据库驱动的风控策略表
- `audit_logs`：关键动作审计表

## 风控与审批

当前风控已经不是单纯写死在代码里，而是“代码 + 数据库策略”的组合。

默认规则包括：

- `shell_exec`：始终审批
- `http_request`：非 `GET` 请求默认审批
- `file_write` / `write_json`：覆盖已有文件、隐藏文件、脚本/配置类文件默认审批
- 低风险产出文件类型可直接放行，例如 `.txt`、`.md`、`.csv`、`.log`

这些策略现在可以通过 API / CLI / Web 面板调整。

## 审计日志

当前已落地的审计事件包括：

- `approval.approve`
- `approval.reject`
- `task.resume`
- `task.interrupt`
- `risk.update`
- `task.stale_requeue`
- `task.claim_lost`

查询接口：

```bash
curl -sS "http://localhost:8000/audit-logs"
curl -sS "http://localhost:8000/audit-logs?task_id=502"
curl -sS "http://localhost:8000/audit-logs?event_type=risk.update"
```

## 快速启动

在仓库根目录执行：

```bash
docker compose -f infra/compose/docker-compose.yml up -d --build
curl -X POST http://localhost:8000/init-db
```

启动后默认入口：

- Web：`http://localhost:8080`
- API：`http://localhost:8000`
- Postgres：`localhost:5432`
- Redis：`localhost:6379`

## 常用命令

查看任务：

```bash
./scripts/assistant_cli.py task list
```

创建任务：

```bash
./scripts/assistant_cli.py task create -i "读取 /workspace/test_note.txt 并整理要点"
```

查看任务步骤：

```bash
./scripts/assistant_cli.py steps 1
```

查看待审批：

```bash
./scripts/assistant_cli.py approvals list --status pending
```

批准审批：

```bash
./scripts/assistant_cli.py approvals decide 12 --approve --note "允许执行"
```

查看风险策略：

```bash
./scripts/assistant_cli.py risk list
```

修改风险策略：

```bash
./scripts/assistant_cli.py risk set approval_allowed_http_methods '["GET","HEAD"]'
```

查看 checkpoint：

```bash
./scripts/assistant_cli.py checkpoint 1
```

恢复任务：

```bash
./scripts/assistant_cli.py task resume 1 --from-step 2 --note "continue"
```

暂停任务：

```bash
./scripts/assistant_cli.py task interrupt 1 --note "pause now"
```

## 验收脚本

基础验收：

```bash
bash scripts/acceptance_check.sh
```

审批 + 重试专项验收：

```bash
bash scripts/approval_retry_check.sh
```

claim / 锁续租 / stale requeue 验收：

```bash
bash scripts/claim_lease_check.sh
```

治理专项验收：

```bash
bash scripts/governance_check.sh
```

健康检查：

```bash
bash scripts/healthcheck.sh
```

备份：

```bash
bash scripts/backup.sh
```

## 文档入口

- 运行手册：[docs/runbook.md](/opt/ai-assistant/docs/runbook.md)
- LangGraph 决策说明：[docs/langgraph_decision.md](/opt/ai-assistant/docs/langgraph_decision.md)
- runtime 模块化计划：[docs/runtime_boundary_plan.md](/opt/ai-assistant/docs/runtime_boundary_plan.md)
- Structured step 协议草案：[docs/structured_step_protocol_v1.md](/opt/ai-assistant/docs/structured_step_protocol_v1.md)
- `json_extract` 工具设计记录：[docs/next_tool_json_extract.md](/opt/ai-assistant/docs/next_tool_json_extract.md)

## 当前已知缺口

虽然主链已经比较完整，但还存在这些明显缺口：

- 当前只有基础监控概览，还没有更完整的独立监控系统
- checkpoint 能力已具备，但不是正式基于 LangGraph
- 还没有 MCP 工具服务化
- 还没有更完整的多 provider 策略编排与 provider 级验收脚本
- skills / prompt library 仍未系统化

## 路线图

### 阶段 0：准备期

目标：搭好基础运行环境。

交付物：

- Ubuntu + Docker Compose 基础环境
- 项目目录
- `.env.example`
- README / runbook

### 阶段 1：最小可用版 MVP

目标：跑通“自然语言任务 -> 工具执行 -> 状态记录”。

范围：

- Web / CLI 输入
- Planner
- 基础工具
- PostgreSQL 状态表
- 审批表
- 简单日志
- 失败重试
- 人工审批页

当前状态：已完成

### 阶段 2：稳定化

目标：从能跑变成稳跑。

范围：

- checkpoint
- interrupt / resume
- Redis 队列
- 更完善的风控策略
- 工作目录隔离
- tool 白名单
- 监控面板
- 备份脚本

当前状态：已完成

### 阶段 3：助理化

目标：从“工作流引擎”变成“像助理”。

范围：

- sessions
- 定时复盘
- 记忆分层
- 偏好学习
- 每日总结
- 常见任务模板
- skills / prompt library

当前状态：大部分完成

### 阶段 4：企业化预埋

目标：为以后多用户、多项目、多系统接入做准备。

范围：

- MCP 工具服务化
- 多角色权限
- 审计增强
- 工具注册中心
- 任务配额
- 多模型路由
- 更正式的变更管理

当前状态：持续推进中

### 阶段 5：多 Agent 协作层

目标：从“单执行器平台”升级成“有角色分工的协作系统”。

范围：

- manager / specialist / reviewer / operator 角色模型
- 子任务拆分协议
- agent artifact 协议
- fan-out / fan-in
- reviewer 独立评估
- agent 级审计与成本统计

当前状态：未开始

### 阶段 6：评估与自我改进层

目标：让系统开始知道“什么算做得好”，并能在受控边界里持续改进 workflow。

范围：

- success criteria
- evaluator pipeline
- failure taxonomy
- workflow improvement proposal
- shadow run / canary 验证
- review 结果反哺 prompt / workflow / route

当前状态：未开始

### 阶段 7：受控自修改与安全回滚层

目标：允许系统在严格治理边界里修改自己的实现，并在失败时自动回退。

范围：

- patch / rollback artifact
- workflow 与 prompt 版本化
- 受控配置自修改
- 受控代码 patch 实验
- 自动验收与自动回滚
- proposal / rollback 审计追踪

当前状态：未开始

Stage 5-7 的详细设计、门槛与验收标准见：

- [docs/personal_ai_os_roadmap.md](/opt/ai-assistant/docs/personal_ai_os_roadmap.md)
