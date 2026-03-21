# Engineering Optimization Plan

这份文档把当前项目最近一轮“稳定可用性 + 持续重构”的实际进展固定下来，并明确接下来的优化方向。

目标不是重新定义 Stage 5 / 6 / 7 的产品路线，而是补充一层更贴近工程落地的视角：

- 当前系统已经优化到了什么程度
- 哪些问题已经被真实修复
- 哪些技术债仍然存在
- 接下来应该按什么顺序继续推进

## 1. 当前工程基线

截至当前仓库状态，系统已经满足下面这条最低工程要求：

- API、Web、Worker、Scheduler 能稳定启动
- `healthcheck` 与 `web_console_check` 可重复通过
- 浏览器治理面板关键数据接口可直接访问
- `change_request / workflow_proposal / monitor` 相关主链已能被真实调用，而不是只在 smoke path 成立

最近一轮持续验证中，以下接口都已反复确认可用：

- `GET /change-requests?limit=5`
- `GET /change-requests/{id}`
- `GET /change-requests/{id}/shadow-validation`
- `GET /workflow-proposals/{id}/shadow-validation`
- `GET /tools`
- `GET /model-routes`
- `GET /model-providers`
- `GET /monitor/overview`

同时，下面两条校验脚本已作为每轮改动后的标准回归动作：

- `bash scripts/healthcheck.sh`
- `bash scripts/web_console_check.sh`

## 2. 最近已完成的优化

### 2.1 修复了读接口被 schema bootstrap / DDL 锁住的问题

之前项目存在一个真实可用性问题：

- 某些 GET 接口会在请求路径里触发表结构检查、`ALTER TABLE` 或 advisory lock
- 当多个请求叠加时，会出现数据库锁等待
- 外在表现是 `/tools`、`/model-routes`、`/model-providers`、`/change-requests`、`/monitor/overview` 等接口偶发超时或卡死

这一轮已经完成的止血和修复包括：

- 把治理类表的存在性判断改成轻量检查
- 避免在高频读路径上重复抢 schema advisory lock
- 避免在读接口里反复触发重型 DDL bootstrap
- 恢复关键浏览器接口的稳定可访问性

这部分工作的目标已经从“能跑”提升到“可持续访问”。

### 2.2 `change-requests` 列表已从大响应体改成可分页摘要

之前 `change-requests` 列表存在工程体验问题：

- 没有真正使用 `limit`
- 列表默认返回完整 payload
- 单次请求可能返回超大 JSON，影响浏览器和排障体验

当前已经完成：

- 增加真实分页参数：`limit / offset`
- 列表默认返回摘要版本
- 仅在 `include_payloads=true` 时返回完整 payload
- 列表响应体从约 `13.5MB` 降到约 `11.7KB`

这使得治理台与接口排障都更接近“生产可用”状态。

### 2.3 `apps/api/main.py` 的 `change_request` 链路已完成一轮模块化拆分

最近几轮优化不是简单修 bug，而是边修边重构。当前已经拆出的职责大致如下：

- `apps/api/governance_helpers.py`
  - 治理相关表 bootstrap / seed
- `apps/api/change_request_serializers.py`
  - change request 详情/列表序列化
  - payload 摘要
- `apps/api/change_request_business.py`
  - rollback draft
  - shadow validation 响应组装
  - shadow validation 状态计算
- `apps/api/change_request_store.py`
  - change request 读取辅助
  - shadow validation 查询链
  - shadow validation 同步更新链
- `apps/api/workflow_proposal_store.py`
  - workflow proposal 详情读取
  - proposal shadow validation 支持性判断
  - change request 触发 shadow validation 的前置资格判断
  - shadow task 创建与审计写入
- `apps/api/monitor_overview_store.py`
  - `monitor/overview` 的通用统计与最近记录读取
- `apps/api/monitor_stage_metrics_store.py`
  - Stage 5 / 6 的监控聚合与 readiness 原始指标
- `apps/api/monitor_stage7_store.py`
  - Stage 7 groundwork / sandbox / rollback 指标聚合

这意味着 `change_request` 相关逻辑已经不再完全堆在 `apps/api/main.py` 里。

### 2.4 `monitor/overview` 已完成第一轮按阶段拆分

之前 `GET /monitor/overview` 是一个很长的单体聚合函数，里面同时混着：

- session / review / approval / access / tool / model 统计
- Stage 5 聚合
- Stage 6 聚合
- Stage 7 groundwork / sandbox / rollback 聚合

