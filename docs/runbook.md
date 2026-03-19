# AI Assistant Runbook

## 目标

这个 runbook 对应当前仓库已经落地的可运行版本，用来说明：

- 怎么启动系统
- 怎么初始化数据库
- 怎么用 Web 和 CLI 提交任务
- 怎么处理审批
- 怎么查看日志
- 怎么跑 MVP 验收
- 怎么使用当前的治理与变更能力

架构方向上的正式决策见：

- [docs/langgraph_decision.md](/opt/ai-assistant/docs/langgraph_decision.md)
- [docs/personal_ai_os_roadmap.md](/opt/ai-assistant/docs/personal_ai_os_roadmap.md)
- [docs/multi_agent_protocol_v1.md](/opt/ai-assistant/docs/multi_agent_protocol_v1.md)
- [docs/stage3_stage4_closure_checklist.md](/opt/ai-assistant/docs/stage3_stage4_closure_checklist.md)
- [docs/stage5_stage6_closure_checklist.md](/opt/ai-assistant/docs/stage5_stage6_closure_checklist.md)
- [docs/stage5_stage6_readiness_checklist.md](/opt/ai-assistant/docs/stage5_stage6_readiness_checklist.md)

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
- 在任务工作区查看 `Agents` 子页签
- 在页面里触发 `bootstrap-demo / finalize-demo`
- 在页面里展开查看 agent messages / artifacts
- 在页面里批准/拒绝审批
- 切换 Web actor 上下文（`local_admin` / `local_operator` / `local_viewer`）
- 查看治理面板：change requests、tool registry、model providers/routes、quota usage
- 在页面里创建 / 批准 / 拒绝 / 应用 change request

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

Stage 3 起步后，CLI 也已经支持最小 sessions 闭环：

