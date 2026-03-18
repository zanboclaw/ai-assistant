# LangGraph 决策说明

## 结论

当前仓库阶段不建议立刻把执行引擎整体重写为 LangGraph。

更合适的策略是：

1. 保留现有自研 runtime 继续承载 Stage 2
2. 在现有 Worker 上继续做“LangGraph-compatible”的边界整理
3. 等进入 Stage 3 前后，再决定是否把部分链路迁移到 LangGraph

一句话说：

当前选择是“继续沿现有 runtime 演进，并为未来的 LangGraph 化预留接口”，而不是“现在立即全量切换”。

## 当前更新

从这份决策写下到现在，仓库已经继续推进到了 Stage 3 后段和 Stage 4 前中段：

- Stage 2 的 runtime 边界抽取与协议冻结已经基本完成
- Stage 3 的 sessions / memory / review / scheduler 已经落地
- Stage 4 已经落地了权限、配额、工具注册中心、多模型路由、正式变更管理与强制门禁

这意味着这份决策目前仍然成立，而且比当时更合理：

- 自研 runtime 已经足够稳定，继续强行切 LangGraph 的性价比依旧不高
- 当前更值得投入的是治理层、provider 路由和工具服务化
- 是否 LangGraph 化，仍然更适合放到未来真正需要更复杂 graph persistence / multi-agent orchestration 时再评估

## 为什么现在不建议立刻切

当前仓库已经具备这些关键能力：

- 任务表 / 步骤表 / 审批表 / 风险策略表 / 审计表
- checkpoint 持久化
- interrupt / resume
- Redis 队列
- claim / 锁续租 / stale requeue
- 风控与审批
- 重试

也就是说，LangGraph 最核心想解决的 durable execution / interrupt / checkpoint / human-in-the-loop，这套系统已经有了一个可工作的实现。

如果现在立刻切 LangGraph，代价主要在这里：

- 需要把 `process_task()` 的主执行循环整体改写成 graph/state 模型
- 当前 `task_steps` / `approvals` / `checkpoint` 的写入语义都要重新对齐
- 现有 Redis claim / stale requeue / 审批恢复逻辑要重新嵌入 LangGraph 生命周期
- 测试和验收脚本需要大范围重做

这不是“不可以做”，而是“现在做的性价比不高”。

## 为什么也不能永远不做

虽然当前 runtime 能跑，但它也有明显边界：

- `process_task()` 已经承担了太多责任：规划、执行、审批、重试、中断、checkpoint
- 任务状态机主要靠代码分支维持，后续复杂度继续增长会变得更难维护
- 想引入 session 级上下文、长期记忆、review loop、多 agent 编排时，LangGraph 的状态图模型会更自然
- 想要更正式的 durable execution / thread persistence / graph visualization，LangGraph 生态更成熟

所以结论不是“永远不做 LangGraph”，而是“不要在 Stage 2 中途为了框架而框架化”。

## 当前推荐路线

### 阶段 2 期间

继续保留当前 runtime 作为主执行引擎。

重点做这些收口工作：

- 把监控面板补齐
- 把验收脚本继续补完整
- 把 Worker 里的状态流转进一步模块化
- 稳定当前 approval / retry / resume / interrupt / claim 语义

### 阶段 2 末到阶段 3 初

开始做 LangGraph-compatible 的边界整理，而不是直接替换。

优先抽离这些接口：

- planner 接口
- step executor 接口
- checkpoint serializer
- approval gate
- retry policy evaluator
- task state reducer

只要这些边界先抽出来，后续迁移到 LangGraph 时，才不会是“拆整个 worker”。

### 阶段 3 之后 / Stage 4 期间

再评估是否把以下链路迁移到 LangGraph：

- 结构化步骤执行主链路
- session / memory 协调链路
- reviewer / self-improvement / 定时复盘链路
- 更复杂的多 provider / 多 agent 协作链路

## 迁移触发条件

出现以下任意 2 到 3 个现象时，就值得正式启动 LangGraph 迁移：

- `process_task()` 继续膨胀，已难以维护
- 需要更复杂的多分支图执行，而不是单纯顺序步骤
- 需要 session 级 graph persistence
- 需要更正式的 graph debug / state inspect 能力
- 需要把 agent 编排从“工具执行器”升级成“有状态协作者”

## 当前代码层面的判断依据

当前 Worker 的主复杂度集中在 [worker.py](/opt/ai-assistant/apps/worker/worker.py)：

- `plan_task()`：规划
- `execute_tool()`：工具调度
- `process_task()`：主状态循环
- `write_checkpoint()`：checkpoint 写入
- Redis claim / stale requeue：执行期协调

这说明系统已经天然形成了“planner / executor / checkpoint / approval / retry / claim”几个边界。  
这正是适合先做模块化、再决定是否 LangGraph 化的信号。

## 正式决策

当前正式决策为：

- Stage 2 不做全量 LangGraph 重写
- Stage 2 继续使用现有 runtime
- Stage 3 前完成 LangGraph-compatible 的边界整理
- Stage 3 再决定是否迁移主执行链路到 LangGraph

## 当前下一步动作

围绕这个决策，推荐的后续实现顺序：

1. 继续保持现有 runtime 稳定
2. 把 provider 路由、工具治理和变更门禁继续做深
3. 评估多 provider / MCP 工具服务化
4. 只有在现有 runtime 明显阻碍更复杂协作链路时，再启动 LangGraph 迁移评估
