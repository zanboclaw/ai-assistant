# ai-assistant P0 / P1 / P2 执行版

## 0. 执行原则

这份文档不是平台总纲，而是**接下来真实可交付的实施计划**。

目标只有一个：

**在不破坏现有控制面的前提下，让 ai-assistant 在 3 个阶段里，完成“可观测、可复用、可记忆、可治理”的最小闭环。**

### 必须遵守的约束

1. 不重写现有 task / approval / audit / checkpoint 主链
2. PostgreSQL + Redis 仍是唯一状态中心
3. 新能力只能挂在现有主链上
4. 每阶段必须有清晰验收标准
5. 任何阶段都不直接做生产级自修改

---

## 1. P0：可观测 + MCP + 最小 Skill

### 1.1 目标

在不改主链语义的前提下，让系统：

- 看得见自己怎么执行
- 能接入外部 MCP 工具
- 能以最小成本开始复用 Skill

这是收益最高、破坏最小的一阶段。

### 1.2 范围

#### A. 增加 tracing

新增：

- `task_trace`
- `step_trace`
- `model_trace`
- `tool_trace`
- `retrieval_trace`（先留空结构）
- `skill_trace`（先做最小版）

记录字段至少包括：

- trace_id
- task_run_id
- task_step_id
- model_name
- prompt_version
- tool_name
- tool_args_hash
- skill_id（可空）
- started_at / ended_at
- status
- error_summary

#### B. Prompt / Model / Tool 可回放

每个 step 必须能知道：

- 用了哪个 prompt 版本
- 调了哪个模型
- 调了哪些工具
- 工具是否成功
- 重试了几次

#### C. MCP Tool Registry

扩展 Tool Registry，支持：

- `builtin`
- `mcp_stdio`
- `mcp_http`

新增字段：

- `provider_type`
- `transport`
- `server_name`
- `provider_config`
- `risk_level`
- `approval_required`

#### D. 最小 Skill Registry

只做：

- Skill metadata 注册
- Skill package 导入
- Skill discovery
- 显式 skill invocation
- 最小 skill trace

先**不做**：

- Internal skill authoring UI
- generated skill
- skill marketplace
- team-wide publishing workflow

### 1.3 交付结果

- 任意任务都能看到 step 执行轨迹
- 至少接入 1 个 MCP 工具
- 至少能导入 1 个 Skill 包
- 用户可以显式指定 Skill 执行一次任务
- 审批、checkpoint、resume 主链不被破坏

### 1.4 数据结构

新增表：

- `task_traces`
- `step_traces`
- `model_traces`
- `tool_traces`
- `skill_traces`
- `skills`
- `skill_versions`

### 1.5 验收标准

- 任意任务都能在 UI 中看到 step trace
- 任意工具调用都有 trace_id
- 至少 1 个 MCP tool 可注册并执行
- 至少 1 个 Skill 可导入并被显式调用
- 所有 trace 都能关联到 task_run_id
- 现有审批 / 恢复测试全部通过

---

## 2. P1：最小记忆 + Retrieval + Skill 复用增强

### 2.1 目标

让系统具备真正的**最小长期记忆能力**，并让 Skill 不只是能导入，而是能和 memory、retrieval 协同工作。

### 2.2 范围

#### A. 三层记忆的最小版

只实现：

- Session Working Memory
- Compressed Long-term Memory
- Vector Retrieval Memory

不做复杂记忆图谱，不做太多自动分类。

#### B. 引入 Qdrant

Qdrant 用于：

- 历史任务摘要 embedding
- 常用 Skill few-shot 样例 embedding
- 项目资料片段 embedding

#### C. 任务前 memory 注入

在 Planner 前加入：

1. 加载 session working memory
2. 检索 long-term memory
3. 从 vector DB 检索 top-k 相关片段
4. 将结果写入 retrieval trace

#### D. 任务后记忆沉淀

任务完成后自动抽取：

- summary
- preference
- fact
- reusable example

#### E. Skill 使用统计

记录：

- 某 skill 被谁用了
- 哪类任务用了
- 成功率
- 平均耗时
- 是否经常被审批打断

### 2.3 交付结果

- 系统能记住用户偏好
- 同类任务能复用历史经验
- Skill 可以基于记忆推荐或增强执行
- retrieval 过程可追踪、可解释