```bash
./scripts/assistant_cli.py sessions create demo --description "stage3 session"
./scripts/assistant_cli.py sessions list
./scripts/assistant_cli.py sessions show 1
./scripts/assistant_cli.py sessions summary 1
./scripts/assistant_cli.py sessions health 1
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

Stage 5 / Stage 6 现在已经有一条主链 runtime + postrun：普通任务执行期即可 fan-out 至多个 runtime specialists，manager 在执行尾声汇总 fan-in，终态再由 evaluator / workflow proposal 收口；下面这些命令则保留为 demo/worker smoke 与调试入口：

```bash
./scripts/assistant_cli.py agent-runs summary 1 --compact
./scripts/assistant_cli.py agent-runs status
./scripts/assistant_cli.py agent-runs list
./scripts/assistant_cli.py agent-runs show 1
./scripts/assistant_cli.py agent-runs messages 1
./scripts/assistant_cli.py agent-runs artifacts 1
./scripts/assistant_cli.py agent-runs bootstrap-demo 1 --specialist-count 2
./scripts/assistant_cli.py agent-runs execute-worker-demo 1 --note "worker path"
./scripts/assistant_cli.py agent-runs execute-worker-demo 1 --subtask-type readonly_source_snapshot --source-kind json_file --source-path /workspace/example.json --source-json-path meta.title
./scripts/assistant_cli.py agent-runs execute-worker-demo 1 --subtask-type readonly_task_snapshot --force-rerun
./scripts/assistant_cli.py agent-runs finalize-demo 1 --summary "manager final" --reviewer-decision approved
./scripts/assistant_cli.py evaluator-runs latest 1 --compact
./scripts/assistant_cli.py workflow-proposals list --priority high
./scripts/assistant_cli.py workflow-proposals latest 1 --compact
./scripts/assistant_cli.py workflow-proposals draft 1
./scripts/assistant_cli.py workflow-proposals create-change 1 access_actor demo_actor '{"role":"viewer","description":"from workflow proposal"}'
```

当前 Stage 5 / Stage 6 已经具备的最小能力：

- `AUTO_STAGE5_POSTRUN_ENABLED=1` 时，普通任务在执行期即可 fan-out 至多个 runtime specialists，manager 会在执行尾声 fan-in，再由终态 postrun 收敛 evaluator / workflow proposal
- `GET /tasks/{id}` 与 `GET /tasks/{id}/agent-runs/summary` 会标记 `implementation_status=task_runtime_postrun_v1`，并暴露 `runtime_fanout_active=true`、`record_origin=mainline_runtime` 或 `mainline_postrun`、`control_mode=observe_only`、`execution_backend=mainline`
- demo 接口仍保留，但改为单次写入 smoke：如果任务已经有主链 postrun 记录，则 `bootstrap-demo / finalize-demo` 会返回 `409`
- bootstrap 生成 `manager / specialist / reviewer`
- worker 也能通过 `execute-worker-demo` 消费 `agent_runs.execution_request`
- worker specialist 支持：
  - `readonly_step_digest`
  - `readonly_source_snapshot`
  - `readonly_task_snapshot`
- finalize 生成 `draft / review / final`
- reviewer 决策：
  - `approved`
  - `rework_required`
  - `rejected`
- 返回 `quality_score / quality_criteria / step_stats`
- finalize 后会额外写入一条 `evaluator_run`，把评分、criteria、step_stats、建议动作单独沉淀
- evaluator 会附带 `workflow_proposal`，并暴露到 task summary 与 `GET /tasks/{task_id}/workflow-proposals/latest`
- proposal 也能通过 `GET /workflow-proposals`、`GET /tasks/{task_id}/workflow-proposals` 和 `workflow-proposals` CLI 命令做列表与筛选
- proposal 还支持桥接成 pending change request：
  - `GET /workflow-proposals/{id}/change-request-draft`
  - `POST /workflow-proposals/{id}/change-request-draft`
- proposal 还支持主链 shadow validation：
  - `POST /workflow-proposals/{id}/shadow-validate`
- 当前白名单自动建议：
  - `expand_specialist_scope -> model_route/planner`
- `monitor/overview.readiness_metrics.stage5/stage6` 会明确返回：
  - `operational=true`
  - `completed=true`
  - `completion_ratio=1.0`
  - Stage 5 / Stage 6 当前 completion gates 已全部满足
  - 其它 action 默认仍然保持手填

说明：

- `session -> 多个 tasks` 是当前最小会话模型
- 这一层现在已经承载最小 memory 闭环，并带第一版自动沉淀
- 后续的 memory / preference / review 都会优先挂靠到 session
- `session state` 是会话级 working memory，当前支持手动维护，也支持最小自动同步
- 成功完成的 session 任务会自动写入 `task_summary` memory
- 对带明显偏好提示的任务，worker 会额外提炼一条 `preference` memory
- 当前还会生成一条轻量 `fact` memory，作为后续更结构化提炼的过渡
- 每次自动沉淀后都会重建 session state
- `GET /sessions/{id}/summary` 里的 `memory_metrics` 现在同时包含 `total_memories` 和 `by_category`
- 现在也支持第一版 `session review`，可手动触发一次规则化复盘
- 现在也支持第一版 `daily review` 批量入口，可扫描最近活跃的 sessions 并批量创建 `daily` review
- 批量入口默认按“同一 session + 同一 review_kind + 同一天”去重，适合后续挂 cron
- compose 里已经有独立的 `scheduler` 服务，默认每小时触发一次 `daily` review
- 调度进程脚本在 [daily_review_scheduler.py](/opt/ai-assistant/scripts/daily_review_scheduler.py)
- 常用调度环境变量：
  `DAILY_REVIEW_INTERVAL_SECONDS`、`DAILY_REVIEW_STARTUP_DELAY_SECONDS`、`DAILY_REVIEW_KIND`、`DAILY_REVIEW_SESSION_LIMIT`、`DAILY_REVIEW_ACTIVE_WITHIN_HOURS`、`DAILY_REVIEW_FORCE`、`DAILY_REVIEW_NOTE`
- Web 监控概览现在也会显示 review / scheduler 相关指标，便于直接观察批量复盘是否在工作
- 选中带 `session_id` 的任务后，页面会额外展示该 session 最近的 review 列表
- 同时也会展示该 session 当前的 working memory state（summary / preferences / open_loops）
- Web 面板里可直接手动触发 `session review` 和 `state rebuild`
- 监控概览里也可直接手动触发一次 `daily review` 批跑
- `preference` / `open_loop` / `todo` / `follow_up` memory 写入后会自动并入 session state
- 现在也支持第一版 `state-rebuild`，会基于已有 tasks / memories 规则化重建 working memory

可用这条脚本验证 Stage 3 当前最小闭环：

```bash
bash scripts/session_memory_check.sh
```

脚本现在会同时覆盖 API / CLI 两条 Stage 3 操作路径，并校验 `monitor/overview` 中的 `readiness_metrics.stage3` 已达到 `readiness_ratio=1.0`、`operational=true`、`sessions_missing_state=0`、`sessions_missing_review=0`、`sessions_with_duplicate_memories=0`。

最近一次真实结果：

- `bash scripts/session_memory_check.sh` -> `PASS=35 FAIL=0 WARN=0`

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
AI_ACTOR=local_admin ./scripts/assistant_cli.py actors list
AI_ACTOR=local_admin ./scripts/assistant_cli.py actors set-role audit_bot viewer --description "审计专用只读角色"
AI_ACTOR=local_admin ./scripts/assistant_cli.py quotas list
AI_ACTOR=local_admin ./scripts/assistant_cli.py quotas usage
AI_ACTOR=local_admin ./scripts/assistant_cli.py quotas set local_operator --daily-task-limit 30 --active-task-limit 10
AI_ACTOR=local_admin ./scripts/assistant_cli.py tools list
AI_ACTOR=local_admin ./scripts/assistant_cli.py tools set web_search --enabled false --risk-level low --description "临时禁用联网搜索"
AI_ACTOR=local_admin ./scripts/assistant_cli.py tools set web_search --enabled true --risk-level low --description "执行联网搜索。"
AI_ACTOR=local_admin ./scripts/assistant_cli.py models list
AI_ACTOR=local_admin ./scripts/assistant_cli.py models providers
AI_ACTOR=local_admin ./scripts/assistant_cli.py models provider-set deepseek_default --driver openai_compatible --base-url https://api.deepseek.com --api-key-env DEEPSEEK_API_KEY --enabled true --description "默认 DeepSeek provider"
AI_ACTOR=local_admin ./scripts/assistant_cli.py models set planner --provider deepseek_default --enabled true --model-name deepseek-chat --temperature 0.2 --max-tokens 1500 --description "任务规划模型"
AI_ACTOR=local_admin ./scripts/assistant_cli.py changes list
AI_ACTOR=local_operator ./scripts/assistant_cli.py changes create access_actor change_bot '{"role":"viewer","description":"变更管理 smoke actor"}' --rationale "新建只读 actor"
AI_ACTOR=local_admin ./scripts/assistant_cli.py changes approve 1 --note "批准"
AI_ACTOR=local_admin ./scripts/assistant_cli.py changes apply 1
```

