# Contributing

这个仓库当前仍在快速演进，提交变更时请优先保证：

- 不破坏 `api + worker + web + scheduler` 的现有主链
- 不把本地日志、备份、运行产物或密钥提交进仓库
- 所有高风险控制面改动都能说明影响范围和验证方式

## 开发前

1. 从最新主分支开始工作。
2. 检查本地 `.env`，不要提交任何真实密钥。
3. 确认 `git status` 干净，或至少清楚哪些改动是本次任务的一部分。

## 提交建议

- 一个提交尽量只做一类事情：
  - 功能
  - 修复
  - 文档
  - 仓库卫生
- 提交说明优先写清楚“改了什么、为什么改、怎么验证”。

## 代码与脚本

- Python 使用 4 空格缩进。
- Shell 脚本默认使用 LF 换行。
- 优先保留现有运行模型，不要随意改动 runtime 主协议。
- 新增脚本时，尽量提供可重复执行的验收方式。

## 验证

按改动范围至少运行相关检查：

- `bash scripts/healthcheck.sh`
- `bash scripts/acceptance_check.sh`
- `bash scripts/governance_check.sh`
- `bash scripts/session_memory_check.sh`
- `bash scripts/approval_retry_check.sh`
- `bash scripts/claim_lease_check.sh`
- `bash scripts/daily_review_check.sh`

如果当前环境不适合执行全部检查，请在提交说明里明确写出未执行项和原因。

## Pull Request 建议

PR 描述建议包含：

- 背景
- 变更范围
- 风险点
- 验证方式
- 是否涉及治理控制面、会话记忆或执行引擎主链

## 不要提交的内容

- `.env`
- `logs/`
- `backups/`
- `data/` 下的运行产物
- 临时 `.bak_*` 文件
- 本地 IDE 配置和缓存
