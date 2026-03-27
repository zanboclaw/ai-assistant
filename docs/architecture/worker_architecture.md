# Worker Architecture

Worker 已建立显式运行阶段目录：

- `runtime/task_loading`
- `runtime/planning`
- `runtime/execution`
- `runtime/tools`
- `runtime/recovery`
- `runtime/delivery`
- `runtime/agents`
- `runtime/workflow`

当前仍保留 `worker_runtime_context.py` 作为兼容上下文，但新代码入口应优先落到分阶段目录。

## 当前已落地的主链

- `apps/worker/task_processing_runtime.py`
  - 已接入 `runtime/task_loading/load_task.py`
  - 已接入 `runtime/planning/build_intent_plan.py`
  - 已接入 `runtime/planning/build_execution_plan.py`
  - `process_task` 不再只靠内联 payload 提取，而是开始通过显式阶段对象组织运行上下文。
- `apps/worker/runtime/execution/step_state_machine.py`
  - 已定义步骤状态迁移规则与显式校验函数。
- `apps/worker/runtime/execution/task_state_machine.py`
  - 已定义任务状态迁移规则与显式校验函数。
- `apps/worker/runtime/recovery/clarify_handler.py`
  - `clarification_required` 失败收口已从旧上下文拆到新 recovery 模块。
- `apps/worker/runtime/recovery/recovery_actions.py`
  - auto recovery 的 trim / reset 已迁到 recovery 模块。
- `apps/worker/runtime/delivery/validate_deliverable.py`
  - 交付物校验上下文加载与 validate 编排已迁到 delivery 模块。
- `apps/worker/infrastructure/db/runtime_repo_pg.py`
  - `task_steps / audit_logs / task_runs delivery fields` 的一组运行时查询与更新已开始沉淀到仓储层。
- `apps/worker/infrastructure/db/runtime_schema.py`
  - Worker 侧 runtime schema 已改成 contract validator；保留 bootstrap 只做默认治理 seed，不再在 Worker 启动时执行补表补列 DDL。

## 当前仍保留的兼容边界

- `apps/worker/worker_runtime_context.py`
  - 仍是兼容入口与大量历史逻辑承载点，但已开始把 `process_task` 主链透传到新的阶段模块。
- `task_execution_runtime.py`、`task_lifecycle_runtime.py`
  - 执行与收口能力仍主要在旧运行时模块，后续需要继续按 execution / recovery / delivery 分段迁出。
