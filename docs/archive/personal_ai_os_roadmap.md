# Personal AI OS Roadmap

这份文档描述当前仓库从“可运行的个人 AI 助理平台”继续推进到“更像个人 AI 助理操作系统”的后续路线。

如果想看最近一轮更贴近工程落地的优化进展、当前技术债与后续拆分计划，请结合：

- [docs/engineering_optimization_plan.md](/opt/ai-assistant/docs/engineering_optimization_plan.md)

这里的目标不是把所有能力一次性堆满，而是逐步形成下面这条闭环：

- 系统能自主拆任务、分派多个 agent
- 能沉淀可复用记忆，而不只是保存上下文
- 能评估自己这次工作是否达标
- 能提出 workflow / prompt / 配置改进建议
- 能在受控边界内自动修改自己的配置甚至代码
- 能在验收失败时安全回滚

按当前仓库状态来看，距离这个目标大致还有一段中长距离。更合适的判断是：

- Stage 1 和 Stage 2 已完成
- Stage 3 已完成收口
- Stage 4 已完成收口
- 真正通往 “Personal AI OS” 的核心工作主要落在 Stage 5 / 6 / 7

## 当前基线

当前仓库已经具备的底座：

- task -> plan -> step execution -> approvals -> resume 的主执行链
- checkpoint / interrupt / resume / stale requeue
- session / session memories / session state / reviews / daily scheduler
- actor / quota / tool registry / model provider / model route / change request / audit log
- Web + CLI 双控制面

而且从工程实现角度看，这个底座已经不再只是“单文件大实现”：

- `monitor`
- `change_request`
- `workflow_proposal`
- `shadow_validation`

这几条高频主链都已经开始从 `apps/api/main.py` 下沉到 business/store/helper 模块，当前更准确的状态是“可运行平台 + 持续模块化”，而不是“还停留在原型堆叠期”。

这意味着系统已经具备“可运行 runtime + 基础治理”的形态，但还没有形成真正的多 agent、自评估、自改进、自回滚闭环。

## 核心缺口

### 1. 多 agent 编排已进入最小主链 init/runtime/postrun，但还没成为完整主执行 fan-out / fan-in 链路

当前运行模型虽然已经会在任务进入执行阶段时初始化 Stage 5 骨架、在执行期跑一轮最小 readonly specialists fan-out/fan-in，并在终态补写 Stage 5 / Stage 6 记录，但仍然以单任务执行器为主，缺少稳定的：

- manager / specialist / reviewer / operator 角色模型
- 子任务拆分协议
- agent 间工件交换格式
- 并行任务汇总和冲突消解
- 成本 / 延迟 / 成功率驱动的 agent 调度策略

### 2. memory 更像“保存”，还不像“变强”

当前 session memory 已经能沉淀信息，但还缺：

- 长短期记忆分层
- 记忆去噪与淘汰
- 记忆质量评估
- 从记忆提炼 skill / template / rule
- 验证“这条记忆是否真的改善后续任务”

### 3. review 已有雏形，但 evaluator 闭环还没建立

当前 review 更像规则聚合摘要，还不等于系统级质量评估器。还缺：

- 任务成功标准
- 自动评分器
- 失败归因
- retry / escalate / stop 决策策略
- 复盘结果反哺执行器与 workflow 的闭环

### 4. 受控的自我改进实验系统已经有 groundwork，但还没形成完整平台

当前已经有的 groundwork 包括：

- `workflow_proposal -> change_request` bridge
- proposal / change request scoped shadow validation
- candidate overlay + `payload_hash` 精确门禁
- patch artifact / rollback artifact
- `sandbox_file` source-copy / source-patch file-level 实验通道

但如果要让系统自动改 workflow / prompt / tool policy / model route，至少还需要：

- 配置和 workflow 版本化
- 提案、审批、应用、验证、回退闭环
- shadow run / canary / A/B 验证
- 改动收益与风险的观测指标

### 5. 安全回滚已经有最小闭环，但还不够“系统级”

当前已有：

- change request
- 审计
- checkpoint
- rollback draft / rollback change request
- apply 后 acceptance / auto rollback 最小闭环

但离真正系统级安全回滚还差：

- 配置级一键回滚
- workflow / prompt 版本回滚
- 代码 patch 和 reverse patch
- 数据副作用隔离
- 回滚后的自动再验证

## Stage 5：多 Agent 协作层

目标：把系统从“单执行器平台”升级成“有角色分工的协作系统”。

当前状态：已启动，处于 `task_runtime_postrun_v1` 阶段。

当前 readiness / completion gap 口径见：

- [docs/validation/stage5_stage6_readiness_checklist.md](/opt/ai-assistant/docs/validation/stage5_stage6_readiness_checklist.md)

当前已落地：

