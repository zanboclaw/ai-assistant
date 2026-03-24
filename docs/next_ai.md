# 项目后续执行文档

更新时间：`2026-03-25`

以下内容基于当前目录 `/opt/ai-assistant` 作为项目根目录分析，结合当前对话中已经确认的事实，以及仓库中的真实代码、配置、测试、脚本和文档内容整理而成。

## 1. 项目当前状态总结

### 1.1 分析依据

本次判断主要依据以下真实文件与目录：

- 项目入口与定位：
  - [`README.md`](/opt/ai-assistant/README.md)
- 文档导航与当前有效文档：
  - [`docs/README.md`](/opt/ai-assistant/docs/README.md)
- 运行手册：
  - [`docs/runbook.md`](/opt/ai-assistant/docs/runbook.md)
- 运维手册：
  - [`docs/operations_runbook.md`](/opt/ai-assistant/docs/operations_runbook.md)
- API 与数据模型索引：
  - [`docs/api_data_model_index.md`](/opt/ai-assistant/docs/api_data_model_index.md)
- 当前剩余主线：
  - [`docs/next_execution_todo.md`](/opt/ai-assistant/docs/next_execution_todo.md)
- 历史路线图映射：
  - [`docs/execution_roadmap.md`](/opt/ai-assistant/docs/execution_roadmap.md)
- API 主入口：
  - [`apps/api/main.py`](/opt/ai-assistant/apps/api/main.py)
- Intake/Fast Path/Task 创建入口：
  - [`apps/api/intake_task_routes.py`](/opt/ai-assistant/apps/api/intake_task_routes.py)
- Worker 主入口：
  - [`apps/worker/worker.py`](/opt/ai-assistant/apps/worker/worker.py)
- Worker 执行编排：
  - [`apps/worker/task_execution_runtime.py`](/opt/ai-assistant/apps/worker/task_execution_runtime.py)
- Worker 交付校验与恢复：
  - [`apps/worker/deliverable_runtime.py`](/opt/ai-assistant/apps/worker/deliverable_runtime.py)
- Worker 任务载荷与长期记忆注入：
  - [`apps/worker/task_payloads.py`](/opt/ai-assistant/apps/worker/task_payloads.py)
- 前端页面与交互：
  - [`apps/web/index.html`](/opt/ai-assistant/apps/web/index.html)
  - [`apps/web/assets/dashboard_runtime.js`](/opt/ai-assistant/apps/web/assets/dashboard_runtime.js)
  - [`apps/web/assets/dashboard_task_utils.js`](/opt/ai-assistant/apps/web/assets/dashboard_task_utils.js)
  - [`apps/web/assets/dashboard.js`](/opt/ai-assistant/apps/web/assets/dashboard.js)
  - [`apps/web/assets/dashboard.css`](/opt/ai-assistant/apps/web/assets/dashboard.css)
- 依赖文件：
  - [`requirements/base.txt`](/opt/ai-assistant/requirements/base.txt)
  - [`requirements/dev.txt`](/opt/ai-assistant/requirements/dev.txt)
  - [`package.json`](/opt/ai-assistant/package.json)
- 部署配置：
  - [`infra/compose/docker-compose.yml`](/opt/ai-assistant/infra/compose/docker-compose.yml)
  - [`.env.example`](/opt/ai-assistant/.env.example)
- CI：
  - [`.github/workflows/ci.yml`](/opt/ai-assistant/.github/workflows/ci.yml)
- 发布检查脚本：
  - [`scripts/release_readiness_check.sh`](/opt/ai-assistant/scripts/release_readiness_check.sh)
- E2E 测试：
  - [`tests/e2e/dashboard.spec.js`](/opt/ai-assistant/tests/e2e/dashboard.spec.js)
  - [`tests/e2e/mock_api_server.py`](/opt/ai-assistant/tests/e2e/mock_api_server.py)

### 1.2 项目核心目标

#### 已确认