Web 页面也新增了“风险策略”面板，能把每条 policy 展示为卡片、原地切换编辑模式，并且同时支持布尔值和 JSON list 的保存操作。

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

## 7. Runtime 与治理现状

当前仓库当前已经具备这些基础能力：

- Redis 服务已加入 Compose
- 新任务会写入 Redis 队列
- Worker 会使用 Redis claim token + 锁续租，避免多 worker 时重复领取同一任务
- 每个任务会把 checkpoint 写到 `data/checkpoints/`
- API 提供 checkpoint 查询接口
- worker 会定期把“无锁且卡住太久”的运行中任务重新回队
- 风控策略已落库到 `risk_policies`，可通过 API / CLI 调整
- 审计日志已落库，包含审批、resume/interrupt、risk policy 变更、stale requeue 与 claim lost
- 第一版角色控制已落库到 `access_actors`，默认包含 `local_admin / local_operator / local_viewer`
- 工具注册中心已落库到 `tool_registry_entries`
- 模型 provider 注册中心已落库到 `model_providers`
- 多模型路由已落库到 `model_routes`
- 正式变更管理已落库到 `change_requests`
- `model_route / tool_registry / risk_policy` 已纳入强制变更门禁

## 多角色权限（第一版）

当前只先拦最敏感的变更入口，角色定义如下：

- `viewer`
  - 只允许只读接口
- `operator`
  - 允许创建任务、处理中断/恢复、审批、session memories / state / reviews
- `admin`
  - 额外允许 `init-db`、风险策略更新、`/reviews/daily-run`、actor 角色维护

API 通过请求头 `X-Actor-Name` 识别当前 actor；不传时默认走 `local_admin`，以保持历史脚本兼容。

CLI 通过环境变量 `AI_ACTOR` 透传这个 header，例如：

