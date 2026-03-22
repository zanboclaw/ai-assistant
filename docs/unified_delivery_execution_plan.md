# 统一落地方案与开发优先级计划

## 1. 文档目标

这份文档用于把当前仓库的后续推进方向统一成一条可执行主线，回答四件事：

- 当前项目下一步到底先做什么
- 为什么这样排优先级
- 哪些风险必须先处理
- 后续推进应如何分阶段验收

这份文档不重复描述所有历史阶段实现细节，而是在现有代码与现有文档基础上，给出统一落地方案。

---

## 2. 当前统一判断

基于当前代码实现与现有文档，可先统一下面三条判断：

### 2.1 基线平台已经成型

当前仓库已经具备以下可运行底座：

- 任务执行主链：`apps/api/main.py`、`apps/worker/worker.py`
- 审批 / 重试 / checkpoint / interrupt / resume
- sessions / memories / reviews / daily review
- actor / quota / risk / tool / model / change request / audit
- trace / replay / minimal skill registry / MCP tool registry
- Stage 5 / 6 / 7 当前仓库定义下的 completed 主链

更准确地说，当前项目已经是一个“可执行、可治理、可恢复、可观测”的平台，而不再是简单原型。

### 2.2 当前主短板不在执行底座，而在交付闭环

当前系统最明显的问题不是“不会跑任务”，而是：

- 对模糊输入的理解不稳定
- 缺少明确的最终交付物定义
- planner 仍可能停在 research / summarize
- worker 跑完不等于用户得到了真正可用的成品

因此，下一步不应继续把重点放在“再补一点执行能力”，而应优先补齐“交付闭环”。

### 2.3 对话体验是重要能力，但不是当前第一优先级

系统当前仍偏“任务系统感”，不够像助理：

- 所有输入容易直接进入任务链
- 模糊需求缺少草稿态确认
- 简单问答缺少 fast path
- conversation memory 与 task memory 未清晰分层

但这些问题的优先级低于“能否稳定交付正确结果”。

---

## 3. 统一落地方案

后续路线统一为三层：

### 3.1 第一主线：先把系统从“执行平台”升级为“交付平台”

这条主线是后续最高优先级。

核心目标：

- 让系统先知道用户要的是什么成品
- 让 planner 围绕交付物而不是围绕工具来规划
- 让 completed 由结果校验驱动，而不是由 worker 是否跑完驱动

建议落地对象：

- `TaskIntent`
- `DeliverableSpec`
- deliverable-first planner
- `ValidationReport`
- `RecoveryAction`

建议直接复用现有底座，而不是重写主链：

- task / step / approval / trace / session / evaluator / workflow proposal 继续保留
- 在现有主链前后增加“理解层、交付层、校验层、恢复层”

### 3.2 第二主线：再把系统从“任务面板感”升级为“会话感”

在交付闭环有最小版本后，再推进对话层。

核心目标：

- 区分聊天、澄清、正式执行
- 支持草稿态确认，而不是默认立刻创建正式任务
- 简单请求走 fast path，复杂请求再升级为任务
- conversation memory 与 task memory 分层

### 3.3 第三主线：最后补平台级增强

这条主线用于把平台从“可交付”继续推向“可持续成长”：

- retrieval memory
- long-term memory
- finer-grained authz
- pattern memory
- evaluator 反哺优化

这部分应建立在前两条主线已经稳定的基础上推进。

---

## 4. 开发优先级

## P0：统一口径与边界

先统一项目表达，避免后续继续在不同文档中出现方向分裂。

本阶段要做的事：

- 统一 Stage 7 状态口径
- 统一“当前完成了什么”和“最终目标是什么”的边界
- 统一“下一步主线”表述
- 明确哪些文档是现状口径、哪些是未来规划、哪些是历史方案

完成效果：

- 团队对当前状态有一致理解
- 评审、汇报、开发不再各说一套

## P1：TaskIntent / DeliverableSpec

这是当前最应该最先做的产品能力。

目标：

- 让系统先理解任务类型
- 让系统明确“最终要交付什么”

建议落地点：

- `task_runs` 扩展字段：
  - `task_intent_json`
  - `deliverable_spec_json`
- Web / CLI / API 任务详情可见
- 先覆盖高频任务类型：
  - 问答
  - 调研
  - 内容生成
  - 改写
  - 执行类任务

## P2：Deliverable-first Planner

目标：

- planner 显式消费 `DeliverableSpec`
- 计划模板从“tool-first”切到“deliverable-first”

最低要求：

- 计划中必须显式出现 `generate`
- 计划中必须显式出现 `validate`
- research 类任务不能停在 `web_search / summarize`

## P3：Validation / Recovery

目标：

- 让系统不再把中间结果误当最终交付

最小能力：