### 2.4 数据结构

新增表：

- `memory_items`
- `memory_summaries`
- `memory_preferences`
- `memory_facts`
- `memory_embeddings`
- `retrieval_traces`
- `skill_usage_stats`

### 2.5 验收标准

- 同一用户重复任务能命中历史偏好
- 每次任务结束至少生成 1 条 long-term summary
- retrieval trace 在 UI 可查看
- Skill 成功率和使用频次可统计
- 支持手动查看和删除 memory item
- memory 注入不明显拉低任务成功率

---

## 3. P2：可治理执行 + 权限模型 + 审批策略升级

### 3.1 目标

把已有的治理能力从“有审批”升级为“**有边界、可分层、可控可解释**”。

### 3.2 范围

#### A. 最小 AuthZ 层

先用 Casbin，不急着上 OpenFGA。

对象：

- user
- team
- assistant
- task
- tool
- skill
- memory_space

动作：

- read
- create
- update
- execute
- approve
- reject
- publish
- manage
- access_memory

#### B. Tool / Skill / Memory 权限分层

必须支持：

- 谁能执行某个工具
- 谁能调用某个 Skill
- 谁能访问某个 memory scope
- 谁能发布 Skill
- 谁能审批高风险任务

#### C. 审批白名单与自动审批策略升级

引入风险分级：

- L0：自动通过
- L1：自动通过，但必须 shadow / trace
- L2：系统建议，人类确认
- L3：必须人工审批

审批策略判断维度：

- 工具风险
- Skill 风险
- 当前任务类型
- 用户角色
- memory scope
- 外部副作用

#### D. 审批与审计统一

所有拒绝、放行、升级都必须进入 audit log。

### 3.3 交付结果

- 系统具备最小角色边界
- 高风险工具与 Skill 真正受控
- memory 不再是默认全可见
- 自动审批与人工审批开始形成分层结构

### 3.4 数据结构

新增或扩展：

- `policy_rules`
- `subject_roles`
- `resource_scopes`
- `approval_policies`
- `approval_policy_hits`

### 3.5 验收标准

- 至少 3 类角色权限能跑通
- tool execute 权限可独立控制
- skill invoke / publish 权限可独立控制
- memory scope 访问可被限制
- 自动审批策略至少能覆盖 2 类低风险场景
- 所有拒绝与放行都写入审计日志

---

## 4. 暂不进入本轮执行的内容

以下内容保留在平台总纲里，但**不进入 P0 / P1 / P2**：

- Internal skill authoring UI
- generated tool
- generated skill
- self-check / diagnose / repair
- OpenFGA 全量关系型授权
- full marketplace / sharing system
- 自动 rollout / 自动自修改

这些功能不是不做，而是必须建立在 P0 / P1 / P2 跑稳之后。

---

## 5. 交付顺序建议

### 第一个阶段：先让系统“看得见”

先做 tracing、MCP、最小 Skill import。

### 第二个阶段：再让系统“记得住”

做最小 memory 和 retrieval。

### 第三个阶段：最后让系统“管得住”

做 Casbin + 风险分级审批。

一句话版本：

- **P0：可观测**
- **P1：可记忆**
- **P2：可治理**

---

## 6. 每阶段结束时必须回答的问题

### P0 结束后

- 我能不能解释任意一次任务为什么这样执行？
- 我能不能接一个 MCP 工具而不破坏主链？
- 我能不能让 Skill 作为最小可复用能力被调用？

### P1 结束后

- 系统能不能记住用户、项目和高质量历史？
- Skill 能不能借助记忆真正提升任务质量？
- retrieval 有没有被 trace 出来？

### P2 结束后

- 谁能执行什么，边界是否清楚？
- 哪些动作能自动批，哪些必须人工批？
- 任何重要动作是否都能被追踪和审计？

---

## 7. 建议先做的专业 pack

执行版里建议优先做 **Research / Analysis pack** 作为验证对象。

原因：

- 对 memory、retrieval、skill 模板、审计、引用都高度相关
- 风险比 App Builder 小
- 更容易验证“模糊任务 -> workflow -> 治理”的价值

它最适合作为 P0 / P1 / P2 的贯穿样板。
