# 执行路线图

这份文档用于把当前项目后续工作按优先级收敛成一条可执行主线。

原则：

- 先止血，再扩展
- 先补交付闭环，再补更多能力
- 先补安全和工程化，再推进产品化体验

## P0：先止血，解决上线阻断项

### 1. 安全清理

目标：

- 把仓库从“危险原型”拉回“可控内部环境”

执行项：

- 清理 `.env.example` 中的真实形态密钥
- 替换 `infra/compose/docker-compose.yml` 中的默认弱口令与硬编码敏感配置
- 补齐发布前安全检查，使 `RELEASE_CHECKLIST.md` 与实际仓库一致

完成标准：

- 仓库内无真实密钥
- 默认配置不再暴露明显生产风险
- 发布检查项可实际通过

### 2. 统一接口鉴权

目标：

- 让 actor 权限模型真正落地

执行项：

- 统一梳理 `apps/api/main.py` 所有路由
- 给未鉴权接口补 `require_actor_permission`

优先补齐：

- `/risk-policies`
- `/monitor/overview`
- `/sessions*`
- `/tasks*`
- `/approvals`

完成标准：

- 所有接口都有明确的 `read / operate / admin` 要求
- Web 传递的 actor 头与后端权限校验一致

### 3. 统一项目目标口径

目标：

- 停止“Stage 完成”和“产品完成”混淆

执行项：

- 修订 `README.md`
- 修订 `version.json`
- 修订 `docs/unified_delivery_execution_plan.md`

完成标准：

- 文档不再暗示 `Stage 7 completed = 产品接近上线`
- 下一步主线明确聚焦交付闭环

## P1：打通核心闭环，从执行平台变成交付平台

### 4. 强化 `TaskIntent`

目标：

- 让系统先正确理解任务类型，而不是直接开跑

执行项：

- 重构 `apps/api/task_intent_helpers.py`
- 把当前 `heuristic_v1` 升级为“任务类型模板 + 明确澄清条件”
- 给高频任务建立稳定分类规则

优先覆盖：

- 问答
- 调研
- 内容生成
- 改写
- 执行类任务

完成标准：

- 模糊任务不会直接错误落入执行链
- 需要澄清的任务能稳定标记出来

### 5. 强化 `DeliverableSpec`

目标：

- 把“要交付什么”变成运行时一等对象

执行项：

- 扩展 `apps/api/task_intent_helpers.py` 的 `infer_deliverable_spec`
- 为各类任务定义：
  - `deliverable_type`
  - `expected_sections`
  - `quantity_hint`
  - `acceptance_hints`
  - `clarify` 条件

完成标准：

- 每个任务创建时都能产出明确交付定义
- 不再只有“执行一下”这种抽象目标

### 6. 改造 planner 为 deliverable-first

目标：

- 规划围绕成品，而不是围绕工具

执行项：

- 重构 `apps/worker/worker.py` 中的 deliverable-first 规划逻辑
- 强制高频任务计划显式出现：
  - 生成成品
  - 校验成品
- 禁止 research 类任务停在搜索摘要

完成标准：

- planner 输出默认包含 `generate + validate`
- “完成”不再只是步骤跑完

### 7. 强化交付校验与恢复动作

目标：

- 把 `validation_report` 和 `recovery_action` 升级为主流程判断器

执行项：

- 强化 `apps/worker/worker.py` 中的交付校验与恢复逻辑
- 规范失败恢复动作：
  - `clarify`
  - `retry_generate`
  - `retry`
  - `replan`

完成标准：

- 结果不合格时系统优先恢复，不是直接失败
- “执行成功但交付失败”能被明确识别

### 8. 打通 clarify 主链

目标：

- 模糊需求进入“补充信息再继续”的正式闭环

执行项：

- 完善 `/tasks/{id}/clarify`
- 串稳 clarification history、重建后的 `task_intent` 与 `deliverable_spec`

完成标准：

- clarify 成为主恢复路径之一