从 [`README.md`](/opt/ai-assistant/README.md)、[`infra/compose/docker-compose.yml`](/opt/ai-assistant/infra/compose/docker-compose.yml)、[`docs/api_data_model_index.md`](/opt/ai-assistant/docs/api_data_model_index.md) 可以确认，这个项目的核心目标不是单点聊天机器人，而是一个“本地可运行、带治理、可审计、可恢复、可扩展到多 Agent 的 AI 助理执行平台”。

已落地的主线包括：

- 输入分流、草稿确认与 Fast Path：
  - `POST /intake/route`
  - `POST /intake/confirm`
  - `POST /chat/fast-path`
- 正式任务执行与恢复：
  - `POST /tasks`
  - `GET /tasks/*`
  - `interrupt / resume / clarify / apply-recovery-action`
- Session、长期记忆、review：
  - `sessions`
  - `session state`
  - `session reviews`
  - `long_term_memories`
  - `/memories/search`
- 治理与控制面：
  - actor / quota
  - model provider / route
  - tool registry
  - risk policy
  - change request / shadow validation / rollback
- Stage 5/6/7 多 Agent 与评估提案主线：
  - `agent_runs`
  - `evaluator_runs`
  - `workflow_proposals`

#### 推断但有代码支撑

结合 [`apps/web/index.html`](/opt/ai-assistant/apps/web/index.html) 和 [`apps/web/assets/dashboard.js`](/opt/ai-assistant/apps/web/assets/dashboard.js)，项目正在从“工程控制台”继续向“任务工作台产品”演进，目标用户不只是开发者，也包括需要通过 Web 页面完成任务起草、执行追踪、审批恢复和治理巡检的内部运营/技术角色。

### 1.3 当前对话中已经确认的事项

#### 已确认

- `2719` 任务失败问题已定位并修复。
- 修复内容已经进入代码并推送到 GitHub。
- 已新增并通过相关测试：
  - [`tests/test_worker_search_query_sanitization.py`](/opt/ai-assistant/tests/test_worker_search_query_sanitization.py)
  - [`tests/test_worker_validation.py`](/opt/ai-assistant/tests/test_worker_validation.py)
  - [`tests/test_worker_deliverable_prompt_sanitization.py`](/opt/ai-assistant/tests/test_worker_deliverable_prompt_sanitization.py)
- 前端已经完成一轮体验重构，任务起草器已拆为独立页面，支持多轮任务对话与“开始新任务对话”。
- 文档体系已经做过一轮整理，当前一线文档入口明确写在 [`docs/README.md`](/opt/ai-assistant/docs/README.md)。
- 所有已提交改动已经推到 `origin/master`。

### 1.4 本地仓库中已经实现了什么

#### 已确认

- 运行架构完整：
  - `postgres + redis + api + worker + web + scheduler`
  - 见 [`infra/compose/docker-compose.yml`](/opt/ai-assistant/infra/compose/docker-compose.yml)
- Python 与 Node 依赖已成型：
  - FastAPI、Redis、Postgres、OpenAI SDK、pytest、Playwright
  - 见 [`requirements/base.txt`](/opt/ai-assistant/requirements/base.txt)、[`requirements/dev.txt`](/opt/ai-assistant/requirements/dev.txt)、[`package.json`](/opt/ai-assistant/package.json)
- CI 已接入：
  - Python compile check
  - web syntax check
  - pytest
  - Playwright
  - Docker 构建检查
- 发布与运维脚本已存在：
  - 见 [`scripts/release_readiness_check.sh`](/opt/ai-assistant/scripts/release_readiness_check.sh) 及 `scripts/` 下 check 脚本
- Web 前端已具备多域工作台结构：
  - 工作台
  - 任务起草器
  - 任务
  - 工作区
  - Sessions
  - 治理
  - 监控
  - 设置
- 前端静态资源模块化已启动：
  - `apps/web/assets/dashboard_runtime.js`
  - `apps/web/assets/dashboard_task_utils.js`
  - `apps/web/assets/dashboard.js`
