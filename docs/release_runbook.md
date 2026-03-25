# 发布与回滚手册

## 目标

把当前仓库从“本地能跑”收口到“可重复发布、可重复回滚、可重复验证”。

## 发布前准备

1. 检查仓库状态

```bash
git status --short
```

2. 执行日常检查入口

```bash
bash scripts/daily_checks.sh
```

3. 如需更厚的回归，再执行回归检查入口

```bash
RUN_E2E=1 bash scripts/regression_checks.sh
```

4. 验证 compose 配置

```bash
docker compose -f infra/compose/docker-compose.yml config -q
docker compose -f infra/compose/docker-compose.yml -f infra/compose/docker-compose.validation.yml config -q
```

5. 一键跑发布就绪检查

```bash
bash scripts/release_readiness_check.sh
```

如果要在本机顺带拉起服务、跑回归并执行验证脚本：

```bash
RUN_REGRESSION_CHECKS=1 RUN_RELEASE_SERVICES=1 RUN_VALIDATION_SCRIPTS=1 bash scripts/release_readiness_check.sh
```

## 标准发布流程

1. 准备环境变量
   - 本地验证：复制 `env.sample.local`
   - 验收/CI：复制 `env.sample.validation`
   - 正式部署：以 `env.sample.production` 为模板，由 secrets 平台注入真实密钥

2. 构建与启动

```bash
docker compose -f infra/compose/docker-compose.yml up -d --build
```

如果是复用已有本地 Postgres 数据卷，且 API 在启动时出现 `password authentication failed for user "assistant"`，先对齐本地库里的角色密码，再继续：

```bash
bash scripts/repair_local_postgres_auth.sh
docker compose -f infra/compose/docker-compose.yml restart api worker scheduler
```

3. 执行迁移

```bash
python3 scripts/run_migrations.py
```

说明：

- `run_migrations.py` 现在同时负责显式创建 `long_term_memories`，不再依赖首次检索时隐式补表。
- `runtime_version_check.sh` 会把运行中的 `/runtime-metadata` 与当前仓库 `version.json` / git commit 做对比，帮助及时发现“容器不是这版代码”。
- 发布后可通过 `GET /runtime-metadata` 或 `GET /monitor/overview` 中的 `runtime_metadata.version` 核对当前运行版本、commit 指纹与分支信息，避免容器运行版本与本地代码不一致。

4. 发布后检查

```bash
bash scripts/runtime_version_check.sh
bash scripts/healthcheck.sh
bash scripts/acceptance_check.sh
bash scripts/governance_check.sh
bash scripts/session_memory_check.sh
bash scripts/approval_retry_check.sh
bash scripts/claim_lease_check.sh
bash scripts/daily_review_check.sh
```

5. 浏览器回归

```bash
npm ci
npx playwright install --with-deps chromium
npm run test:e2e
```

本地回归说明：

- 如果只是前端脚本改动，先执行 `npm run check:web` 或 `bash scripts/daily_checks.sh`。
- 如果本地 Chromium 起不来，先执行 `bash scripts/playwright_local_check.sh` 看缺失的是浏览器本体还是系统共享库。
- Playwright 失败后会在 `playwright-report/` 和 `test-results/` 下留下 HTML 报告、trace、截图与视频。
- 开发机第一次执行缺依赖时，优先使用 `npx playwright install --with-deps chromium` 与 CI 保持同一入口。

## 回滚流程

1. 先确认是否只是配置问题
   - 优先检查 `.env` / provider / route / quota / risk policy。

2. 如果是变更单引起的问题
   - 优先走 `change request rollback`，保留审计链。

3. 如果是应用发布回滚

```bash
docker compose -f infra/compose/docker-compose.yml down
docker compose -f infra/compose/docker-compose.yml up -d --build
```

4. 如果迁移已经执行
   - 先确认 `scripts/run_migrations.py` 对应版本。
   - 数据回滚必须和业务 owner 一起执行，不能只回应用镜像。

## 发布记录要求

- 所有破坏性改动记录到 `CHANGELOG.md`
- 所有环境变量新增项同步到环境模板与 README
- 所有控制面高风险改动写清影响范围、验证方式、回滚入口
