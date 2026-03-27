# ADR 0003: Policy Layer

权限、额度和风险判断统一下沉到 `apps/api/policy` 与 `apps/worker/policy`，减少路由层和运行时的重复判断。