- `multi_agent_protocol_v1`
- `agent_runs / agent_messages / agent_artifacts`
- 普通任务在执行启动时初始化 `task_runtime_postrun_v1` agent skeleton
- 普通任务在执行期即可 fan-out 多个 runtime specialists，并通过 `bash scripts/task_runtime_mainline_fanout_check.sh` 验证 manager 已在运行尾声完成 fan-in rollup，而终态 postrun 继续收束 evaluator/workflow proposal
- `bash scripts/stage56_mainline_check.sh` 已跑通到 `PASS=7 FAIL=0`
- `bash scripts/stage56_closure_check.sh` 已对齐到 `PASS=9 FAIL=0`
- `bootstrap-demo`
- `finalize-demo`
- reviewer `approved / rework_required / rejected`
- `quality_score / quality_criteria / step_stats`
- Web / CLI / audit / smoke check 可见性
- `GET /tasks/{id}` 与 task agent summary 已暴露主链 Stage 5 状态
- `monitor/overview.readiness_metrics.stage5` 当前稳定返回：
  - `operational=true`
  - `completed=true`
  - `completion_ratio=1.0`
  - `missing_completion_gates=[]`

### 结果定义

- 系统能够把任务拆成多个 agent 子任务
- agent 之间通过统一工件协议交换上下文
- 有 manager 负责规划、委派、汇总、重试和升级审批
- 有 reviewer 负责独立检查结果质量
- 所有 agent 活动都进入审计和成本统计

### 推荐范围

- 引入最小 agent role taxonomy：
  - `manager`
  - `specialist`
  - `reviewer`
  - `operator`
- 新增 `agent_runs` / `agent_messages` / `agent_artifacts` 一类持久化对象
- 定义 agent artifact 协议：
  - brief
  - plan
  - draft
  - review
  - final
- 支持最小 fan-out / fan-in
- 支持子 agent 失败后的聚合决策：
  - 重试
  - 更换角色
  - 降级单 agent
  - 提交人工审批

### 验收标准

- 至少 1 条真实任务可自动拆成 2-3 个 agent 并行执行
- manager 能汇总多个 agent 的结果并生成最终输出
- reviewer 能独立给出通过 / 拒绝 / 需返工判断
- 关键事件可从 Web / CLI / audit log 里追踪

当前和更强的 Stage 5 形态之间仍有增强空间：

- 当前主链已经能在执行期跑一轮最小 readonly fan-out / fan-in，但还不是完整的执行期 orchestration
- specialist 已经能跑最小 `worker_readonly_v1` 只读子任务，但还没有扩到更真实的受限工具级子任务
- manager 还没有多轮自动重试与真实 fan-in 汇总
- reviewer 已经产出 `quality_score / quality_criteria / step_stats`，并会落一条独立 `evaluator_run`，但还没有独立执行期 reviewer pipeline
- 当前 readiness gate 已满足，后续增强不再阻塞 Stage 5 completed

### 现在就可以开始的工作项

- 先冻结最小 multi-agent protocol v1
- 在当前 runtime 之上增加 manager-only orchestration，不急着重写主执行器
- 先把“任务拆解 + 汇总评审”跑通，再扩展更复杂的 agent 网络

配套协议草案见：

- [docs/multi_agent_protocol_v1.md](/opt/ai-assistant/docs/multi_agent_protocol_v1.md)

## Stage 6：评估与自我改进层

目标：让系统开始知道“什么算做得好”，并能在受控边界里持续改进自己的 workflow。

当前 readiness / completion gap 口径见：

- [docs/validation/stage5_stage6_readiness_checklist.md](/opt/ai-assistant/docs/validation/stage5_stage6_readiness_checklist.md)

### 结果定义

- 每类任务有最小成功标准
- 系统能自动给结果打分并归因失败原因
- review 结果能反哺：
  - prompt
  - tool choice
  - model route
  - workflow 模板
- 改进以 change request / proposal 形式进入治理流程

### 推荐范围

- 引入 evaluator pipeline：
  - rule-based evaluator
  - model-based evaluator
  - human override
- 引入 failure taxonomy：
  - planning failure
  - tool misuse
  - incomplete answer

### 当前已落地的最小入口

- `evaluator_runs` 独立持久化对象已经存在
- 普通任务会在已有 Stage 5 skeleton 基础上，于终态自动写入一条 `task_runtime_postrun_v1` evaluator 记录
- `finalize-demo` 仍会在 demo/smoke 路径写入一条 `stage6_quality_gate` evaluator 记录
- `GET /tasks/{task_id}/evaluator-runs/latest`、`GET /evaluator-runs`、`GET /tasks/{task_id}/workflow-proposals/latest` 已可用
- `GET /workflow-proposals`、`GET /tasks/{task_id}/workflow-proposals` 已可用
- monitor 页已经有 `evaluator_metrics / recent_evaluator_runs`
- `workflow_proposal` 已作为 evaluator 的最小提案对象落地，并会进入 task summary / audit / evaluator 接口
- workflow proposal 已具备最小 triage 能力：可列表、可按 `task_id / priority / action_key` 过滤、可进入 monitor 聚合
- workflow proposal 已具备最小治理桥接能力：可预览 change request draft，并可手动创建 pending change request
- Stage 5 worker specialist 已扩到三类只读子任务：
  - `readonly_step_digest`
  - `readonly_source_snapshot`
  - `readonly_task_snapshot`