- 文档主入口、环境矩阵、运维与发布手册已存在：
  - [`docs/README.md`](/opt/ai-assistant/docs/README.md)
  - [`docs/environment_matrix.md`](/opt/ai-assistant/docs/environment_matrix.md)
  - [`docs/runbook.md`](/opt/ai-assistant/docs/runbook.md)
  - [`docs/release_runbook.md`](/opt/ai-assistant/docs/release_runbook.md)
  - [`docs/operations_runbook.md`](/opt/ai-assistant/docs/operations_runbook.md)

### 1.5 当前项目所处阶段

#### 判断

当前项目处于“可运行的平台型内测底座 / 工程化内测阶段”，还不是“可放心大规模长期使用的稳定产品”。

#### 判断依据

- 能力覆盖面已经很广，主干闭环基本打通。
- 工程底座、CI、E2E、运维文档都已经具备。
- 但核心超大文件仍然明显：
  - [`apps/api/main.py`](/opt/ai-assistant/apps/api/main.py) `934` 行
  - [`apps/worker/worker.py`](/opt/ai-assistant/apps/worker/worker.py) `4041` 行
  - [`apps/web/assets/dashboard.js`](/opt/ai-assistant/apps/web/assets/dashboard.js) `4450` 行
- 自动化覆盖率仍然偏低。最近本地执行 worker 主链相关 pytest 时，`coverage.xml` 总体覆盖率约 `18%`，离可放心承接大规模重构仍有明显距离。
- 对话中已确认，运行容器与本地代码曾出现不一致，需要靠 `docker cp` 临时同步，这说明部署一致性仍是风险点。
- 当前本地 Playwright 浏览器回归仍受系统依赖约束，执行 `tests/e2e/dashboard.spec.js` 时缺少 `libatk-1.0.so.0` 等运行库，说明“E2E 已接入”与“开发机可直接运行”之间仍有差距。

### 1.6 已有成果

- 平台主链已打通。
- 治理与变更链已有雏形。
- 前端已从单页堆叠控制台向多域工作台演进。
- 文档入口已开始收口。
- 最近一次真实故障修复已经形成“代码 + 测试 + 推送”的闭环。

### 1.7 主要缺口

- API、Worker、前端仍有明显超大文件风险。
- 核心执行链的自动化测试不够系统。
- 部署一致性与运行版本可见性不足。
- 长期记忆仍以关键词检索为主，质量和解释性还有提升空间。
- 前端虽然已重构一轮，但仍偏“工程控制台”，产品化程度还不够。
- 前端虽然已经开始从单脚本拆成多模块，但页面域逻辑仍主要集中在 `dashboard.js`，离真正可持续维护的前端分层还有距离。
- 权限与治理链虽然存在，但是否覆盖所有高风险接口，仍需系统盘点。

## 2. 待办事项总表

### 2.1 架构优化 / 重构

| 编号 | 任务 | 优先级 | 复杂度 |
|---|---|---:|---:|
| T1 | 继续拆分 API 主入口 `apps/api/main.py` | 高 | 高 |
| T2 | 继续拆分 Worker 主入口 `apps/worker/worker.py` | 高 | 高 |
| T3 | 前端静态控制台模块化拆分 | 高 | 高 |
| T4 | 收口为 migration-first 的 schema 管理模式 | 高 | 中 |

### 2.2 功能稳定性 / 核心闭环

| 编号 | 任务 | 优先级 | 复杂度 |
|---|---|---:|---:|
| T5 | 统一输入分流、长期记忆、Prompt 边界治理 | 高 | 中 |
| T6 | 强化交付校验、恢复动作和失败回放稳定性 | 高 | 中 |
| T7 | 提升长期记忆检索质量与命中解释 | 中 | 中 |
| T8 | 前端任务工作台继续产品化收口 | 中 | 中 |

### 2.3 测试与质量保障

| 编号 | 任务 | 优先级 | 复杂度 |
|---|---|---:|---:|
| T9 | 补 Task / Session / Governance 主链自动化测试 | 高 | 高 |
| T10 | 提升 Playwright 本地可执行性与前端回归覆盖 | 中 | 中 |
| T11 | 完善发布前质量门禁与验证脚本编排 | 中 | 中 |

