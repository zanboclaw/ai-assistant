# Personal AI OS Roadmap

这份文档描述当前仓库从“可运行的个人 AI 助理平台”继续推进到“更像个人 AI 助理操作系统”的后续路线。

这里的目标不是把所有能力一次性堆满，而是逐步形成下面这条闭环：

- 系统能自主拆任务、分派多个 agent
- 能沉淀可复用记忆，而不只是保存上下文
- 能评估自己这次工作是否达标
- 能提出 workflow / prompt / 配置改进建议
- 能在受控边界内自动修改自己的配置甚至代码
- 能在验收失败时安全回滚

按当前仓库状态来看，距离这个目标大致还有一段中长距离。更合适的判断是：

- Stage 1 和 Stage 2 已完成
- Stage 3 大部分完成
- Stage 4 持续推进中
- 真正通往 “Personal AI OS” 的核心工作主要落在 Stage 5 / 6 / 7

## 当前基线

当前仓库已经具备的底座：

- task -> plan -> step execution -> approvals -> resume 的主执行链
- checkpoint / interrupt / resume / stale requeue
- session / session memories / session state / reviews / daily scheduler
- actor / quota / tool registry / model provider / model route / change request / audit log
- Web + CLI 双控制面

这意味着系统已经具备“可运行 runtime + 基础治理”的形态，但还没有形成真正的多 agent、自评估、自改进、自回滚闭环。

## 核心缺口

### 1. 多 agent 编排还没有进入主链

当前运行模型仍然以单任务执行器为主，缺少稳定的：

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

### 4. 还没有受控的自我改进实验系统

要让系统自动改 workflow / prompt / tool policy / model route，至少需要：

- 配置和 workflow 版本化
- 提案、审批、应用、验证、回退闭环
- shadow run / canary / A/B 验证
- 改动收益与风险的观测指标

### 5. 安全回滚还不够“系统级”

当前已有 change request、审计和 checkpoint，但离安全回滚还差：

- 配置级一键回滚
- workflow / prompt 版本回滚
- 代码 patch 和 reverse patch
- 数据副作用隔离
- 回滚后的自动再验证

## Stage 5：多 Agent 协作层

目标：把系统从“单执行器平台”升级成“有角色分工的协作系统”。

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

### 现在就可以开始的工作项

- 先冻结最小 multi-agent protocol v1
- 在当前 runtime 之上增加 manager-only orchestration，不急着重写主执行器
- 先把“任务拆解 + 汇总评审”跑通，再扩展更复杂的 agent 网络

## Stage 6：评估与自我改进层

目标：让系统开始知道“什么算做得好”，并能在受控边界里持续改进自己的 workflow。

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
  - unsafe action
  - memory miss
  - workflow mismatch
- 引入 workflow proposal 对象：
  - proposal target
  - expected gain
  - risk level
  - evidence
  - rollback plan
- 支持 shadow evaluation：
  - 不直接替换主链
  - 先用旁路任务验证改进收益

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

## 进入下一阶段前的门槛

### 进入 Stage 5 前

- Stage 4 的治理入口稳定
- change request / audit / quota / model route 语义基本冻结
- 当前 Web / CLI 控制面能稳定观测任务、session、governance

### 进入 Stage 6 前

- Stage 5 的多 agent 协议和持久化对象稳定
- 至少 1 条多 agent 主链已经跑通
- reviewer 不再只是“附加说明”，而是独立评估角色

### 进入 Stage 7 前

- Stage 6 的 evaluator 能稳定判断通过 / 返工 / 拒绝
- workflow proposal 已具备验证闭环
- 自动回滚先在配置层通过，再逐步放开到代码层