- `bash scripts/stage6_evaluator_check.sh` 已覆盖 demo smoke 与主链 postrun 失败路径
- `bash scripts/workflow_proposal_bridge_check.sh` 已对齐主链 proposal -> preview/create/apply，并继续扩展到 workflow_improvement shadow validation gate 验收
- `bash scripts/multi_agent_source_snapshot_check.sh`、`bash scripts/multi_agent_worker_execute_check.sh` 已覆盖 worker 子任务专项
- 支持 shadow evaluation：
  - 不直接替换主链
  - 先用旁路任务验证改进收益
- readiness 口径里当前 Stage 6 completion gates 已全部满足
- `monitor/overview.readiness_metrics.stage6` 当前稳定返回：
  - `operational=true`
  - `completed=true`
  - `completion_ratio=1.0`
  - `missing_completion_gates=[]`

### 验收标准

- 至少 2 类任务具备结构化 success criteria
- 系统能自动产出改进提案，并能通过 change request 流程进入审批
- 至少 1 类 workflow 改动能经过 shadow run 验证收益
- review / evaluator 指标能进入监控页

### 边界控制

Stage 6 优先允许系统自动改这些内容：

- prompt 模板
- workflow 配置
- tool 选择策略
- model route

Stage 6 默认不直接自动改业务代码主逻辑，除非后续进入 Stage 7 的受控实验通道。

## Stage 7：受控自修改与安全回滚层

目标：允许系统在严格治理边界里修改自己的实现，并在失败时自动回退。

### 当前进展（groundwork）

- `change_requests` 已扩展 `proposal_kind`，并支持 `manual_change / workflow_improvement / rollback`
- 已支持在 change request 创建/应用链路写入 patch artifact（`baseline_payload / payload_patch / patch_summary`）并捕获 rollback artifact
- 已支持 task-scoped `runtime_overrides`，让 proposal shadow validation 可以把 candidate overlay 注入 `model_route/planner`，并已接入 `summarize_text / web_search_summary` 的真实主链执行路径
- 已支持把 `workflow_improvement` change request 绑定到 candidate-aware shadow validation gate，只有 `target_type + target_key + payload_hash` 匹配的 validation 才允许 `apply`
- 已支持 change request-scoped shadow validation/status 接口：
  - `GET /change-requests/{id}/shadow-validation`
  - `POST /change-requests/{id}/shadow-validate`
- 已支持 rollback 草稿与回滚单接口：
  - `GET /change-requests/{id}/rollback-draft`
  - `POST /change-requests/{id}/rollback`
- 已新增 `bash scripts/change_request_rollback_check.sh`，覆盖 patch+rollback artifact 字段校验与 apply -> rollback draft/create -> rollback approve/apply -> 状态恢复闭环
- 已新增 `bash scripts/stage7_shadow_validation_status_check.sh`，覆盖 requested/completed 状态演进、latest shadow task 对齐，以及 proposal -> change request shadow gate 同步
- 已新增 `bash scripts/stage7_model_route_override_check.sh`，覆盖 `summarize_text` route override 在真实主链步骤中的注入与输出落盘
- 已新增 `bash scripts/stage7_web_search_route_override_check.sh`，覆盖 `web_search_summary` route override 在真实 `web_search` 主链步骤中的注入与输出落盘
- 已新增 `sandbox_file` change target，允许在 [apps/api/stage7_sandbox](/opt/ai-assistant/apps/api/stage7_sandbox) 下做受控 file-level source-copy / source-patch / apply / rollback 实验；`payload` 既支持直接写 `content`，也支持通过 `source_path` 从仓库源码复制 sandbox 副本，或通过 `source_path + patch` 按 unified diff 生成 sandbox 目标内容，并补充 `bash scripts/stage7_sandbox_file_change_check.sh` 与 `bash scripts/stage7_sandbox_file_patch_check.sh` 专项验收
- 容器模式下，API 会通过只读 `WORKSPACE_ROOT=/workspace_repo` 挂载仓库源码，供 `sandbox_file` source-copy / source-patch 读取真实源码文件
- 已新增 `bash scripts/stage7_sandbox_file_bridge_check.sh`，覆盖 workflow proposal -> `sandbox_file` target 的显式 source-patch bridge、apply 与 rollback
- 已新增 `bash scripts/stage7_mainline_check.sh`、`bash scripts/stage7_readiness_check.sh`、`bash scripts/stage7_closure_check.sh`，把 Stage 7 groundwork 的主链/readiness/closure 口径固定成脚本化验收
- `monitor/overview.readiness_metrics.stage7` 已开始暴露 Stage 7 groundwork 进度，并额外补充 `sandbox_file_applied_count`、`sandbox_source_copy_applied_count` 与 `sandbox_source_patch_applied_count` 追踪 file-level 实验通道