- 规则校验：
  - 数量
  - 字段
  - 格式
- 语义校验：
  - 是否是成品
  - 是否可直接使用
  - 是否满足用户目标
- 恢复动作：
  - `retry`
  - `replan`
  - `clarify`
  - `fail`

## P4：对话层增强

目标：

- 提升系统的“助理感”

范围：

- 输入分流器
- 草稿态对话层
- fast path
- conversation memory / task memory 分离
- 对话式审批前确认

## P5：长期平台增强

目标：

- 让系统从“可交付”走向“可复用、可成长”

范围：

- retrieval memory
- pattern memory
- 更细粒度权限控制
- evaluator 持续反哺
- 更稳定的经验复用闭环

---

## 5. 风险与阻塞项

## 5.1 最大产品风险：执行完成不等于交付完成

当前如果不优先做交付闭环，系统会继续出现下面的问题：

- 搜索摘要被当成最终答案
- 调研结果被当成成品交付
- planner 跑完但用户目标没有真正达成

对应策略：

- 优先建设 `DeliverableSpec + ValidationReport`

## 5.2 最大工程风险：文档与代码口径持续漂移

当前文档里已经存在下面这些风险：

- 阶段状态表达不完全一致
- “下一步做 P0/P1/P2” 和 “下一步做通用任务架构” 两种口径并存
- 某些旧文档仍在以历史阶段视角描述当前能力

对应策略：

- 先完成口径统一，再进入下一轮开发
- 后续把“现状文档”和“未来规划文档”分层维护

## 5.3 最大架构风险：在现有 runtime 上继续横向堆能力

如果不补统一抽象层，而继续直接往 worker / planner 塞逻辑，会导致：

- 主流程继续膨胀
- 特判越来越多
- 新任务类型只能继续靠补丁处理

对应策略：

- 先增加统一对象，再消费这些对象
- 避免为单任务类型硬编码逻辑

## 5.4 最大体验风险：用户感知仍然像“任务系统”

如果只继续强化执行平台，而不补对话层，会持续出现：

- 简单问题也走重链路
- 用户只是问问，却触发执行
- 改口与任务状态互相污染

对应策略：

- 在交付闭环 MVP 稳定后，再进入对话层增强

---

## 6. 分阶段实施计划

## 阶段 A：统一口径

目标：

- 形成唯一主路线

工作项：

- 收敛现状口径
- 标记历史文档
- 统一下一步主线表达

完成标准：

- 评审时可明确回答“当前完成到哪、下一步做什么、为什么”

## 阶段 B：交付闭环 MVP

目标：

- 先形成最小可运行交付闭环

工作项：

- `TaskIntent`
- `DeliverableSpec`
- deliverable-first plan template
- `generate + validate`
- 一轮最小 recovery

完成标准：

- 对模糊内容生成类任务，不再只返回 research 摘要
- 任务详情中可区分中间产物和最终交付物

## 阶段 C：交付闭环增强

目标：

- 提升稳定性和覆盖面

工作项：

- richer validator
- 更清晰的 artifact 分层
- 更稳定的 replan / retry / clarify 路径

完成标准：

- 高价值任务类型的一次通过率提升
- 中间结果误交率下降

## 阶段 D：对话层增强

目标：

- 提升交互自然度

工作项：

- 输入分流器
- 草稿态
- fast path
- 记忆分层

完成标准：

- 简单问题不再默认进入正式任务链
- 模糊需求会先被澄清

## 阶段 E：平台增强

目标：

- 让系统开始复用经验并持续变强

工作项：

- retrieval memory
- pattern memory
- authz 强化
- 长期优化闭环

完成标准：

- 相似任务可稳定复用历史经验
- skill / memory / tool 进入更清晰治理边界

---

## 7. 推荐执行顺序

建议后续按下面顺序推进：

1. 统一口径与路线
2. `TaskIntent / DeliverableSpec`
3. deliverable-first planner
4. validator / recovery
5. 对话层增强
6. retrieval / authz / pattern memory

这条顺序背后的原则是：

- 先修正确性
- 再修体验
- 最后做平台成长性

---

## 8. 评审口径

后续对内或对外评审时，建议统一使用下面这套表述：

- 当前项目基础平台已成型
- 当前执行与治理底座已经较完整
- 当前主短板不是“不会执行”，而是“交付闭环未形成”
- 下一步主线不是继续补 Stage，而是先把系统升级成“可稳定交付成品的平台”
- 在交付闭环稳定后，再补对话层和长期成长能力

---

## 9. 一句话结论

当前项目已经有了“执行平台”的底座；  
下一步最重要的不是继续堆执行能力，而是先补齐“交付闭环”；  
完成这一步之后，再把系统升级为“更像助理、还能持续成长的平台”。
