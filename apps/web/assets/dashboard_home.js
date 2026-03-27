(function attachDashboardHome(global) {
  function renderGlobalStatusBar(ctx) {
    const container = document.getElementById("globalStatusBar");
    if (!container) {
      return;
    }
    const running = ctx.allTasks.filter((item) => item.status === "running").length;
    const waitingClarification = ctx.allTasks.filter((item) => item.status === "waiting_clarification").length;
    const waitingApproval = ctx.allTasks.filter((item) => item.status === "waiting_approval").length;
    const failed = ctx.allTasks.filter((item) => item.status === "failed").length;
    const actionCount = ctx.allTasks.filter((item) => ctx.getTaskActionCategory(item) === "attention").length;
    const plannerRoute = ctx.modelRoutes.find((item) => item.route_name === "planner") || {};
    container.innerHTML = `
      <div class="status-chip status-chip-connection">
        <div class="status-chip-label">API</div>
        <div class="status-chip-value">${ctx.escapeHtml(ctx.monitorOverview ? "已连接" : "待验证")}</div>
        <div class="status-chip-meta">${ctx.escapeHtml(ctx.API_BASE)}</div>
      </div>
      <div class="status-chip">
        <div class="status-chip-label">Actor</div>
        <div class="status-chip-value">${ctx.escapeHtml(ctx.currentActorName)}</div>
        <div class="status-chip-meta">${ctx.escapeHtml(ctx.getActorRole(ctx.currentActorName))}</div>
      </div>
      <div class="status-chip">
        <div class="status-chip-label">Planner</div>
        <div class="status-chip-value">${ctx.escapeHtml(plannerRoute.provider || "-")}</div>
        <div class="status-chip-meta">${ctx.escapeHtml(plannerRoute.model_name || "-")}</div>
      </div>
      <div class="status-chip">
        <div class="status-chip-label">待处理</div>
        <div class="status-chip-value">${actionCount}</div>
        <div class="status-chip-meta">待澄清 / 审批 / 恢复</div>
      </div>
      <div class="status-chip">
        <div class="status-chip-label">运行中</div>
        <div class="status-chip-value">${running}</div>
        <div class="status-chip-meta">澄清 ${waitingClarification} / 审批 ${waitingApproval} / 失败 ${failed}</div>
      </div>
      <div class="status-chip">
        <div class="status-chip-label">自动刷新</div>
        <div class="status-chip-value">${ctx.frontendPrefs.autoRefresh ? "开启" : "关闭"}</div>
        <div class="status-chip-meta">${ctx.escapeHtml(String(ctx.frontendPrefs.refreshIntervalSeconds || 15))}s</div>
      </div>
    `;
  }

  function renderHomeOverview(ctx) {
    const heroEl = document.getElementById("homeHeroMetrics");
    const actionEl = document.getElementById("homeActionCenter");
    const pendingEl = document.getElementById("homePendingList");
    const deliverableEl = document.getElementById("homeRecentDeliverables");
    if (!heroEl || !actionEl || !pendingEl || !deliverableEl) {
      return;
    }

    const runningTasks = ctx.allTasks.filter((item) => item.status === "running");
    const attentionTasks = ctx.allTasks.filter((item) => ctx.getTaskActionCategory(item) === "attention");
    const completedTasks = ctx.allTasks.filter((item) => item.status === "completed");
    const latestTask = ctx.allTasks[0] || null;

    heroEl.innerHTML = `
      <div class="hero-metric-card">
        <div class="hero-metric-label">当前待处理</div>
        <div class="hero-metric-value">${attentionTasks.length}</div>
        <div class="hero-metric-meta">优先处理待澄清、审批和恢复任务</div>
      </div>
      <div class="hero-metric-card">
        <div class="hero-metric-label">运行中任务</div>
        <div class="hero-metric-value">${runningTasks.length}</div>
        <div class="hero-metric-meta">建议进入工作区查看当前步骤</div>
      </div>
      <div class="hero-metric-card">
        <div class="hero-metric-label">最近任务</div>
        <div class="hero-metric-value">${latestTask ? `#${latestTask.id}` : "-"}</div>
        <div class="hero-metric-meta">${ctx.escapeHtml(latestTask ? ctx.summarizeTaskStatus(latestTask) : "暂无任务")}</div>
      </div>
      <div class="hero-metric-card">
        <div class="hero-metric-label">环境状态</div>
        <div class="hero-metric-value">${ctx.monitorOverview ? "健康" : "待检测"}</div>
        <div class="hero-metric-meta">${ctx.escapeHtml(ctx.monitorOverview?.generated_at ? ctx.formatDateTime(ctx.monitorOverview.generated_at) : "点击设置页可测试")}</div>
      </div>
    `;

    const nextActions = [];
    if (!ctx.allTasks.length) {
      nextActions.push("先输入一个任务并生成系统理解卡片。");
    }
    if (attentionTasks.length) {
      nextActions.push(`有 ${attentionTasks.length} 个任务需要人工处理，建议先打开最急任务。`);
    }
    if (runningTasks.length) {
      nextActions.push(`有 ${runningTasks.length} 个任务正在运行，建议持续观察当前步骤和输出。`);
    }
    if (!ctx.monitorOverview) {
      nextActions.push("监控概览尚未同步，建议到设置页测试 API 连通性。");
    }
    actionEl.innerHTML = `
      <div class="action-center-header">
        <div>
          <div class="panel-title">下一步动作</div>
          <div class="panel-subtitle">系统根据当前任务和运行态，推荐最值得优先处理的动作。</div>
        </div>
        <div class="top-actions">
          ${attentionTasks[0] ? `<button onclick="selectTask(${attentionTasks[0].id}, { focusWorkspace: true })">打开最急任务</button>` : `<button onclick="setAppTab('tasks')">查看任务</button>`}
          <button class="ghost-btn" onclick="setAppTab('${ctx.actorHasPermission(ctx.currentActorName, "operate") ? "monitor" : "settings"}')">${ctx.actorHasPermission(ctx.currentActorName, "operate") ? "查看监控" : "查看设置"}</button>
        </div>
      </div>
      <div class="action-recommendations">
        ${(nextActions.length ? nextActions : ["当前没有明显阻塞，可以继续创建新任务或回看最近交付。"])
          .map((text) => `<div class="action-recommendation">${ctx.escapeHtml(text)}</div>`).join("")}
      </div>
    `;

    pendingEl.innerHTML = attentionTasks.length
      ? attentionTasks.slice(0, 5).map((task) => `
        <button type="button" class="pending-item pending-${ctx.getTaskAttentionLevel(task)}" onclick="selectTask(${task.id}, { focusWorkspace: true })">
          <div class="pending-item-title">#${task.id} ${ctx.escapeHtml(task.display_user_input || task.user_input || "未命名任务")}</div>
          <div class="pending-item-meta">${ctx.escapeHtml(ctx.describeNextAction(task, task.validation_report || {}, task.recovery_action || {}))}</div>
        </button>
      `).join("")
      : `<div class="empty">当前没有待澄清、待审批或待恢复任务。</div>`;

    deliverableEl.innerHTML = completedTasks.length
      ? completedTasks.slice(0, 3).map((task) => `
        <button type="button" class="deliverable-item" onclick="selectTask(${task.id}, { focusWorkspace: true })">
          <div class="deliverable-item-title">#${task.id} ${ctx.escapeHtml(task.display_user_input || task.user_input || "")}</div>
          <div class="deliverable-item-meta">${ctx.escapeHtml((task.result || "").slice(0, 120) || "已完成但暂无可见交付")}</div>
        </button>
      `).join("")
      : `<div class="empty">暂无最近交付。</div>`;
  }

  global.DashboardHome = {
    renderGlobalStatusBar,
    renderHomeOverview,
  };
})(window);