边界说明：

- 当前 Stage 7 groundwork 已完成收口，但不代表 Stage 7 全阶段完成
- 当前已多出 `sandbox_file` 这条 file-level 实验通道，并且能通过 `source_path` 复制现有源码到 sandbox 副本、再从 workflow proposal 显式桥接进入；但它仍局限在 sandbox 路径，不等于 branch/code patch 自动化已经完成

### 结果定义

- 系统能生成代码或配置 patch
- 改动进入 sandbox / branch / proposal 通道
- 系统能自动执行验收脚本
- 验收失败会自动回滚并记录失败归因
- 回滚后系统状态仍可追踪、可重放、可审计

### 推荐范围

- 引入 patch proposal / rollback proposal
- 引入实验沙箱：
  - 临时 workspace
  - 临时分支
  - 临时配置版本
- 对不同 target 分级治理：
  - `prompt/workflow/config`
  - `tool registry / model route`
  - `worker/api code`
- 自动执行专项验收：
  - acceptance
  - governance
  - session memory
  - approval retry
  - claim lease
  - daily review
- 为每次自改动保存：
  - patch
  - reverse patch
  - test result
  - metric delta
  - rollback reason

### 验收标准

- 至少 1 类非关键配置变更支持自动提案、自动验证、自动回滚
- 至少 1 类代码 patch 支持受控实验和自动回退
- Web / CLI 能查看 proposal、实验状态、验收结果、回滚记录
- 任意失败实验都不会污染主配置或主运行链

## 推荐推进顺序

建议严格按下面顺序推进，而不是直接跳到“自动改代码”：

1. 先完成 Stage 5 的 agent 协议和角色体系
2. 再完成 Stage 6 的 evaluator 与 workflow proposal 闭环
3. 最后进入 Stage 7 的受控自修改与安全回滚

原因很直接：

- 没有 agent 协议，就没有稳定的多 agent 自主分派
- 没有 evaluator，就不知道系统是在变好还是变坏
- 没有 proposal + rollback，就不应该给系统自改代码权限

## 对当前仓库的直接建议

如果只看最近 2-4 个迭代，最值的不是做一个“大而全”的新子系统，而是优先落这 6 件事：

1. 新增 `multi_agent_protocol_v1.md`
2. 为 task/session/review 补 success criteria 与 failure taxonomy
3. 新增 evaluator 结果表和最小 UI 展示
4. 给 change request 增加 `proposal_kind=workflow_improvement`
5. 补 workflow version / prompt version 的最小版本化
6. 为自动改动准备 patch + rollback artifact 模型

进展更新（2026-03-21）：

- 第 4、6 项已进入主链 groundwork，并完成当前收口：`proposal_kind`、task-scoped `runtime_overrides`、candidate overlay + `payload_hash` 精确 shadow gate、patch+rollback artifact/change request 闭环，以及 Stage 7 的 mainline/readiness/closure 验收已落地
- `sandbox_file` 已从 demo 文本写入推进到 source-copy / source-patch / apply / rollback 主链实验，并已补齐 workflow proposal -> `sandbox_file` source-patch bridge，以及 `sandbox_source_copy_applied_count / sandbox_source_patch_applied_count` 指标
- 最近一轮 Stage 7 专项结果已对齐到：`stage7_sandbox_file_change_check=PASS17`、`stage7_sandbox_file_patch_check=PASS21`、`stage7_sandbox_file_bridge_check=PASS25`、`stage7_mainline_check=PASS10`、`stage7_readiness_check=PASS11`、`stage7_closure_check=PASS10`
- 仍需继续推进 patch proposal 的实验沙箱与代码层自动回滚能力

## 进入下一阶段前的门槛

### 进入 Stage 5 前

- Stage 4 的治理入口稳定
- change request / audit / quota / model route 语义基本冻结
- 当前 Web / CLI 控制面能稳定观测任务、session、governance

### 进入 Stage 6 前

- Stage 5 的多 agent 协议和持久化对象稳定
- 至少 1 条 Stage 5 主链 postrun 已经跑通
- reviewer 不再只是“附加说明”，而是独立评估角色

### 进入 Stage 7 前

- Stage 6 的 evaluator 能稳定判断通过 / 返工 / 拒绝
- workflow proposal 已具备验证闭环
- 自动回滚先在配置层通过，再逐步放开到代码层