### 2.4 部署 / 运维 / 可观测

| 编号 | 任务 | 优先级 | 复杂度 |
|---|---|---:|---:|
| T12 | 修复部署一致性与运行版本可见性 | 高 | 中 |
| T13 | 增强监控、日志、故障定位与值班手册 | 中 | 中 |

### 2.5 安全 / 治理 / 文档

| 编号 | 任务 | 优先级 | 复杂度 |
|---|---|---:|---:|
| T14 | 做权限边界与高风险控制面完整盘点 | 高 | 中 |
| T15 | 继续收口一线文档、归档历史方案、清理仓库杂项 | 中 | 低 |

## 3. 每项任务的详细说明

### T1. 继续拆分 API 主入口 `apps/api/main.py`

- 任务目的：把 API 层从“超大总入口”收口成“装配层 + 领域路由层”，降低耦合和回归风险。
- 具体内容：继续把 `tasks detail / steps / traces / replay / approvals / sessions / reviews / governance` 中仍留在 [`apps/api/main.py`](/opt/ai-assistant/apps/api/main.py) 的路由拆到独立模块，保持 [`apps/api/intake_task_routes.py`](/opt/ai-assistant/apps/api/intake_task_routes.py) 的拆分风格。
- 依赖项：[`docs/api_data_model_index.md`](/opt/ai-assistant/docs/api_data_model_index.md) 中的模块边界说明。
- 优先级：高。
- 复杂度：高。
- 建议执行顺序：1。
- 预期产出：新的路由模块文件、`main.py` 变薄、对应集成测试更新。

### T2. 继续拆分 Worker 主入口 `apps/worker/worker.py`

- 任务目的：把执行面从单一巨型运行时文件收口成可独立测试、可独立维护的模块。
- 具体内容：继续把 planning、approval、recovery、tool execution、stage5/6/7 orchestration、trace 写入等逻辑从 [`apps/worker/worker.py`](/opt/ai-assistant/apps/worker/worker.py) 中拆出，保持与 [`apps/worker/task_execution_runtime.py`](/opt/ai-assistant/apps/worker/task_execution_runtime.py)、[`apps/worker/deliverable_runtime.py`](/opt/ai-assistant/apps/worker/deliverable_runtime.py)、[`apps/worker/task_payloads.py`](/opt/ai-assistant/apps/worker/task_payloads.py) 相同的边界风格。
- 依赖项：可与 T1 并行推进，但建议共享边界设计。
- 优先级：高。
- 复杂度：高。
- 建议执行顺序：2。
- 预期产出：更薄的 worker 主循环、更清晰的执行模块分层、单元测试可直接覆盖独立模块。

### T3. 前端静态控制台模块化拆分

- 任务目的：降低前端继续迭代的难度，避免 [`apps/web/assets/dashboard.js`](/opt/ai-assistant/apps/web/assets/dashboard.js) 成为新的维护瓶颈。
- 具体内容：把前端按数据访问层、全局状态、任务起草器、工作区、治理、监控、Sessions、设置拆成多个静态 JS 模块；把大块样式按域拆分；保留当前无需引入新框架的部署方式。当前已经开始把运行时配置/本地存储层拆到 [`apps/web/assets/dashboard_runtime.js`](/opt/ai-assistant/apps/web/assets/dashboard_runtime.js)，把任务状态格式化与搜索辅助拆到 [`apps/web/assets/dashboard_task_utils.js`](/opt/ai-assistant/apps/web/assets/dashboard_task_utils.js)。
- 依赖项：以 [`apps/web/index.html`](/opt/ai-assistant/apps/web/index.html) 当前多域导航结构为基准。
- 优先级：高。
- 复杂度：高。
- 建议执行顺序：5。
- 预期产出：多文件前端模块结构、可读性更强的代码组织、保留现有功能不回退。