当前已经完成的拆分是：

- 基础统计与 recent 列表 -> `monitor_overview_store.py`
- Stage 5 / 6 聚合 -> `monitor_stage_metrics_store.py`
- Stage 7 聚合 -> `monitor_stage7_store.py`

现在 `main.py` 中的 `get_monitor_overview()` 已更接近“上下文适配器 + readiness 组装器”，这让后续继续演化 Stage 5/6/7 指标时，回归影响面明显缩小。

### 2.5 `workflow_proposal / shadow_validation` 链路也已开始模块化

除了 `change_request` 线，这几轮还持续整理了 proposal / shadow validation 主链：

- workflow proposal 详情读取改走 `workflow_proposal_store.py`
- proposal shadow validation 状态查询已外移
- proposal / change_request 触发 shadow validation 的前置校验已抽为 helper
- shadow validation 的 baseline 准备、execution payload 组装、响应收尾逻辑已外移到 `change_request_business.py`
- shadow task 的创建与审计写入已收口到 `workflow_proposal_store.py`

当前这条链已经从“一个大函数串完全部逻辑”逐步转向：

- 前置校验
- baseline 准备
- execution payload 组装
- DB 写入
- 等待/异步收尾

### 2.6 `change_request` 路由已补齐异常路径下的事务收尾

最近还做了一类不那么显眼、但很关键的稳定性修复：

- 给 `change_request` 相关关键路由补上 `try/finally`
- 确保在 `HTTPException` 或其它异常分支下，游标和连接也能被正确关闭

这直接改善了之前偶发出现的短暂 `idle in transaction` 残留问题。  
当前回归里复查 `pg_stat_activity` 时，已经不再重复看到早前那类 `change_requests` 读取链上的事务尾巴。

### 2.7 现在的开发节奏已经切换为“先验证真可用，再继续重构”

当前默认工作方式已经固定为：

1. 做一小段局部优化
2. 编译或最小语法校验
3. 重启 API
4. 跑 `healthcheck` / `web_console_check`
5. 手工验证浏览器关键数据接口
6. 再继续下一段拆分

这条节奏本身就是项目优化的一部分，因为它避免了“代码看起来更干净，但系统其实不能用”的假进展。

## 3. 当前仍然存在的技术债

虽然系统现在已经恢复到稳定可用，但还不能把工程债务视为完成。

### 3.1 `apps/api/main.py` 仍然偏大

虽然 `change_request` 相关链路已经拆出一部分，但主文件仍然承担了过多职责：

- 路由定义
- schema bootstrap
- 部分 business orchestration
- 部分 DB 访问
- 部分 Stage 5 / 6 / 7 聚合逻辑

这会继续带来：

- 修改时心智负担高
- 回归影响面难以预测
- 新功能落点不清晰

不过它已经不再是“完全未拆”的状态。当前更准确的判断是：

- `monitor`
- `change_request`
- `workflow_proposal`
- `shadow_validation`

这四条主线都已经完成了一轮有效瘦身，剩下的是继续把局部 orchestrator 变薄，而不是从零开始拆。

### 3.2 shadow validation 主链仍有最后一层 orchestrator 可继续下沉

虽然最重的步骤已经拆出，但 `execute_workflow_proposal_shadow_validation(...)` 仍然保留一部分主流程级编排：

- baseline task 读取
- runtime override 生成
- helper 之间的数据拼装
- enqueue / await / async wait 的最后一层路由控制

这部分已经进入“可继续优化，但风险已明显下降”的阶段。

### 3.3 `create_change_request_row` 周边组合逻辑还没有完全拆干净

当前创建链路已经比之前清晰很多，但还可以继续推进：

- payload 归一化
- patch artifact 计算
- shadow validation state 计算
- insert 返回

它已经不是当前最急的可用性问题，但仍然是后续继续瘦 `main.py` 的一个自然目标。

### 3.4 读路径和 bootstrap 的边界虽然更安全了，但还值得继续收口

当前我们已经避免了明显的锁风暴，但从长期看仍建议：

- 继续减少请求期 schema 相关动作
- 尽量把 bootstrap 收口到启动期或显式初始化动作
- 把“运行期查询”和“结构修复动作”彻底分层

### 3.5 当前验证以脚本和接口 smoke 为主，缺少更细粒度的模块级测试

现在的回归验证已经足以保证“真可用”，但还偏向系统级检查。

后续如果继续深入重构，最好逐步补上：

- `change_request` 序列化/摘要的模块级测试
- shadow validation 状态计算的模块级测试
- 读路径 bootstrap 边界的专项回归测试

