# 通用任务架构执行方案

## 1. 结论

`docs/New features needed/project_design_doc_universal_task_architecture.md` 提出的主方向是对的：

- 项目下一阶段不应继续只强化“执行能力”
- 而应优先补齐“交付闭环”
- 目标是把系统从“会跑任务”升级为“能稳定交付用户真正要的成品”

一句话概括：

```text
用户输入 -> 任务理解 -> 交付物定义 -> 交付导向计划 -> 执行 -> 生成 -> 校验 -> 返工/澄清 -> 最终交付
```

---

## 2. 为什么这件事是下一优先级

当前项目已经具备很强的执行底座：

- API / Web / CLI 入口
- Planner / Worker / Tool Calling
- Approval / Risk Policy / Audit
- Retry / Interrupt / Resume / Checkpoint
- Session / Review / Memory
- Evaluator / Workflow Proposal / Shadow Validation
- Stage 7 受控自修改

但面对模糊自然语言任务，仍存在稳定缺口：

- 容易把调研结果当最终答案
- 容易把中间摘要当任务完成
- 缺少统一交付抽象，导致新任务只能继续打补丁

因此，下一阶段真正该补的不是更多单点能力，而是：

- 明确用户到底要什么交付物
- 用交付物驱动计划
- 用校验结果驱动完成判定

---

## 3. 对现有项目的方向判断

### 3.1 已经做好的部分

当前底座已经足够支撑通用任务架构第一版落地：

- P0 Trace 第二刀：已支持更细粒度 trace 与只读 replay
- P0 Minimal Skill Registry 第二刀：已支持治理可视化与 task UI skill 选择
- 任务状态、审批、artifact、session、review、evaluator 已可复用

这意味着我们**不需要推翻现有架构**，而是可以在现有主链上加一层：

- `TaskIntent`
- `DeliverableSpec`
- `ExecutionPlan`（交付导向）
- `ValidationReport`
- `RecoveryAction`

### 3.2 当前真正缺的部分

优先缺口不是 Tool / MCP / Runtime，而是：

1. **任务理解层**
2. **交付物定义层**
3. **交付导向 planner**
4. **结果校验层**
5. **返工 / 澄清恢复层**

---

## 4. 推荐实施顺序

## Phase 1：任务理解与交付物定义

### 目标

新增两层稳定抽象：

- `TaskIntent`
- `DeliverableSpec`

### 落地方式

- 在 `tasks` 表新增：
  - `task_intent_json`
  - `deliverable_spec_json`
- 在创建任务时先做一次轻量解析
- Web / CLI / API 展示这两个对象

### 验收标准

- 常见模糊任务可区分：
  - `qa`
  - `research`
  - `content_generation`
  - `rewrite`
  - `execution`
  - `mixed`
- 至少能为“小红书文案 / 邮件回复 / 竞品简表 / 自我介绍”生成合理的 `DeliverableSpec`

---

## Phase 2：交付导向 Planner

### 目标

让 planner 围绕交付物规划，而不是围绕工具规划。

### 落地方式

- planner 输入显式加入 `DeliverableSpec`
- 引入 plan archetypes：
  - `direct_answer`
  - `research_then_answer`
  - `research_then_generate`
  - `tool_execution`
  - `clarify_first`
- 强制计划包含：
  - `generate`
  - `validate`

### 验收标准

- research 类任务不会停在 search/summarize
- content_generation 类任务必须进入成品生成
- 任务详情页能看见“中间产物”和“最终交付物”分层

---

## Phase 3：Validator 与 Recovery

### 目标

阻止“中间结果冒充最终交付”。

### 落地方式

- 新增规则型 `ValidationReport`
- 先做结构校验：
  - 数量
  - 字段
  - 格式
- 再补语义校验：
  - 是否是成品
  - 是否可直接使用
  - 是否满足用户目标
- 将完成判定从“worker 跑完”切换为“validation 通过”
- 接入最小恢复动作：
  - `retry`
  - `replan`
  - `clarify`
  - `fail`

### 验收标准

- 小红书文案任务不会只给搜索摘要
- 数量不足、字段不全、成品缺失时不会直接 `completed`

---

## Phase 4：模式沉淀与持续优化

### 目标

把通用能力沉淀成模式，而不是继续堆特判。

### 落地方式

- 新增 `pattern_memory`
- 记录：
  - 高成功率 `DeliverableSpec` 模板
  - 高成功率 plan archetype
  - 高频失败模式
- 以 `task_type + deliverable_type` 维度追踪成功率

### 验收标准

- 相似任务命中历史模板时稳定性提升
- 出现新任务时优先复用模式，而不是手工加规则

---

## 5. 当前建议的 MVP

优先做最小闭环，不做大而全：

```text
user_input
-> infer_task_intent
-> infer_deliverable_spec
-> build_plan_template
-> execute
-> generate_deliverable
-> validate_output
-> retry once if needed
-> final_answer
```

MVP 重点不是“更复杂”，而是“更稳地交付”。

### MVP 暂不优先

- 复杂多 agent 自动协作
- 自修改驱动 planner
- 高级长期记忆策略
- 自动 workflow 全局优化

这些都应建立在交付闭环先成立的前提上。

---

## 6. 对当前项目的具体拆解

## P1：TaskIntent / DeliverableSpec

建议直接作为下一主线：

- 新增 schema
- 新增持久化字段
- 新增解析器
- 新增任务详情展示
- 补 3~5 个真实 smoke case

## P2：Deliverable-first Planner

- 引入 plan archetype
- planner 强制读 `DeliverableSpec`
- 计划中显式出现 `generate` / `validate`

## P3：Validation / Recovery

- 规则校验先落地
- evaluator 作为补充
- completed 改由 validation 驱动

---

## 7. 最终判断

这份设计文档给出的不是一个“未来也许可以做”的方向，而是：

- 当前项目从“可执行平台”走向“可交付平台”的自然下一步
- 且和我们已经完成的 P0 Trace / Skill / Runtime 建设是衔接良好的

因此，项目后续总方向建议收敛为：

```text
先完成 P0 的剩余收口，
然后正式进入 Deliverable-first Universal Task Architecture。
```

当前最值得优先立项的是：

1. `TaskIntentResolver`
2. `DeliverableSpecResolver`
3. `Deliverable-first Planner`
4. `ValidationReport + RecoveryAction`