```bash
AI_ACTOR=local_viewer ./scripts/assistant_cli.py task list
AI_ACTOR=local_operator ./scripts/assistant_cli.py task create -i "读取 /workspace/test_note.txt 并整理要点"
AI_ACTOR=local_admin ./scripts/assistant_cli.py risk set approval_require_for_hidden_files false
```

## 任务配额（第一版）

当前已经有 actor 级配额表 `access_quotas`，先控制两类最小指标：

- `daily_task_limit`
- `active_task_limit`

默认值按角色给出：

- `admin` -> `1000 / 200`
- `operator` -> `50 / 20`
- `viewer` -> `0 / 0`

任务创建时会在 `POST /tasks` 前检查配额，超额直接返回 `429`。

常用命令：

```bash
AI_ACTOR=local_admin ./scripts/assistant_cli.py quotas list
AI_ACTOR=local_admin ./scripts/assistant_cli.py quotas usage
AI_ACTOR=local_admin ./scripts/assistant_cli.py quotas set local_operator --daily-task-limit 30 --active-task-limit 10
```

如果想直接看当前使用量，也可以查：

```bash
curl -sS "http://localhost:8000/access/quota-usage"
```

## 工具注册中心（第一版）

当前已经有最小工具注册中心，表名是 `tool_registry_entries`，对外接口仍然保持为 `/tools`。

当前能力：

- 查询当前所有已注册工具
- 由 `admin` 启用 / 禁用工具
- 为工具记录 `risk_level` 与描述
- worker 执行前会拦截被禁用的工具
- 监控概览会显示注册工具数和禁用工具数

常用命令：

```bash
AI_ACTOR=local_admin ./scripts/assistant_cli.py tools list
AI_ACTOR=local_admin ./scripts/assistant_cli.py tools set web_search --enabled false --risk-level low --description "临时禁用联网搜索"
AI_ACTOR=local_admin ./scripts/assistant_cli.py tools set web_search --enabled true --risk-level low --description "执行联网搜索。"
curl -sS "http://localhost:8000/tools"
```

这一版的目标不是插件化，而是先把“工具可否执行”收进治理面，便于审计、运维和后续企业化扩展。

## 多模型路由（第一版）

当前已经有最小多模型路由，表名是 `model_routes`。这版只先治理 3 类调用：

- `planner`
- `summarize_text`
- `web_search_summary`

当前已经拆成 `model_providers + model_routes` 两层：

- `model_providers`
  - `driver`
  - `base_url`
  - `api_key_env`
  - `enabled`
- `model_routes`
  - `provider`
  - `model_name`
  - `temperature`
  - `max_tokens`
  - `enabled`

对外接口：

- `GET /model-providers`
- `PUT /model-providers/{provider_name}`
- `GET /model-routes`
- `PUT /model-routes/{route_name}`

常用命令：

```bash
AI_ACTOR=local_admin ./scripts/assistant_cli.py models list
AI_ACTOR=local_admin ./scripts/assistant_cli.py models providers
AI_ACTOR=local_admin ./scripts/assistant_cli.py models provider-set deepseek_default --driver openai_compatible --base-url https://api.deepseek.com --api-key-env DEEPSEEK_API_KEY --enabled true --description "默认 DeepSeek provider"
AI_ACTOR=local_admin ./scripts/assistant_cli.py models set planner --provider deepseek_default --enabled true --model-name deepseek-chat --temperature 0.2 --max-tokens 1500 --description "任务规划模型"
AI_ACTOR=local_admin ./scripts/assistant_cli.py models set summarize_text --provider deepseek_default --enabled true --model-name deepseek-chat --temperature 0.2 --max-tokens 800 --description "文本摘要模型"
curl -sS "http://localhost:8000/model-providers"
curl -sS "http://localhost:8000/model-routes"
```

这一版还不是复杂多 provider 编排，但已经把“provider 在哪里、路由指向哪个 provider、不同场景走哪个模型、温度和 token 上限是什么”从代码常量提到治理层。

## 变更管理（第一版）

当前已经有最小正式变更管理，表名是 `change_requests`。

当前支持的变更目标类型：

- `risk_policy`
- `tool_registry`
- `model_route`
- `model_provider`
- `access_quota`
- `access_actor`

当前流程：

1. 创建变更单
2. 管理员批准或拒绝
3. 对已批准变更执行 apply
4. 自动写入审计日志

接口：

