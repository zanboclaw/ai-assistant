# System Context

AI Assistant 当前被定义为“任务工作台 + 治理控制台 + 运行监控台”的组合平台，而不是单一聊天界面。

- API 负责输入、任务控制、治理与查询入口。
- Worker 负责任务运行时状态机、工具调用、恢复与交付。
- Web 负责多域工作台呈现。
- Scheduler 负责日常 review / 巡检调度。

