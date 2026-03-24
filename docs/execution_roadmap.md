# 执行路线图

更新时间：`2026-03-24`

## 文档定位

这份文档已经从“未来规划清单”调整为“历史路线图 + 当前剩余主线”。

原因很简单：仓库里不少旧路线图条目已经完成，如果继续保留原始待办口径，会造成明显的文档漂移。

当前执行应优先参考：

- `README.md`
- `docs/README.md`
- `docs/runbook.md`
- `docs/next_execution_todo.md`
- `docs/release_runbook.md`
- `docs/environment_matrix.md`

## 历史路线图完成情况

### P0：先止血，解决上线阻断项

#### 1. 安全清理

- 当前状态：已基本完成
- 已落地：
  - `.env.example` 与多环境模板已整理
  - `SECURITY.md` 已补齐
  - 发布就绪检查已纳入 `scripts/release_readiness_check.sh`
- 剩余说明：
  - 仍需在后续迭代中持续检查新配置项不要再次回到硬编码或弱口令模式

#### 2. 统一接口鉴权

- 当前状态：部分完成，仍需继续梳理
- 已落地：
  - 当前仓库已有 `apps/api/access_control.py`
  - actor / quota / governance 主链已具备权限模型基础
- 剩余说明：
  - 仍建议继续做一次完整路由盘点，确认所有控制面和任务面接口都落在一致的权限边界内

#### 3. 统一项目目标口径

- 当前状态：已基本完成
- 已落地：
  - `README.md` 已明确说明当前是“平台型可运行底座”，不是终态产品
  - 文档不再简单把 stage 完成等同于可直接上线
- 剩余说明：
  - 后续只需要持续维护文档同步

### P1：打通核心闭环，从执行平台变成交付平台

#### 4. 强化 `TaskIntent`

- 当前状态：部分完成
- 已落地：
  - `apps/api/task_intent_helpers.py`
  - intake 路由已形成输入分流、草稿理解与确认链
- 剩余说明：
  - 分类稳定性、澄清条件和复杂任务模板仍可继续增强

#### 5. 强化 `DeliverableSpec`

- 当前状态：部分完成
- 已落地：
  - `deliverable_spec_json`
  - `apps/worker/deliverable_runtime.py`
- 剩余说明：
  - 高频任务模板化程度还可继续提高
  - 交付定义与验收标准还可以更细

#### 6. 改造 planner 为 deliverable-first

- 当前状态：已有主链基础，仍需继续深化
- 已落地：
  - deliverable runtime 已存在
  - worker 已具备 validate / recovery 主链能力
- 剩余说明：
  - 复杂任务上的 deliverable-first 一致性仍需继续加强

#### 7. 强化交付校验与恢复动作

- 当前状态：部分完成
- 已落地：
  - `validation_report_json`
  - `recovery_action_json`
  - `/tasks/{id}/apply-recovery-action`
  - `/tasks/{id}/clarify`
- 剩余说明：
  - 恢复策略覆盖面和失败路径测试仍需继续补强

#### 8. 打通 clarify 主链

- 当前状态：已打通基础主链，仍需继续验证
- 已落地：
  - `/tasks/{id}/clarify`
  - clarify 相关状态已经进入任务运行上下文
- 剩余说明：
  - 仍应继续补足围绕 clarify 的链路测试与边界场景验证

### P2：补工程底座，降低后续演进风险

#### 9. 建立正式依赖与镜像构建

- 当前状态：已完成
- 已落地：
  - `requirements/dev.txt`
  - `apps/api/Dockerfile`
  - `apps/worker/Dockerfile`
  - `scripts/Dockerfile`
  - CI 中已执行镜像构建

#### 10. 建 migration 体系

- 当前状态：已具备基础体系
- 已落地：
  - `migrations/`
  - `scripts/run_migrations.py`
- 剩余说明：
  - 后续仍应坚持 schema 变更优先走 migration，而不是回到运行时自举

#### 11. 建最小测试体系

- 当前状态：已完成基础版，并进入继续补强阶段
- 已落地：
  - `pytest`
  - Playwright E2E
  - 多条 shell smoke checks
  - GitHub Actions CI
- 剩余说明：
  - 当前重点不是“从无到有”，而是继续提升关键主链覆盖密度

#### 12. 拆分超大文件

- 当前状态：已启动，但还没收口
- 已落地：
  - API 第一轮拆分：`apps/api/intake_task_routes.py`
  - Worker 第一轮拆分：`apps/worker/task_payloads.py`、`apps/worker/task_execution_runtime.py`
- 剩余说明：
  - 这是当前最值得继续推进的主线之一

## 当前剩余主线

结合当前仓库实际状态，后续执行重点建议收敛为以下几件事：

### 1. API 继续按领域拆分

- 目标：
  - 把 `apps/api/main.py` 收口成装配层
- 重点：
  - 拆 sessions / approvals / tasks detail / traces / replay

### 2. Worker 继续按运行时能力拆分

- 目标：
  - 把 `apps/worker/worker.py` 收口成主循环与装配层
- 重点：
  - 拆 planning / recovery / session memory / specialist orchestration / tool execution

### 3. 给关键主链补更厚的自动化测试

- 目标：
  - 提高重构安全边界
- 重点：
  - task runtime
  - clarify / recovery
  - session / review
  - change request / shadow validation / rollback

### 4. 继续提升浏览器级回归的本地可执行性

- 目标：
  - 让前端回归不只在 CI 方便执行
- 重点：
  - Playwright 依赖安装、运行说明、失败报告入口

### 5. 继续收口产品体验

- 目标：
  - 从“工程控制台”走向“更可理解的产品界面”
- 重点：
  - 最终交付呈现
  - 验收状态解释
  - 错误态 / 空态 / 加载态
  - 长期记忆命中解释

## 结论

旧路线图里最重要的“基础设施、工程化、发布验证、文档补齐”工作，大部分已经完成。

当前项目真正剩下的，不再是“补齐平台地基”，而是：

- 继续压缩超大文件带来的维护成本
- 提升关键主链的测试可信度
- 让当前平台能力更稳定地收口到可持续迭代的产品形态