- `GET /change-requests`
- `POST /change-requests`
- `POST /change-requests/{id}/approve`
- `POST /change-requests/{id}/reject`
- `POST /change-requests/{id}/apply`

常用命令：

```bash
AI_ACTOR=local_admin ./scripts/assistant_cli.py changes list
AI_ACTOR=local_operator ./scripts/assistant_cli.py changes create access_actor change_bot '{"role":"viewer","description":"变更管理 smoke actor"}' --rationale "新建只读 actor"
AI_ACTOR=local_admin ./scripts/assistant_cli.py changes approve 1 --note "批准"
AI_ACTOR=local_admin ./scripts/assistant_cli.py changes reject 1 --note "拒绝原因"
AI_ACTOR=local_admin ./scripts/assistant_cli.py changes apply 1
curl -sS "http://localhost:8000/change-requests"
```

监控概览现在也会显示：

- `变更单总数`
- `待处理变更单`
- `强制门禁目标`

如果你准备逐步把高风险配置更新强制收进变更单，可以使用：

```bash
CHANGE_GATE_ENFORCED_TARGET_TYPES=risk_policy,tool_registry,model_route,model_provider
```

含义是：

- 默认不启用强制门禁，旧脚本和前端仍兼容
- 启用后，对应 target type 的直改接口会返回 `409`
- 仍然允许通过 `change-requests/{id}/apply` 落地正式变更

当前 compose 默认已经把 `model_route,model_provider,tool_registry,risk_policy` 放进了强制门禁，用来作为第一批切换目标。

这意味着：

- 这三类高风险控制面不能再直接修改
- 必须走 `change_requests` 的 `create -> approve/reject -> apply`
- 通过正式变更单 apply 的修改仍然可以正常生效

- Web 已提供基础“监控概览”面板，可查看任务状态分布、队列深度、待审批数、最近任务与最近审计事件

### Step Request 协议摘要

当前 structured runner 使用两层 request 协议，作为 Stage 2 收口期间的固定执行契约；当前冻结版本记为 `stage2-v1`：

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
  - 增加 `should_run`
  - 增加 `skip_reason`
  - 增加 `resolved_input`
  - 增加 `approval_required`
  - 增加 `approval_reason`
  - 增加 `effective_retry_count`
  - 增加 `effective_max_retries`
  - 可选 `result`

运行约束：

- Stage 2 期间默认冻结这份字段集合，不再随意增删
- README、runbook、runtime plan 必须同时描述同一份协议
- Stage 3 的 sessions / memory 只能建立在这份协议已经稳定的前提上

直接查询当前 runtime metadata：

```bash
curl -sS "http://localhost:8000/runtime-metadata"
./scripts/assistant_cli.py runtime show
```

监控概览 API：

```bash
curl -sS "http://localhost:8000/monitor/overview"
```

### 审计日志查询

新 API `GET /audit-logs` 能按 `task_id` 与 `event_type` 过滤，返回最近 50 条记录。它会展示 `actor`、`event_type` 和 `details`（例如审批 ID、来源步骤、resume note、claim lost 的 worker_id 等），是排查审批/恢复链路的第一手凭证。

```
curl -sS "http://localhost:8000/audit-logs?task_id=502"
curl -sS "http://localhost:8000/audit-logs?event_type=task.resume"
```

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

### Stage 2 验收清单

进入 Stage 3 之前，至少确认下面几项同时成立：

1. `StepExecutionRequest` / `EnrichedStepExecutionRequest` 的字段集合已稳定，README、runbook、runtime plan 对它的描述一致。
2. structured 主链保持 adapter / orchestrator 壳模型，legacy 路径只作为最薄兼容层，不再继续扩展。
3. `approval_retry_check.sh` 与 `claim_lease_check.sh` 保持通过，且它们描述的运行模型与当前代码和文档一致。
4. 风控、审批、interrupt / resume、checkpoint、claim / 续租 / stale requeue 这些 Stage 2 核心能力的操作路径已稳定，不再处于大改状态。

## 8. 运维辅助脚本

新增脚本：

- [`scripts/backup.sh`](/opt/ai-assistant/scripts/backup.sh)
- [`scripts/healthcheck.sh`](/opt/ai-assistant/scripts/healthcheck.sh)
- [`scripts/governance_check.sh`](/opt/ai-assistant/scripts/governance_check.sh)

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

治理专项验收：

