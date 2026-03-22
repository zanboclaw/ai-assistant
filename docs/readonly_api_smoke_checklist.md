# Readonly API Smoke Checklist

这份清单用于固定当前仓库里最值得人工抽检的只读接口。

它解决的问题是：

- 大脚本通过了，但高频读接口可能已经退化
- 重构后只验证了写路径，没有验证浏览器真正依赖的读路径
- `monitor/overview`、治理接口、proposal / change request 详情仍主要靠人工经验抽检

这份清单不替代脚本，而是补足当前脚本之间的空档。

## 适用时机

建议在下面这些情况下至少跑一轮：

- 改了 `apps/api/main.py`
- 改了 `change_request` / `workflow_proposal` / `monitor` 相关 helper/store
- 改了 schema/bootstrap、连接关闭、事务收尾逻辑
- 改了治理类查询接口
- 做完脚本回归后，需要再确认浏览器依赖的数据接口是真可用

## 最小抽检清单

### 治理与高频只读接口

- `GET /change-requests?limit=5`
- `GET /change-requests/{id}`
- `GET /workflow-proposals?limit=5`
- `GET /workflow-proposals/{id}`
- `GET /workflow-proposals/{id}/shadow-validation`
- `GET /tools`
- `GET /model-routes`
- `GET /model-providers`
- `GET /monitor/overview`

### 建议补充接口

- `GET /change-requests/{id}/shadow-validation`
- `GET /change-requests/{id}/rollback-draft`
- `GET /workflow-proposals/{id}/change-request-draft`
- `GET /tasks/{id}/steps`

## 抽检方式

建议至少检查下面四件事：

- 是否在可接受时间内返回
- 是否返回合法 JSON
- 是否包含预期关键字段
- 是否没有明显异常放大响应体

## 建议命令模板

```bash
for path in \
  '/change-requests?limit=5' \
  '/change-requests/420' \
  '/workflow-proposals?limit=5' \
  '/workflow-proposals/985' \
  '/workflow-proposals/985/shadow-validation' \
  '/tools' \
  '/model-routes' \
  '/model-providers' \
  '/monitor/overview'
do
  echo "=== $path ==="
  curl -sS --max-time 15 "http://localhost:8000$path" >/tmp/endpoint.out
  wc -c /tmp/endpoint.out
  head -c 320 /tmp/endpoint.out
  echo
  echo
done
```

## 判定标准

当前仓库阶段，最小通过标准建议是：

- 所有接口都能返回
- 没有明显超时
- `monitor/overview` 返回结构稳定
- `change-requests` 列表仍保持摘要化，不回到超大响应体
- `workflow-proposals/{id}/shadow-validation` 与 `change-requests/{id}/shadow-validation` 可读

## 数据库尾检

只读接口 smoke 结束后，建议补一轮数据库健康尾检：

```bash
docker exec ai-postgres psql -U assistant -d assistant -c \
  "select pid, state, wait_event_type, wait_event, now()-query_start as age, left(query,140) as query
   from pg_stat_activity
   where datname='assistant' and state <> 'idle'
   order by query_start asc
   limit 10;"
```

当前重点关注：

- 是否出现新的 `idle in transaction`
- 是否出现锁等待
- 是否出现高频读接口带出的长事务

## 与其它文档的关系

- 回归基线与发布纪律见 `docs/runbook.md`
- 工程证据记录模板见 `docs/validation/engineering_evidence_log.md`
- Stage 7 口径边界见：
  - `docs/validation/stage7_groundwork_readiness_checklist.md`
  - `docs/validation/stage7_groundwork_closure_checklist.md`
