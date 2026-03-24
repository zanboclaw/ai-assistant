# Changelog

## 2026-03-24

### Added

- Playwright 浏览器级 E2E 基建，包含：
  - `playwright.config.js`
  - `tests/e2e/dashboard.spec.js`
  - `tests/e2e/mock_api_server.py`
- GitHub Actions CI：
  - Python 编译检查
  - 前端脚本语法检查
  - pytest + coverage
  - Playwright E2E
  - Docker build
- 发布与运维文档：
  - `docs/release_runbook.md`
  - `docs/operations_runbook.md`
  - `docs/environment_matrix.md`
  - `docs/api_data_model_index.md`
- 多环境模板：
  - `env.sample.local`
  - `env.sample.validation`
  - `env.sample.production`
- `fast_path` 轻量回答接口：
  - `POST /chat/fast-path`

### Changed

- 拆分 `apps/api/main.py`：
  - intake / task create / task list / memory search / fast_path 移到 `apps/api/intake_task_routes.py`
- 拆分 `apps/worker/worker.py`：
  - 任务载荷解析移到 `apps/worker/task_payloads.py`
  - 计划选择与执行编排移到 `apps/worker/task_execution_runtime.py`
- 长期记忆检索增强：
  - 返回 `matched_keywords`
  - 返回 `match_explanation`
  - 返回 `citation_hint`
- 前端任务台补长期记忆检索、fast_path 轻量回答、更多解释型状态文案
- API / Worker 默认日志与运行目录改为对本地开发友好的仓库内路径回退

### Quality

- 新增 API 路由级集成测试
- 引入 `pytest-cov`