## P2：补工程底座，降低后续演进风险

### 9. 建立正式依赖与镜像构建

目标：

- 停止运行时动态安装依赖

执行项：

- 增加依赖文件并锁版本
- 为 `api / worker / scheduler` 增加 Dockerfile
- 重构 `infra/compose/docker-compose.yml` 使用预构建镜像

完成标准：

- 容器启动不再依赖运行时 `pip install`
- 环境可重复构建

### 10. 建 migration 体系

目标：

- 停止依赖运行时 `ensure_*` 和 `ALTER TABLE IF NOT EXISTS`

执行项：

- 为核心表建立正式 migration

优先覆盖：

- `task_runs`
- `task_steps`
- `approvals`
- `sessions`
- `session_memories`
- `session_states`
- `agent_runs`
- `evaluator_runs`
- `change_requests`
- traces 系列表

完成标准：

- 新环境可通过 migration 完整初始化
- schema 演进不再依赖应用启动自举

### 11. 建最小测试体系

目标：

- 从“脚本 smoke”升级为“测试 + smoke”

执行项：

- 为以下模块建立单元测试：
  - `task_intent_helpers`
  - deliverable validation
  - approval rules
  - change request shadow / rollback
- 保留现有 `scripts/*.sh` 作为集成 smoke

完成标准：

- 核心业务规则可自动断言
- 关键闭环不只靠手工脚本验证

### 12. 拆分超大文件

目标：

- 降低未来维护难度

执行项：

- 拆 `apps/api/main.py`
- 拆 `apps/worker/worker.py`
- 拆 `apps/web/index.html`

建议方向：

- API 按 `tasks / sessions / governance / monitor / changes / agents`
- Worker 按 `planning / tools / approvals / validation / traces / session_memory`
- Web 至少拆成多文件脚本

完成标准：

- 主入口显著瘦身
- 新需求不再持续堆到单文件里

## P3：把工程控制台推进为可用产品

### 13. 建输入分流层

目标：

- 区分聊天、澄清、正式执行

执行项：

- 在任务创建前增加输入路由
- 简单问答走 fast path
- 复杂请求进入草稿态或正式任务

完成标准：

- 用户输入不会默认全部创建任务

### 14. 建草稿态与确认流

目标：

- 降低误执行和错误规划成本

执行项：

- 前端增加草稿任务视图
- 展示系统理解出的：
  - `task_intent`
  - `deliverable_spec`
  - 是否需要 clarify
- 用户确认后再创建正式任务

完成标准：

- 模糊任务先确认再执行
- 误判成本明显下降

### 15. 优化最终交付展示层

目标：

- 让用户先看到成品，而不是先看到运行细节

执行项：

- 重构任务详情页
- 默认展示：
  - 最终结果
  - 验收状态
  - 恢复建议
- 步骤、trace、agent、governance 退到高级视图

完成标准：

- 产品感明显提升
- 非技术用户也能理解结果状态

## P4：最后再做平台增强

### 16. 提升多 Agent 的真实协作价值

目标：

- 从“观测骨架”升级为“真正提升产出质量”

执行项：

- 明确哪些任务真的需要 specialist fan-out
- 用 evaluator 结果反哺 planner 和 specialist 策略

完成标准：

- 多 Agent 能稳定提升结果质量

### 17. 长期记忆与经验复用

目标：

- 从 session working memory 走向长期经验沉淀

执行项：

- 增加 retrieval memory / pattern memory
- 区分 conversation memory 与 task memory

完成标准：

- 系统能跨任务复用经验

### 18. 更细粒度权限与运营能力

目标：

- 从本地实验平台走向可运营系统

执行项：

- 更细粒度 authz
- 成本 / 配额治理
- 多用户 / 多租户准备

完成标准：

- 有机会走向真实部署与运营

## 当前执行顺序

1. `P0-安全与鉴权`
2. `P1-交付闭环`
3. `P2-工程化与拆模块`
4. `P3-对话体验和产品化`
5. `P4-平台增强`
