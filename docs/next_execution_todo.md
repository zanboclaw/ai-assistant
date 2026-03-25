# 当前执行待办

更新时间：`2026-03-25`

这份文档不再复述历史规划，而是基于当前仓库真实状态，收敛出“仍然值得继续做的事情”。

## 已经完成的主干事项

以下事项已经在当前仓库落地，不应继续作为待办重复追踪：

- 浏览器级 E2E 已接入：
  - `package.json`
  - `playwright.config.js`
  - `tests/e2e/dashboard.spec.js`
  - `tests/e2e/mock_api_server.py`
- GitHub Actions CI 已接入：
  - `.github/workflows/ci.yml`
- 发布收口与发布就绪检查已接入：
  - `scripts/release_readiness_check.sh`
  - `docs/release_runbook.md`
- 多环境模板与环境矩阵已补齐：
  - `env.sample.local`
  - `env.sample.validation`
  - `env.sample.production`
  - `docs/environment_matrix.md`
- 接口与数据模型索引已补齐：
  - `docs/api_data_model_index.md`
- 运维动作手册已补齐：
  - `docs/operations_runbook.md`
- `fast_path` 已具备独立轻量运行时：
  - `core/fast_path_runtime.py`
  - `POST /chat/fast-path`
- API 与 Worker 的第一轮模块拆分已落地：
  - `apps/api/intake_task_routes.py`
  - `apps/worker/task_payloads.py`
  - `apps/worker/task_execution_runtime.py`
- 前端静态控制台模块化已经启动第一轮拆分：
  - `apps/web/assets/dashboard_runtime.js`
  - `apps/web/assets/dashboard_task_utils.js`
- 协作、安全、版本记录已经具备基础文件：
  - `CHANGELOG.md`
  - `CONTRIBUTING.md`
  - `SECURITY.md`

## 当前仍然值得继续推进的事项

### 1. 继续拆分 `apps/api/main.py`

- 当前状态：
  - `apps/api/main.py` 已进一步收口为薄兼容导出层，实际装配与上下文绑定下沉到 `apps/api/api_app_context.py`
  - `apps/api/main.py` 已继续缩减到约 `934` 行，入口层已基本压缩为“装配 + 薄封装”结构
  - 已把 intake / task create-list 等入口迁移到 `apps/api/intake_task_routes.py`
  - 已把 task detail / steps / traces / replay / checkpoint 迁移到 `apps/api/task_query_routes.py`
  - 已把 task interrupt / resume / apply recovery action / clarify / approvals 路由迁移到 `apps/api/task_control_routes.py`
  - 已把 agent runs / evaluator runs / workflow proposals 的只读查询迁移到 `apps/api/multi_agent_query_routes.py`
  - 已把 multi-agent demo 的 bootstrap / execute / execute-worker / finalize 路由迁移到 `apps/api/multi_agent_demo_routes.py`
  - 已把 change request 的 list / detail / shadow validation 查询 / rollback draft 预览迁移到 `apps/api/change_request_query_routes.py`
  - 已把 change request 的 create / approve / reject / apply / rollback / shadow validate 写入链迁移到 `apps/api/change_request_control_routes.py`
  - 已把 `monitor/overview` 迁移到 `apps/api/monitor_routes.py`
  - 已把 sessions / reviews / state / memories 主链迁移到 `apps/api/session_routes.py`
  - 已把 risk / tool / model / access / audit / runtime metadata 迁移到 `apps/api/governance_routes.py`
  - 已把 skill registry 的 list / detail / import 迁移到 `apps/api/skill_routes.py`
  - 已把 change request / monitor 查询与部分聚合下沉到独立 store/business 模块
  - 已把 app 级公共依赖与 schema/task control helper 下沉到：
    - `apps/api/app_runtime.py`
    - `apps/api/schema_runtime.py`
    - `apps/api/task_control_runtime.py`
  - 已把 multi-agent 的 artifact / message / run / evaluator / workflow proposal / specialist draft / stage5 summary helper 下沉到：
    - `apps/api/api_multi_agent_runtime.py`
    - `apps/api/multi_agent_runtime.py`（兼容导出层）
  - 已把 workflow proposal shadow validation / change request shadow state 的上下文 helper 下沉到：
    - `apps/api/api_shadow_validation_runtime.py`
  - 已把 change request 草稿构建、baseline 读取、patch artifact 组装与 shadow overlay helper 下沉到：
    - `apps/api/api_change_request_runtime.py`
  - 已把 sandbox_file payload / acceptance / path guard / patch apply / redis monitor helper 下沉到：
    - `apps/api/api_sandbox_runtime.py`
  - 已把 change request apply / rollback 写入链 helper 下沉到：
    - `apps/api/api_change_apply_runtime.py`
  - 已把 API bootstrap / planner route / change gate helper 下沉到：
    - `apps/api/api_bootstrap_runtime.py`