### T4. 收口为 migration-first 的 schema 管理模式

- 任务目的：避免数据库结构变更继续依赖运行时自举，提升部署一致性。
- 具体内容：盘点 API 和 Worker 中所有 `ensure_*table`、`ensure_*columns`、隐式 bootstrap 逻辑，把已稳定的 schema 收口到 `migrations/` 与 [`scripts/run_migrations.py`](/opt/ai-assistant/scripts/run_migrations.py)。
- 依赖项：需要先梳理当前 schema 实际来源。
- 优先级：高。
- 复杂度：中。
- 建议执行顺序：4。
- 预期产出：清晰的 migration 清单、减少运行时 schema 修补逻辑、更新 runbook。

### T5. 统一输入分流、长期记忆、Prompt 边界治理

- 任务目的：避免任务输入、长期记忆和生成提示词互相污染，提升结果稳定性。
- 具体内容：在 [`apps/worker/task_payloads.py`](/opt/ai-assistant/apps/worker/task_payloads.py) 与 [`apps/worker/deliverable_runtime.py`](/opt/ai-assistant/apps/worker/deliverable_runtime.py) 基础上，统一定义“原始用户输入”“planner 输入”“search query”“generation prompt”的边界与净化规则。
- 依赖项：现有 sanitize 逻辑与相关测试。
- 优先级：高。
- 复杂度：中。
- 建议执行顺序：3。
- 预期产出：统一的 payload/prompt 规范、更多边界测试、减少类似 Tavily 400 级别故障。

### T6. 强化交付校验、恢复动作和失败回放稳定性

- 任务目的：让失败任务能更稳定地自动恢复，减少误判和人工排查成本。
- 具体内容：继续增强 [`apps/worker/deliverable_runtime.py`](/opt/ai-assistant/apps/worker/deliverable_runtime.py) 中不同 `deliverable_type` 的校验器、`recovery_action_json` 生成逻辑、`clarify`/`apply-recovery-action` 失败路径覆盖。
- 依赖项：T5 的输入边界治理会直接影响校验可靠性。
- 优先级：高。
- 复杂度：中。
- 建议执行顺序：6。
- 预期产出：更多交付模板校验规则、失败路径样例、恢复动作验证测试。

### T7. 提升长期记忆检索质量与命中解释

- 任务目的：让长期记忆真正帮助任务，而不是只做简单关键词召回。
- 具体内容：继续优化 [`core/long_term_memory.py`](/opt/ai-assistant/core/long_term_memory.py) 的召回排序、scope 控制、命中解释稳定性，并让前端更清楚展示“为什么召回这条记忆”。
- 依赖项：T5 的边界治理要先稳住。
- 优先级：中。
- 复杂度：中。
- 建议执行顺序：10。
- 预期产出：更好的检索质量、更可信的命中解释、前端可读的引用理由。

### T8. 前端任务工作台继续产品化收口

- 任务目的：让前端从“工程控制台”进一步靠近“业务可理解工作台”。
- 具体内容：继续按 [`docs/frontend_experience_rebuild_plan.md`](/opt/ai-assistant/docs/frontend_experience_rebuild_plan.md) 收口首页工作台、工作区 Hero、空态/错误态/加载态、失败恢复提示、Agent 可视化、最终交付呈现。
- 依赖项：T3 完成后更容易持续演进。
- 优先级：中。
- 复杂度：中。
- 建议执行顺序：8。
- 预期产出：更清晰的主流程页面、更好的下一步动作引导、更低的学习成本。

### T9. 补 Task / Session / Governance 主链自动化测试

- 任务目的：给重构和持续交付提供足够的安全网。
- 具体内容：围绕 task runtime、clarify/recovery、session health/review/state、change request/shadow validation/rollback 补 API 级与 runtime 级测试。
- 依赖项：T1、T2 不必全部完成后再做，可以并行补。
- 优先级：高。
- 复杂度：高。
- 建议执行顺序：7。
- 预期产出：更厚的 pytest 用例、更稳定的回归保护、更高的重构信心。

