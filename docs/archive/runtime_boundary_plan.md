# Runtime Boundary Plan

## 当前状态

这份文档主要记录 Stage 2 期间为自研 runtime 做的边界抽取与协议冻结工作。

当前这些工作已经基本完成，并已经支撑 Stage 3 与 Stage 4 的继续推进。也就是说：

- 这里列出的边界大多已经从“计划”变成“已落地”
- 这份文档现在更适合作为 runtime 结构说明和历史收口记录
- 后续如果继续演进，重点会更多落在治理层、provider 路由层和工具服务化，而不是回到 Stage 2 的大规模执行器收口

## 已抽出的边界

1. `interrupt_task_if_requested`：中断请求统一在步骤边界检查，checkpoint/状态写在一个地方。
2. `resolve_structured_step_input`：工具输入解析、normalize、JSON 化统一处理。
3. `enforce_step_approval`：审批 gate 由这段逻辑承载，保持审计 + WAITING 状态一致。
4. `execute_step_with_retries`：retry / tool 执行 / claim ownership 统一收敛，方便后续替换执行器。
5. `record_skipped_step`：skip 分支的落库、context 更新、checkpoint 写入已经独立。
6. `finalize_structured_step_success` / `finalize_structured_step_continue` / `record_structured_step_exception`：structured step 的成功、继续、异常出口已拆开。
7. `select_task_plan_source` / `prepare_executor_context` / `run_planned_execution`：任务规划来源判定、上下文初始化、structured/legacy 分发已经从 `process_task()` 主体剥离。
8. `start_task_execution` / `finalize_task_success` / `finalize_task_failure`：任务开始/结束状态写入已经成对收口。
9. `persist_structured_step_runtime_state`：`step_context`、`var_context`、`step_outputs`、checkpoint 的运行态写回已经统一，success/continue/skip/exception 四条支路共用一套 sink。
10. `persist_structured_step_outcome`：success、continue、skip、exception 均通过同一份 outcome reducer 更新 `task_steps`、重试计数与 checkpoint。
11. `persist_legacy_step_runtime_state`：legacy 路径的步骤输出现在也会把 `step_outputs` 推入 task runtime sink，保持 progress/ checkpoint 语义一致。
12. `call_planner_with_retries` / `resolve_task_plan_source`：planner 层的 inference/model/fallback 分支被拆出，`process_task()` 不再直接混合判断。
13. `StepExecutionRequest` / `EnrichedStepExecutionRequest`：structured step 的 request 字段集合已经通过 `TypedDict` 固定下来，主链使用同一份 execution contract。
14. `normalize_step_execution_request` / `enrich_step_execution_request`：structured step 已经拆成静态 request 规范化和上下文派生两层。
15. `begin_structured_step_execution` / `execute_prepared_step_request` / `route_structured_step_outcome` / `handle_structured_step_exception` / `complete_structured_step_execution`：structured runner 的开始、消费、结果路由、异常分派已经成形，`run_structured_step()` 逐步退化为 orchestration 壳子。
16. `assemble_task_success_result`：artifact 写入与最终结果拼装已经从任务完成态写回中分离，便于后续替换为 graph runner 的终态节点。

## 历史待抽边界

1. **Step request 协议冻结**：`TypedDict` 已经落地，当前冻结版本为 `stage2-v1`；接下来重点不再是“是否升级”，而是冻结字段集合与含义，避免在进入 Stage 3 前继续漂移。
2. **Stage 2 收口清单**：把 legacy 保持为最薄兼容层，不再继续扩展；同时让 README / runbook / runtime plan 对当前架构边界保持一致，形成明确的 Stage 2 收口说明，以便 Stage 3 可以从一个“稳定状态”顺利接手。
3. **Stage 3 入口条件固化**：明确只有在 structured adapter 主链、request 协议、专项验收脚本三者一致时，才正式启动 sessions / memory 主线。

## Stage 2 收口结果

1. 把 `select_task_plan_source`、`prepare_executor_context`、`run_planned_execution` 这三层边界彻底收稳，让 planner 到 executor 的链路不再混着旧逻辑。
2. 把 structured 主链继续压成稳定的 adapter/orchestrator 形态，并明确 legacy 只保留最薄兼容层，不再继续扩展；在收口期间冻结 `StepExecutionRequest` / `EnrichedStepExecutionRequest` 的 payload 字段集合与含义，以免 Stage 3 的 sessions / memory 线索依赖不确定的结构。
3. 让代码结构、README、runbook 和专项验收脚本完全对齐，确保 Stage 2 的运行模型已经固定，再进入 Stage 3 的 sessions / memory 主线。收口完成之后再正式开启 Stage 3 的 intersection work，让 Stage 3 的启动点始终从一个“稳定的 Step request + structured execution”开始，并以明确的 Stage 2 验收清单为进度锚点。

## Stage 3 触发条件

1. `StepExecutionRequest` / `EnrichedStepExecutionRequest` 的字段集合在 README、runbook 和 runtime plan 中一致，且不再处于“探索中”状态。
2. `run_structured_step()` 保持 orchestration 壳模型，structured adapter 主链稳定，legacy 继续维持最薄兼容层。
3. `approval_retry_check.sh`、`claim_lease_check.sh` 与必要的主流程验收脚本保持通过，且这些脚本描述的运行模型与文档一致。

## 现在仍不建议轻易改动的部分

* planner + tool 解析：仍然由现有 `plan_task()` 生成的 raw steps 提供，只在模块化后再考虑引入 LangGraph planner。
* Redis claim / claim heartbeat / stale requeue：这些机制已经合适，不做改动；未来再拆出核心监控接口即可。
* Worker 主循环的 fetch + enqueue 路径：保持当前结构，只在需要多模型调度时再拆成不同 runner。

## 继续演进建议

1. 继续把 Step Request 协议视为稳定契约，不要轻易扩大字段集合。
2. 若要继续演进执行器，优先在 provider route、tool service 和治理层扩展，而不是回头打散当前稳定的 structured runner。
3. 每次涉及控制面变更时，优先补专项验收与文档，再补新能力。

## 最近进展

- `persist_structured_step_runtime_state` 让 success / continue / skip 的运行态写回共用一个 sink，`run_structured_step()` 现在更像调用这些 helper。
- `finalize_task_failure()` 先执行 `rollback()` 再通过新 cursor 写 `failed` 状态与 checkpoint，避免由于事务 aborted 再写导致的 `InFailedSqlTransaction`。
- 验收脚本在 `curl` 访问宿主 `localhost:8000` 不通时会自动 fallback 到 `docker compose exec -T api` 的容器内请求，保持远程或 VPN 场景也能顺利完成循环。
- `run_structured_step()` 现在已经拆出 request normalize/enrich、prepared request 执行、结果路由、异常分派与 completion helper，主函数本身逐步退化成 orchestration 壳子。