- 仍然缺什么：
  - 主业务路由已不再驻留在 `main.py`
  - 后续若继续演进，重点会是继续按上下文对象细化 `api_app_context.py`，而不是回退到总入口堆叠
- 为什么仍然高优先级：
  - API 入口仍然过大，后续每次改任务链、会话链、治理链都容易互相影响
- 完成标准：
  - `main.py` 只保留应用装配、依赖注入、路由挂载
  - 主要业务路由按领域拆到独立模块

### 2. 继续拆分 `apps/worker/worker.py`

- 当前状态：
  - `apps/worker/worker.py` 已收口为薄兼容导出层，实际运行时绑定下沉到 `apps/worker/worker_runtime_context.py`
  - `apps/worker/worker.py` 已从约 `5054` 行继续压到约 `4041` 行
  - payload 读取与执行入口编排已拆到独立模块
  - deliverable 相关逻辑已有 `apps/worker/deliverable_runtime.py`
  - step approval 查询、创建、等待审批状态与审批判定规则已拆到 `apps/worker/approval_runtime.py`
  - 步骤请求规范化、planner 步骤校验、执行请求富化逻辑已拆到 `apps/worker/step_request_runtime.py`
  - 任务开始、成功收口、失败收口、task runtime state 持久化与 legacy step 生命周期逻辑已拆到 `apps/worker/task_lifecycle_runtime.py`
  - `process_task` 主流程 orchestration 已拆到 `apps/worker/task_processing_runtime.py`
  - structured step 的开始、执行请求处理、结果路由、异常收口、outcome/runtime state 持久化已拆到 `apps/worker/structured_step_runtime.py`
  - stage5/6/7 multi-agent runtime 的 artifact / message / run 写入、fanout、postrun finalize、mainline init 已拆到 `apps/worker/multi_agent_runtime.py`
  - runtime feedback / specialist fanout strategy helper 已跟随下沉到 `apps/worker/multi_agent_runtime.py`
  - planner 模型调用、planner fallback/source 选择已拆到 `apps/worker/planner_runtime.py`
  - planner fallback legacy step 规则也已跟随下沉到 `apps/worker/planner_runtime.py`
  - task/step/model/skill trace 上下文与写入逻辑已拆到 `apps/worker/trace_runtime.py`
  - session memory 推断、session state rebuild、任务完成后的 memory capture 已拆到 `apps/worker/memory_runtime.py`
  - web_search / http_request / MCP tool / execute_tool 分发链已拆到 `apps/worker/tool_runtime.py`
  - file/json/template/if-condition 这组本地 builtin tool helper 已拆到 `apps/worker/local_tool_runtime.py`
  - specialist agent run 的只读执行与结果产物写入已拆到 `apps/worker/agent_run_runtime.py`
  - task/agent queue、claim、stale requeue 与 task fetch helper 已拆到 `apps/worker/queue_runtime.py`
  - risk policy / tool registry / model route/provider 的 schema、seed、缓存加载与 provider client helper 已拆到 `apps/worker/governance_runtime.py`
  - `trace`、`multi-agent`、`planner`、`tool search` 这几组已存在 runtime 承接的包装层已继续收口为薄绑定
- 仍然缺什么：
  - `worker.py` 已完成“主循环 + 装配入口”收口
  - 后续若继续细化，重点是继续缩小 `worker_runtime_context.py` 的内部 helper 聚合面
- 为什么仍然高优先级：
  - 这是当前执行面的主要维护瓶颈，也是后续补测试最难的地方
- 完成标准：
  - `worker.py` 只保留主循环与装配
  - 计划、恢复、记忆、agent runtime、tool execution 能被独立测试

### 3. 前端静态控制台模块化拆分