### T10. 提升 Playwright 本地可执行性与前端回归覆盖

- 任务目的：让前端回归不只是在 CI 中可跑，也能在开发机稳定执行。
- 具体内容：完善 Playwright 本地运行说明、依赖安装说明、失败报告入口，并继续扩展 [`tests/e2e/dashboard.spec.js`](/opt/ai-assistant/tests/e2e/dashboard.spec.js) 对任务起草、任务工作区、治理、设置等路径的覆盖。
- 依赖项：T3、T8 的前端结构收口会让 E2E 更稳。
- 优先级：中。
- 复杂度：中。
- 建议执行顺序：9。
- 预期产出：更完整的 E2E 覆盖、清晰的本地执行手册、失败截图/报告使用说明。

### T11. 完善发布前质量门禁与验证脚本编排

- 任务目的：让发布前检查从“脚本很多”变成“流程清楚、结果可读、失败可定位”。
- 具体内容：梳理 [`scripts/release_readiness_check.sh`](/opt/ai-assistant/scripts/release_readiness_check.sh) 与 `scripts/` 下多个 check 的调用关系，形成分层的日常检查、回归检查、发布检查入口。
- 依赖项：T9、T10 越完整，这个任务越有价值。
- 优先级：中。
- 复杂度：中。
- 建议执行顺序：11。
- 预期产出：统一的检查矩阵、可读性更高的发布前流程、文档同步更新。

### T12. 修复部署一致性与运行版本可见性

- 任务目的：避免“本地代码修了，但容器里跑的不是这版”的情况再次出现。
- 具体内容：补容器镜像版本/commit 指纹展示、API/Worker 当前版本接口或监控输出、部署后自检机制；尽量消除需要手工 `docker cp` 的情况。
- 依赖项：可与 T11 并行。
- 优先级：高。
- 复杂度：中。
- 建议执行顺序：4。
- 预期产出：版本指纹、部署后一致性检查、运行容器版本可观测。

### T13. 增强监控、日志、故障定位与值班手册

- 任务目的：把已有监控与日志入口做成真正可用的故障定位体系。
- 具体内容：基于 [`docs/operations_runbook.md`](/opt/ai-assistant/docs/operations_runbook.md)、`logs/`、`monitor/overview`、task traces，补“常见故障 -> 定位步骤 -> 处理动作”的标准化模板。
- 依赖项：T12 的版本可见性会提升这个任务效果。
- 优先级：中。
- 复杂度：中。
- 建议执行顺序：12。
- 预期产出：更完整的运维手册、监控指标解释、故障排查流程。

### T14. 做权限边界与高风险控制面完整盘点

- 任务目的：确认所有关键控制面接口都落在正确权限边界内。
- 具体内容：基于 [`apps/api/access_control.py`](/opt/ai-assistant/apps/api/access_control.py) 和 [`docs/api_data_model_index.md`](/opt/ai-assistant/docs/api_data_model_index.md)，逐项盘点 task、session、governance、change request、model route、tool registry、risk policy 接口的 `read / operate / admin` 边界。
- 依赖项：T1 拆分后更容易做，但可以先盘点。
- 优先级：高。
- 复杂度：中。
- 建议执行顺序：5。
- 预期产出：权限盘点表、测试清单、必要的接口修正。

### T15. 继续收口一线文档、归档历史方案、清理仓库杂项

- 任务目的：避免文档再次漂移，降低新接手成本和误读概率。
- 具体内容：保持 [`docs/README.md`](/opt/ai-assistant/docs/README.md) 作为统一入口；同步 README/runbook/API 索引；归档旧路线图；处理 `docs/` 下临时产物。
- 依赖项：与各任务同步进行。
- 优先级：中。
- 复杂度：低。
- 建议执行顺序：13。
- 预期产出：一致的一线文档、清晰的 archive 边界、更干净的仓库状态。

## 4. 分阶段执行路线图

### 第一阶段：先稳住运行与质量护栏

建议优先执行：T5、T6、T9、T12、T14。

