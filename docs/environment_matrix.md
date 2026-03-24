# 多环境配置矩阵

## 环境分层

### Local

- 目标：开发、单机调试、API/Worker/Web 联调
- 模板：`env.sample.local`
- 特点：
  - 允许使用本地端口映射
  - 默认日志、checkpoints、artifacts 都写入仓库内 `logs/` 和 `data/`

### Validation

- 目标：CI、验收、回归、影子验证
- 模板：`env.sample.validation`
- 特点：
  - 尽量使用确定性配置
  - 可以关闭外部 provider，优先走 mock / fallback / deterministic route

### Production

- 目标：正式部署
- 模板：`env.sample.production`
- 特点：
  - 真实密钥不进入仓库
  - 通过 secrets 平台注入 provider key、数据库凭据、Redis 凭据
  - 默认开启审计、治理门禁、发布记录要求

## 关键环境变量

### 基础设施

- `POSTGRES_HOST`
- `POSTGRES_PORT`
- `POSTGRES_DB`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `REDIS_URL`

### 运行目录

- `LOG_DIR`
- `CHECKPOINT_DIR`
- `ARTIFACT_DIR`
- `WORKSPACE_DIR`
- `WORKSPACE_ROOT`

说明：

- 非容器本地运行时，API/Worker 默认回退到仓库内 `logs/`、`data/checkpoints/`、`data/artifacts/`、`data/workspace/`
- 容器运行时继续由 compose 明确注入挂载路径

### 模型与检索

- `DEEPSEEK_API_KEY`
- `DEEPSEEK_BASE_URL`
- `DEEPSEEK_MODEL`
- `TAVILY_API_KEY`

### 调度与治理

- `AUTO_STAGE5_POSTRUN_ENABLED`
- `CHANGE_GATE_ENFORCED_TARGET_TYPES`
- `DAILY_REVIEW_INTERVAL_SECONDS`
- `DAILY_REVIEW_STARTUP_DELAY_SECONDS`
- `DAILY_REVIEW_SESSION_LIMIT`
- `DAILY_REVIEW_ACTIVE_WITHIN_HOURS`

## Secrets 注入策略

- 本地：
  - 使用 `.env`
  - 仅供个人开发，禁止提交
- CI / Validation：
  - 使用 GitHub Actions secrets 或 runner 环境变量
  - 尽量避免依赖真实外部 provider
- Production：
  - 使用部署平台或 secret manager
  - 不允许把密钥硬编码在 compose、README、脚本默认值中

## 推荐做法

- 每次新增环境变量时同步更新：
  - `.env.example`
  - `env.sample.local`
  - `env.sample.validation`
  - `env.sample.production`
  - `README.md`
  - `docs/release_runbook.md`
