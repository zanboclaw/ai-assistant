# Release Checklist

上传 GitHub 或准备发布前，建议至少过一遍这份清单。

## 仓库卫生

- [ ] `git status` 只包含预期改动
- [ ] `.env` 没有被追踪
- [ ] `logs/`、`backups/`、`data/` 运行产物没有被追踪
- [ ] 没有遗留 `.bak`、`__pycache__`、`.pyc`、临时草稿文件
- [ ] `.env.example` 是可用模板，但不含真实密钥

## 文档

- [ ] `README.md` 与当前实现一致
- [ ] `docs/runbook.md` 与关键脚本和入口一致
- [ ] `docs/release_runbook.md` 与当前发布流程一致
- [ ] `docs/operations_runbook.md` 与当前巡检 / 排障动作一致
- [ ] `docs/environment_matrix.md` 与环境模板一致
- [ ] 新增的重要设计文档已挂到 README 或 runbook
- [ ] 已明确仓库授权策略

## 验证

- [ ] `bash scripts/healthcheck.sh`
- [ ] `bash scripts/acceptance_check.sh`
- [ ] `bash scripts/governance_check.sh`
- [ ] `bash scripts/session_memory_check.sh`
- [ ] `bash scripts/approval_retry_check.sh`
- [ ] `bash scripts/claim_lease_check.sh`
- [ ] `bash scripts/daily_review_check.sh`
- [ ] `bash scripts/release_readiness_check.sh`
- [ ] `npm run test:e2e`
- [ ] 如果复用本地 Postgres 数据卷，已确认当前 `POSTGRES_PASSWORD` 与已有卷内角色密码一致；必要时执行 `bash scripts/repair_local_postgres_auth.sh`

## 安全

- [ ] 根目录和文档里没有真实密钥
- [ ] `.env.example`、`docker-compose.yml`、应用默认连接配置之间没有硬编码凭据漂移
- [ ] 所有控制面接口都已接入 actor 权限校验，读接口至少要求 `read`
- [ ] 变更说明中写清楚高风险控制面影响
- [ ] 审计、审批、配额和 change request 相关改动有最小验证说明

## GitHub 发布前最后检查

- [ ] 已确认是否添加 `LICENSE`
- [ ] 已确认是否需要 `CHANGELOG`
- [ ] 已确认默认分支和仓库可见性设置
- [ ] 已确认 issue / PR 协作方式