这样安排的原因：

- 当前项目最大风险不是“没有功能”，而是“功能很多但边界、测试、部署一致性还不够稳”。
- `2719` 的真实问题已经证明，输入边界、交付校验和部署一致性会直接影响真实任务结果。
- 在没有足够质量护栏之前，继续大规模重构会放大回归风险。

这一阶段的目标是：

- 主链更稳
- 测试更厚
- 部署更可信
- 权限边界更清楚

### 第二阶段：收口超大文件与 schema 漂移风险

建议执行：T1、T2、T4。

这样安排的原因：

- 架构重构本身价值很高，但必须建立在第一阶段的质量护栏之上。
- API、Worker 这两个超大文件是后续所有演进的主要瓶颈。
- migration-first 是为了防止环境差异在后续继续积累。

这一阶段的目标是：

- API 变成装配层
- Worker 变成主循环装配层
- schema 变更路径统一

### 第三阶段：让前端从控制台走向更成熟的工作台

建议执行：T3、T8、T10。

这样安排的原因：

- 当前前端已有较好的信息架构，但代码组织和产品化细节还未收口。
- 先做模块化，再继续做体验打磨，更稳。
- E2E 要跟着页面结构一起收口，避免反复改测试。

这一阶段的目标是：

- 前端更容易继续维护
- 用户更容易理解任务状态与下一步动作
- 前端回归更容易执行

### 第四阶段：增强助理化能力与运维成熟度

建议执行：T7、T11、T13、T15。

这样安排的原因：

- 长期记忆质量、运行监控和文档治理，是平台从“可运行”走向“可长期运营”的关键。
- 这类任务需要前面三阶段先把主链、架构和前端基础稳定下来。

这一阶段的目标是：

- 记忆检索更像真正的助理能力
- 发布与巡检更可标准化执行
- 文档与仓库状态更可持续

## 5. 当前待确认信息

### 5.1 可从当前对话确认的信息

- 当前项目根目录就是 `/opt/ai-assistant`。
- 最近一轮前端改造与 worker 稳定性修复已经完成并推送到 GitHub。
- `2719` 的失败根因已经确认并修复：
  - `web_search.query` 被长期记忆污染
  - `copywriting_bundle` 的分组式标题/正文校验误判
- 当前环境里存在可用的 DeepSeek 兼容模型路由。
- 后续目标不是只做规划，而是继续按工程方式收口和实现。

### 5.2 可从本地仓库确认的信息

- 项目是 Python + FastAPI + Worker + Postgres + Redis + 静态 Web + Scheduler 的组合架构。
- 当前前端不依赖重型前端框架，而是原生 HTML/CSS/JS。
- 当前已经存在 CI、pytest、Playwright、Docker 构建、发布检查脚本。
- 当前 docs 已明确区分一线文档和 archive/validation 文档。

### 5.3 当前无法确认但会影响执行判断的问题

- 终态产品的核心目标用户是谁。
  - 待确认：是偏内部技术平台、内部运营工作台，还是对外产品。
- 生产环境的认证方式是什么。
  - 待确认：当前仓库可见的是 `X-Actor-Name` 头与 RBAC/Quota 机制，但是否还有更完整的认证体系，仓库中未明确。
- 真实上线形态与发布路径是什么。
  - 待确认：当前仓库有 Docker Compose 和发布检查，但是否有 k8s、灰度、正式域名、反向代理拓扑，仓库中未体现。
- 目标并发、SLA 和容量边界是什么。
  - 待确认：这会直接影响缓存、队列、数据库、日志和监控方案。
- 长期记忆后续是否要升级为向量检索或混合检索。
  - 待确认：当前代码可见的是关键词与解释增强，不足以确认最终方向。
- 前端是否要长期保持原生静态架构。
  - 待确认：当前仓库支持继续用静态方式模块化，但是否未来迁移框架，没有明确决策。
- runtime schema bootstrap 是否允许长期保留一部分。
  - 待确认：需要结合部署方式和团队习惯决定最终收口程度。
