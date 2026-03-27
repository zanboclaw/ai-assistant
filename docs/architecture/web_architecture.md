# Web Architecture

前端已新增：

- `js/app`: `bootstrap/router/state/api_client/event_bus`
- `js/domains`: composer/workspace/sessions/governance/monitor/settings
- `js/components`
- `js/shared`
- `assets/styles`

当前仍保留 `assets/dashboard*.js` 作为兼容运行层，但跨域壳层与首页概览已经继续拆出，旧主脚本主要承担上下文拼装与兼容桥接，确保原页面可继续运行。

## 当前已落地的主链

- `apps/web/js/app/state.js`
  - 已开始承载域状态注册，不再只保存全局 tab / actor。
- `apps/web/js/domains/composer/composer_api.js`
  - 已沉淀 `intake/confirm/fast-path/tasks/memories` 相关调用入口。
- `apps/web/js/domains/composer/composer_state.js`
  - 已沉淀当前任务对话与草稿快照状态。
- `apps/web/js/domains/composer/composer_page.js`
  - 已把 composer 域正式注册为可复用页面能力，而不只是空 mount。
- `apps/web/js/domains/workspace/workspace_api.js`
  - 已沉淀 task / steps / checkpoint / interrupt / resume / recovery 相关调用入口。
- `apps/web/js/domains/workspace/workspace_state.js`
  - 已沉淀 selected task 与 workspace tab 状态。
- `apps/web/js/domains/workspace/workspace_page.js`
  - 已把 workspace 域正式注册为可复用页面能力。
- `apps/web/assets/dashboard_shell.js`
  - 已拆出全局 toast、tab 壳层、actor 权限可见性与自动刷新循环，不再继续堆在 `dashboard.js` 顶层。
- `apps/web/assets/dashboard_home.js`
  - 已拆出首页概览与全局状态栏渲染，把“工作台”首页作为独立壳层能力沉淀。

## 当前仍保留的兼容边界

- `apps/web/assets/dashboard.js`
  - 仍承载部分跨域 orchestration、上下文拼装与全局函数桥接，但首页/壳层主逻辑已迁出。
- `apps/web/assets/dashboard_composer.js`
  - 任务起草器渲染与交互主体仍在旧兼容层。
- `apps/web/assets/dashboard_workspace.js`
  - 工作区渲染与任务控制主体仍在旧兼容层。
