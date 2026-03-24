# 当前执行待办

更新时间：`2026-03-24`

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
- 协作、安全、版本记录已经具备基础文件：
  - `CHANGELOG.md`
  - `CONTRIBUTING.md`
  - `SECURITY.md`

## 当前仍然值得继续推进的事项

### 1. 继续拆分 `apps/api/main.py`

- 当前状态：
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
- 仍然缺什么：
  - `main.py` 里仍有大量共享 helper 与装配代码，还没继续按 helper/runtime 维度下沉
  - 仍在 `apps/api/main.py`
- 为什么仍然高优先级：
  - API 入口仍然过大，后续每次改任务链、会话链、治理链都容易互相影响
- 完成标准：
  - `main.py` 只保留应用装配、依赖注入、路由挂载
  - 主要业务路由按领域拆到独立模块

### 2. 继续拆分 `apps/worker/worker.py`

- 当前状态：
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
  - task/step/model/skill trace 上下文与写入逻辑已拆到 `apps/worker/trace_runtime.py`
  - session memory 推断、session state rebuild、任务完成后的 memory capture 已拆到 `apps/worker/memory_runtime.py`
  - web_search / http_request / MCP tool / execute_tool 分发链已拆到 `apps/worker/tool_runtime.py`
  - specialist agent run 的只读执行与结果产物写入已拆到 `apps/worker/agent_run_runtime.py`
  - task/agent queue、claim、stale requeue 与 task fetch helper 已拆到 `apps/worker/queue_runtime.py`
- 仍然缺什么：
  - worker 主循环中仍混有计划、恢复、记忆与部分 tool 细节
  - 共享 helper 仍较多，`worker.py` 还没有完全退化为“主循环 + 装配层”
- 为什么仍然高优先级：
  - 这是当前执行面的主要维护瓶颈，也是后续补测试最难的地方
- 完成标准：
  - `worker.py` 只保留主循环与装配
  - 计划、恢复、记忆、agent runtime、tool execution 能被独立测试

### 3. 深化主链测试覆盖

- 当前状态：
  - `pytest -q` 可运行
  - CI 已接入 `pytest`
  - 前端已有 Playwright E2E
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
- 仍然缺什么：
  - 深层治理链、worker 主链、clarify / recovery / change request / rollback 的系统化测试仍不够厚
  - 覆盖率虽然接入，但关键主链的断言密度仍有继续补强空间
- 为什么仍然高优先级：
  - 现在仓库已经不是原型规模，仅靠 smoke 和局部规则测试不足以承接继续重构
- 完成标准：
  - 为 task 主链、session 主链、governance 主链补更完整的 API / runtime 集成测试
  - 对关键失败恢复路径建立可重复断言

### 4. 提升真实浏览器 E2E 的可执行性

- 当前状态：
  - Playwright 测试代码、mock API 与 CI 步骤都已存在
- 仍然缺什么：
  - 本地真实执行仍依赖 Chromium 系统依赖和 Playwright 安装环境
  - 当前更偏“可在 CI 跑通”，对开发机环境还不够友好
- 为什么仍然中高优先级：
  - 前端回归已经具备框架，但还需要进一步降低团队真实使用成本
- 完成标准：
  - 本地和 CI 都能按统一命令稳定执行
  - 失败日志、截图、报告入口足够清晰

### 5. 增强长期记忆检索质量

- 当前状态：
  - `core/long_term_memory.py` 已支持关键词标准化、命中解释和引用提示
  - `/memories/search` 已可直接检索并回传解释字段
- 仍然缺什么：
  - 目前仍以关键词检索为主
  - memory scope、排序质量、跨任务经验复用还不够强
- 为什么仍然中优先级：
  - 这是“平台可运行”走向“助理能力更像产品”的关键差距之一
- 完成标准：
  - 检索质量明显提升
  - 命中解释更稳定
  - 前端能更清晰展示“为什么召回这条记忆”

### 6. 收口平台到产品的最后一段体验

- 当前状态：
  - Web 控制台能力已经很全
  - governance、monitor、session、memory、change request 已可操作
- 仍然缺什么：
  - 任务详情空态、错误态、加载态与解释性文案仍有提升空间
  - 当前 UI 更像工程控制台，而不是更成熟的产品界面
- 为什么仍然中优先级：
  - 这决定了系统是“开发平台可用”还是“业务人员也更容易上手”
- 完成标准：
  - 页面信息层次更清晰
  - 关键结果、验收状态、下一步动作更易理解

### 7. 持续维护文档同步机制

- 当前状态：
  - README、runbook、release runbook、environment matrix、api/data model index 已经补齐
- 仍然缺什么：
  - 历史路线图和当前状态文档容易再次漂移
- 为什么仍然中优先级：
  - 当前仓库迭代速度快，如果没有统一入口，后续很容易再次出现“代码已实现、文档仍写待办”
- 完成标准：
  - `docs/README.md` 作为文档总入口
  - 当前文档与 archive / validation 文档职责明确分开

## 推荐执行顺序

1. 继续拆分 `apps/api/main.py`
2. 继续拆分 `apps/worker/worker.py`
3. 深化主链测试覆盖
4. 提升真实浏览器 E2E 的可执行性
5. 增强长期记忆检索质量
6. 收口平台到产品的最后一段体验
7. 持续维护文档同步机制

## 当前判断

仓库已经越过“缺基础设施、缺验证、缺文档”的阶段，下一阶段的主线不再是补空白，而是：

- 压缩超大文件带来的维护风险
- 提升关键主链的测试可信度
- 继续把平台能力收口成更稳定、更好用的产品能力