```bash
bash scripts/governance_check.sh
```

阶段收口总检查：

```bash
bash scripts/stage_closure_check.sh
```

最近一次 Stage 3 / Stage 4 总收口结果：

- `bash scripts/stage_closure_check.sh` -> `PASS=4 FAIL=0`

如果只想单独验证 Stage 3 的调度和 daily review：

```bash
bash scripts/daily_review_check.sh
```

如果想快速确认 Web 控制台关键入口是否存在：

```bash
bash scripts/web_console_check.sh
```

如果想单独确认 Stage 5 的 schema 和只读观测入口已经接上：

```bash
bash scripts/multi_agent_schema_check.sh
```

如果想继续验证最小 manager-only bootstrap 写入链：

```bash
bash scripts/multi_agent_bootstrap_check.sh
```

如果想验证 worker specialist 执行链和 Stage 6 evaluator：

```bash
bash scripts/multi_agent_worker_execute_check.sh
bash scripts/multi_agent_source_snapshot_check.sh
bash scripts/stage6_evaluator_check.sh
bash scripts/workflow_proposal_bridge_check.sh
```

如果想确认普通任务已经自动带出 Stage 5 / Stage 6 主链 postrun，可以直接跑：

```bash
bash scripts/acceptance_check.sh
bash scripts/task_runtime_mainline_init_check.sh
bash scripts/workflow_proposal_bridge_check.sh
```

如果想一口气验证当前 Stage 5 / Stage 6 主链从 runtime fan-out/fan-in 到 postrun 已接通：

```bash
bash scripts/stage56_mainline_check.sh
```

如果想进一步确认 Stage 5 / Stage 6 的 readiness 指标、completion gap 和 `version.json` 状态已经对齐：

```bash
bash scripts/stage56_readiness_check.sh
```

如果想确认 Stage 5 / Stage 6 的最小主链 closure、readiness 与 completion gap 已一起对齐：

```bash
bash scripts/stage56_closure_check.sh
```

如果想专门验证 execution-time fan-out/fan-in：

```bash
bash scripts/task_runtime_mainline_fanout_check.sh
```

最近一次真实结果：

- `bash scripts/multi_agent_schema_check.sh` -> `PASS=9 FAIL=0 WARN=1`
- `bash scripts/multi_agent_bootstrap_check.sh` -> `PASS=40 FAIL=0 WARN=0`
- `bash scripts/multi_agent_worker_execute_check.sh` -> `PASS=13 FAIL=0`
- `bash scripts/multi_agent_source_snapshot_check.sh` -> `PASS=10 FAIL=0`
- `bash scripts/stage6_evaluator_check.sh` -> `PASS=21 FAIL=0 WARN=0`
- `bash scripts/stage6_shadow_validation_check.sh` -> `PASS=11 FAIL=0 WARN=0`
- `bash scripts/workflow_proposal_bridge_check.sh` -> `PASS=12 FAIL=0 WARN=0`
- `bash scripts/task_runtime_mainline_init_check.sh` -> `PASS=9 FAIL=0 WARN=1`
- `bash scripts/task_runtime_mainline_fanout_check.sh` -> `PASS=19 FAIL=0 WARN=0`
- `bash scripts/acceptance_check.sh` -> `PASS=313 WARN=0 FAIL=0`
- `bash scripts/stage56_mainline_check.sh` -> `PASS=7 FAIL=0`
- `bash scripts/stage56_readiness_check.sh` -> 见 [docs/stage5_stage6_readiness_checklist.md](/opt/ai-assistant/docs/stage5_stage6_readiness_checklist.md)
- `bash scripts/stage56_closure_check.sh` -> `PASS=9 FAIL=0`

## 9. MVP 验收

### 基础结构化流程验收

```bash
bash scripts/acceptance_check.sh
```

说明：

- 当前脚本默认会在测试时自动批准待审批步骤
- 可通过 `AUTO_APPROVE_APPROVALS=0` 关闭自动批准
- 依赖 `httpbin` 的外部 HTTP 用例在首次失败时会自动重试一次，用来吸收上游瞬时波动

默认使用 `http://localhost:8000`，但如果宿主 `localhost` 端口在当前环境不可达（如远端调试），脚本会自动通过 `docker compose exec -T api` 在容器内执行相同接口，不会因为外部端口暂时不可达而卡住。

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