- 当前状态：
  - `apps/web/assets/dashboard.js` 已从约 `4645` 行压到约 `1841` 行
  - 运行时配置、API Base 解析、本地存储读写与 tab 元信息已拆到 `apps/web/assets/dashboard_runtime.js`
  - 任务状态格式化、任务搜索辅助与 attention/action 分类 helper 已拆到 `apps/web/assets/dashboard_task_utils.js`
  - 任务召回解释与运行版本展示 helper 已拆到 `apps/web/assets/dashboard_experience.js`
  - 任务起草器、多轮任务对话、草稿确认、Fast Path 与 task skill 选择已拆到 `apps/web/assets/dashboard_composer.js`
  - 任务列表、任务工作区、恢复/clarify 操作与 Agent 视图已拆到 `apps/web/assets/dashboard_workspace.js`
  - Session 浏览器、长期记忆检索与 session review/state 操作已拆到 `apps/web/assets/dashboard_sessions.js`
  - 设置页运行环境摘要与界面偏好已拆到 `apps/web/assets/dashboard_settings.js`
  - 治理区与监控区主渲染已拆到：
    - `apps/web/assets/dashboard_governance.js`
    - `apps/web/assets/dashboard_monitor.js`
  - 治理区与监控区大块样式已拆到：
    - `apps/web/assets/dashboard_governance.css`
    - `apps/web/assets/dashboard_monitor.css`
  - `apps/web/index.html` 已调整为多脚本装配入口，先加载 runtime/task utils/experience，再加载 composer、sessions、governance、monitor、workspace 和 `dashboard.js`
  - `package.json` 中的 `check:web` 已同步覆盖新增前端模块
- 仍然缺什么：
  - 当前剩余在 `dashboard.js` 的部分主要是全局状态、路由切换、trace helper 和跨域装配逻辑
  - 后续若继续推进，可再按 home/app shell 或样式 token 层继续细拆
- 为什么仍然高优先级：
  - 当前前端信息架构已经成型，但后续产品化和交互迭代仍会被大单文件拖慢
- 完成标准：
  - 前端按 runtime/data access/state/view domain 继续拆成多文件
  - 核心页面域能独立维护，不必在单个超大脚本里改动所有逻辑

### 4. 深化主链测试覆盖

- 当前状态：
  - `pytest -q` 可运行
  - CI 已接入 `pytest`
  - 前端已有 Playwright E2E
  - 新增 worker runtime 拆分回归：
    - `tests/test_worker_governance_runtime.py`
    - `tests/test_worker_local_tool_runtime.py`
    - `tests/test_worker_planner_runtime.py`（新增 fallback 覆盖）
  - 新增 API 拆分回归：
    - `tests/test_api_task_query_routes.py`
    - `tests/test_api_task_control_routes.py`
    - `tests/test_api_session_routes.py`
    - `tests/test_api_governance_routes.py`
    - `tests/test_api_skill_routes.py`
    - `tests/test_api_multi_agent_query_routes.py`
    - `tests/test_api_change_request_query_routes.py`
    - `tests/test_api_change_request_control_routes.py`
    - `tests/test_api_monitor_routes.py`
    - `tests/test_api_multi_agent_demo_routes.py`
  - 本轮新增：
    - `tests/test_version_metadata.py`
    - `tests/test_api_routes_integration.py` 已适配新 API 装配层
    - `tests/test_api_governance_routes.py` 新增 admin 拒绝路径覆盖
    - `tests/test_api_task_control_routes.py` 新增 operate 拒绝路径覆盖
    - `tests/test_api_session_routes.py` 新增 `daily-run` admin 边界拒绝路径覆盖
    - `tests/test_worker_clarification_runtime.py`、`tests/test_session_runtime.py`、`tests/test_worker_trace_runtime.py` 已补 preflight clarify `waiting_clarification` 状态、task trace 终态和 session 活跃口径回归
    - `tests/test_api_change_request_control_routes.py` 新增 `create / approve / apply / rollback / shadow-validate` 权限边界回归
    - `tests/test_runtime_logging.py` 新增日志目录/文件不可写降级覆盖
    - `tests/test_long_term_memory.py` 新增 session / actor scope 排序与解释覆盖
- 仍然缺什么：
  - 深层治理链、worker 主链、change request / rollback 的系统化测试仍不够厚
  - 覆盖率虽然接入，但关键主链的断言密度仍有继续补强空间
- 为什么仍然高优先级：
  - 现在仓库已经不是原型规模，仅靠 smoke 和局部规则测试不足以承接继续重构
- 完成标准：
  - 为 task 主链、session 主链、governance 主链补更完整的 API / runtime 集成测试
  - 对关键失败恢复路径建立可重复断言