## 4. 后续优化规划

下面的规划按“收益 / 风险 / 依赖关系”排序，而不是按一次性大重写排序。

### 4.1 近期计划：继续清理 shadow validation 最后一层 orchestrator

优先级最高的下一步，已经不再是“大拆 monitor”，而是收最后几段高频主链：

- 继续简化 `execute_workflow_proposal_shadow_validation(...)`
- 进一步减少 helper 间的中间态拼装
- 保持 proposal -> shadow validate -> wait/async 的主链更稳定、更可读

预期结果：

- Stage 6 / Stage 7 的共享链路更清楚
- shadow validation 的维护成本继续下降
- 后续若扩展新的 validation mode，会更容易落点

### 4.2 近期计划：继续完成 `change_request` 创建链路拆分

优先级最高的下一步：

- 继续外移 `create_change_request_row` 周边组合逻辑
- 把 patch artifact / shadow state / insert 组装进一步模块化
- 继续减少 `apps/api/main.py` 中 `change_request` 相关的上下文噪音

预期结果：

- `main.py` 继续瘦身
- `change_request` 功能边界更稳定
- 后续 Stage 7 能更安全地继续迭代

### 4.3 近期计划：补一层更细的工程验证

建议在不打断当前主链的前提下，逐步增加：

- `change_request_serializers` 测试
- `change_request_business` 测试
- `change_request_store` 的关键查询/同步测试

预期结果：

- 后续拆分时不必完全依赖人工接口回归
- 能更快识别“逻辑对了但响应格式变了”一类问题

### 4.4 中期计划：继续拆分 `apps/api/main.py`

`change_request` 之后，适合继续整理的方向包括：

- workflow proposal 相关路由与聚合逻辑
- monitor 聚合与 readiness 统计逻辑
- Stage 5 / 6 / 7 的查询聚合辅助

目标不是拆成很多碎文件，而是让模块职责和演进边界更清楚。

### 4.5 中期计划：把“可用性回归”固定成正式工程约束

当前这条规则已经在实践中证明有效，建议正式化为项目约束：

- 每轮接口/治理/Stage 5-7 相关改动后
- 至少跑一次：
  - `bash scripts/healthcheck.sh`
  - `bash scripts/web_console_check.sh`
- 至少人工验证一次关键数据接口：
  - `/change-requests`
  - `/workflow-proposals/.../shadow-validation`
  - `/tools`
  - `/model-routes`
  - `/model-providers`
  - `/monitor/overview`

### 4.6 长期计划：让 Stage 7 从 groundwork completed 走向更完整的受控自修改

当前 Stage 7 的真实状态仍然是：

- groundwork 已完成
- 阶段整体尚未完成

后续长期方向依然包括：

- sandbox / branch / code patch 自动化
- 更明确的 acceptance / rollback 编排
- 更完整的 proposal -> change request -> validate -> apply -> rollback 自动闭环

这些属于产品/平台层升级，不应与当前工程可用性修复混在一轮里推进。

## 5. 当前建议的工作原则

在当前仓库阶段，最适合继续沿用的原则是：

- 优先保证真实可用，而不是只追求代码拆分数量
- 每次只做一小段可验证重构
- 先修复根因，再做表面清理
- 文档、脚本、接口口径保持一致
- 对 Stage 7 保持“groundwork 已完成，但全阶段未完成”的边界清晰表达

## 6. 与其它文档的关系

这份文档主要回答“工程优化做到哪、接下来先做什么”。

如果要看更高层的阶段路线，请结合：

- [docs/personal_ai_os_roadmap.md](/opt/ai-assistant/docs/personal_ai_os_roadmap.md)

如果要看实际运行与回归方式，请结合：

- [docs/runbook.md](/opt/ai-assistant/docs/runbook.md)

如果要看 Stage 5 / 6 / 7 的 readiness / closure 边界，请结合：

- [docs/stage5_stage6_readiness_checklist.md](/opt/ai-assistant/docs/stage5_stage6_readiness_checklist.md)
- [docs/stage5_stage6_closure_checklist.md](/opt/ai-assistant/docs/stage5_stage6_closure_checklist.md)
- [docs/stage7_groundwork_readiness_checklist.md](/opt/ai-assistant/docs/stage7_groundwork_readiness_checklist.md)
- [docs/stage7_groundwork_closure_checklist.md](/opt/ai-assistant/docs/stage7_groundwork_closure_checklist.md)