### 5. 提升真实浏览器 E2E 的可执行性

- 当前状态：
  - Playwright 测试代码、mock API 与 CI 步骤都已存在
  - 前端多脚本拆分后的 `node --check` 已通过
  - 已新增 `scripts/playwright_local_check.sh`，可直接诊断浏览器二进制和系统共享库缺失
  - `bash scripts/playwright_local_check.sh` 已通过
  - `npx playwright test tests/e2e/dashboard.spec.js` 已可在当前机器稳定执行
  - E2E 已覆盖任务起草器、多轮对话、工作区、Session Memory Search、设置、治理、监控，以及工作区 `Agents / Session` 子页签
  - 本轮已把 preflight clarify 的“待补信息 / 待澄清”展示和补充澄清操作路径纳入浏览器回归
- 仍然缺什么：
  - 当前 E2E 仍主要依赖 mock API
  - 如果后续前端继续产品化，仍需要继续扩任务失败恢复、治理写入和设置偏好持久化等浏览器覆盖面
- 为什么仍然中高优先级：
  - 前端回归已经具备框架，但还需要进一步降低团队真实使用成本
- 完成标准：
  - 本地和 CI 都能按统一命令稳定执行
  - 失败日志、截图、报告入口足够清晰

### 6. 增强长期记忆检索质量

- 当前状态：
  - `core/long_term_memory.py` 已支持关键词标准化、命中解释和引用提示
  - `/memories/search` 已可直接检索并回传解释字段
  - 本轮已补 session / actor scope 排序加权、标题直命中解释、历史复用次数解释
  - 前端任务草稿、Fast Path 和 Session Memory Search 已直接展示命中原因与引用建议
- 仍然缺什么：
  - 目前仍以关键词检索为主
  - memory scope、排序质量、跨任务经验复用还不够强
- 为什么仍然中优先级：
  - 这是“平台可运行”走向“助理能力更像产品”的关键差距之一
- 完成标准：
  - 检索质量明显提升
  - 命中解释更稳定
  - 前端能更清晰展示“为什么召回这条记忆”

### 7. 收口平台到产品的最后一段体验

- 当前状态：
  - Web 控制台能力已经很全
  - governance、monitor、session、memory、change request 已可操作
  - 设置页已直接展示运行版本、commit 指纹与分支信息
  - 任务起草与 Fast Path 已直接展示长期记忆召回原因与引用建议
  - 工作区已补 Hero、加载态、Agent 观察视图、Session 子页签和最终交付摘要呈现
  - 首页工作台已补全局状态条、待处理事项、最近交付和任务对话入口
- 仍然缺什么：
  - 当前 UI 已基本完成“工程控制台 -> 工作台”这一轮收口
  - 后续若继续演进，重点会转向更细的产品文案、视觉一致性和角色感知裁剪
- 为什么仍然中优先级：
  - 这决定了系统是“开发平台可用”还是“业务人员也更容易上手”
- 完成标准：
  - 页面信息层次更清晰
  - 关键结果、验收状态、下一步动作更易理解

### 8. 持续维护文档同步机制

- 当前状态：
  - README、runbook、release runbook、environment matrix、api/data model index 已经补齐
  - 本轮已同步更新：
    - `README.md`
    - `docs/README.md`
    - `docs/runbook.md`
    - `docs/release_runbook.md`
    - `docs/operations_runbook.md`
    - `docs/api_data_model_index.md`
- 仍然缺什么：
  - 历史路线图和当前状态文档仍需要继续随代码演进维护
- 为什么仍然中优先级：
  - 当前仓库迭代速度快，如果没有统一入口，后续很容易再次出现“代码已实现、文档仍写待办”
- 完成标准：
  - `docs/README.md` 作为文档总入口
  - 当前文档与 archive / validation 文档职责明确分开

## 推荐执行顺序

1. 继续拆分 `apps/api/main.py`
2. 继续拆分 `apps/worker/worker.py`
3. 前端静态控制台模块化拆分
4. 深化主链测试覆盖
5. 提升真实浏览器 E2E 的可执行性
6. 增强长期记忆检索质量
7. 收口平台到产品的最后一段体验
8. 持续维护文档同步机制

## 当前判断

仓库已经越过“缺基础设施、缺验证、缺文档”的阶段，下一阶段的主线不再是补空白，而是：

- 压缩超大文件带来的维护风险
- 提升关键主链的测试可信度
- 继续把平台能力收口成更稳定、更好用的产品能力
