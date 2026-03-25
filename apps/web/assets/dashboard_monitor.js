(function () {
  function renderMonitorOverview(ctx) {
    const container = document.getElementById("monitorOverview");
    if (!ctx.monitorOverview) {
      container.innerHTML = `<div class="empty">暂无监控数据</div>`;
      return;
    }

    const {
      escapeHtml,
      formatRatio,
      monitorOverview,
      taskAgentSummaries,
    } = ctx;
    const taskMetrics = monitorOverview.task_metrics || {};
    const approvalMetrics = monitorOverview.approval_metrics || {};
    const queueMetrics = monitorOverview.queue_metrics || {};
    const riskMetrics = monitorOverview.risk_metrics || {};
    const toolMetrics = monitorOverview.tool_metrics || {};
    const modelMetrics = monitorOverview.model_metrics || {};
    const agentMetrics = monitorOverview.agent_metrics || {};
    const changeMetrics = monitorOverview.change_metrics || {};
    const accessMetrics = monitorOverview.access_metrics || {};
    const reviewMetrics = monitorOverview.review_metrics || {};
    const runtimeMetadata = monitorOverview.runtime_metadata || {};
    const readinessMetrics = monitorOverview.readiness_metrics || {};
    const stage3Readiness = readinessMetrics.stage3 || {};
    const stage4Readiness = readinessMetrics.stage4 || {};
    const stage5Readiness = readinessMetrics.stage5 || {};
    const stage6Readiness = readinessMetrics.stage6 || {};
    const stage7Readiness = readinessMetrics.stage7 || {};
    const sessionMetrics = monitorOverview.session_metrics || {};
    const tasksByStatus = taskMetrics.tasks_by_status || {};
    const recentTasks = monitorOverview.recent_tasks || [];
    const recentAgentRuns = monitorOverview.recent_agent_runs || [];
    const evaluatorMetrics = monitorOverview.evaluator_metrics || {};
    const recentEvaluatorRuns = monitorOverview.recent_evaluator_runs || [];
    const recentReviews = monitorOverview.recent_reviews || [];
    const recentAuditLogs = monitorOverview.recent_audit_logs || [];
    const stage5SummaryValues = Array.from(taskAgentSummaries.values());
    const stage5ExecuteCount = stage5SummaryValues.filter((item) => item.recommended_action === "execute").length;
    const stage5FinalizeCount = stage5SummaryValues.filter(
      (item) => item.recommended_action === "finalize" || item.recommended_action === "finalize_retry"
    ).length;
    const stage5RetryCount = stage5SummaryValues.filter((item) => item.recommended_action === "rerun_specialists").length;
    const stage5EscalationCount = stage5SummaryValues.filter((item) => item.recommended_action === "escalate_operator").length;
    const stage5MainlineCount = stage5SummaryValues.filter((item) => item.implementation_status === "task_runtime_postrun_v1").length;
    const stage5PostrunEvaluatorCount = stage5SummaryValues.filter((item) => (item.latest_evaluator || {}).source === "task_runtime_postrun_v1").length;
    const stage5WorkflowProposalVisibleCount = stage5SummaryValues.filter((item) => Boolean((item.latest_workflow_proposal || {}).action_key)).length;
    const validationFailedCount = stage5SummaryValues.filter((item) => item.validation_passed === false).length;
    const recoveryActionableCount = stage5SummaryValues.filter((item) => {
      const action = String(item.recovery_action_key || "").trim();
      return Boolean(action) && action !== "none";
    }).length;

    const governanceActorsEl = document.getElementById("governanceActorsCount");
    const governanceQuotasEl = document.getElementById("governanceQuotasCount");
    const governanceChangeEl = document.getElementById("governanceChangeCount");
    if (governanceActorsEl) {
      governanceActorsEl.textContent = String(accessMetrics.actor_count || 0);
    }
    if (governanceQuotasEl) {
      governanceQuotasEl.textContent = String(accessMetrics.quota_count || 0);
    }
    if (governanceChangeEl) {
      governanceChangeEl.textContent = String(changeMetrics.total_change_requests || 0);
    }

    container.innerHTML = `
      <div class="top-actions">
        <button onclick="runDailyReviews()">运行 Daily Review</button>
        <button class="ghost-btn" onclick="loadMonitorOverview()">刷新概览</button>
      </div>

      <div class="summary-banner">
        <div class="summary-pill"><div class="summary-pill-label">待审批阻塞</div><div class="summary-pill-value">${approvalMetrics.pending_approvals || 0}</div></div>
        <div class="summary-pill"><div class="summary-pill-label">今日 Daily Reviews</div><div class="summary-pill-value">${reviewMetrics.daily_reviews_today || 0}</div></div>
        <div class="summary-pill"><div class="summary-pill-label">强制门禁目标</div><div class="summary-pill-value">${changeMetrics.enforced_target_count || 0}</div></div>
        <div class="summary-pill"><div class="summary-pill-label">执行协议版本</div><div class="summary-pill-value">${escapeHtml(runtimeMetadata.step_request_protocol_version || "-")}</div></div>
        <div class="summary-pill"><div class="summary-pill-label">Agent 协议版本</div><div class="summary-pill-value">${escapeHtml(runtimeMetadata.multi_agent_protocol_version || "-")}</div></div>
        <div class="summary-pill"><div class="summary-pill-label">待 Execute</div><div class="summary-pill-value">${agentMetrics.tasks_requiring_execute || 0}</div></div>
        <div class="summary-pill"><div class="summary-pill-label">待 Retry</div><div class="summary-pill-value">${agentMetrics.tasks_requiring_retry || 0}</div></div>
        <div class="summary-pill"><div class="summary-pill-label">Stage 3 就绪度</div><div class="summary-pill-value">${escapeHtml(formatRatio(stage3Readiness.readiness_ratio))}</div></div>
        <div class="summary-pill"><div class="summary-pill-label">Stage 5 完成度</div><div class="summary-pill-value">${escapeHtml(formatRatio(stage5Readiness.completion_ratio))}</div></div>
        <div class="summary-pill"><div class="summary-pill-label">Stage 6 完成度</div><div class="summary-pill-value">${escapeHtml(formatRatio(stage6Readiness.completion_ratio))}</div></div>
        <div class="summary-pill"><div class="summary-pill-label">Stage 7 Groundwork</div><div class="summary-pill-value">${escapeHtml(formatRatio(stage7Readiness.groundwork_ratio))}</div></div>
        <div class="summary-pill"><div class="summary-pill-label">Stage 5 待执行</div><div class="summary-pill-value">${stage5ExecuteCount}</div></div>
        <div class="summary-pill"><div class="summary-pill-label">Stage 5 待汇总</div><div class="summary-pill-value">${stage5FinalizeCount}</div></div>
        <div class="summary-pill"><div class="summary-pill-label">Stage 5 待重跑</div><div class="summary-pill-value">${stage5RetryCount}</div></div>
        <div class="summary-pill"><div class="summary-pill-label">Stage 5 需接管</div><div class="summary-pill-value">${stage5EscalationCount}</div></div>
        <div class="summary-pill"><div class="summary-pill-label">实现状态(postrun)</div><div class="summary-pill-value">${stage5MainlineCount}</div></div>
        <div class="summary-pill"><div class="summary-pill-label">Evaluator 来源(postrun)</div><div class="summary-pill-value">${stage5PostrunEvaluatorCount}</div></div>
        <div class="summary-pill"><div class="summary-pill-label">Workflow Proposal 可见任务</div><div class="summary-pill-value">${stage5WorkflowProposalVisibleCount}</div></div>
        <div class="summary-pill"><div class="summary-pill-label">Validation Failed</div><div class="summary-pill-value">${validationFailedCount}</div></div>
        <div class="summary-pill"><div class="summary-pill-label">Recovery Actionable</div><div class="summary-pill-value">${recoveryActionableCount}</div></div>
      </div>

      ${renderMetricGroup("任务运行", [
        ["任务总数", taskMetrics.total_tasks || 0],
        ["待审批", approvalMetrics.pending_approvals || 0],
        ["队列深度", queueMetrics.queue_depth || 0],
        ["活跃 Claim", queueMetrics.active_claims || 0],
        ["Checkpoint 任务", taskMetrics.checkpointed_tasks || 0],
      ])}

      ${renderMetricGroup("Session / Review", [
        ["Sessions", sessionMetrics.total_sessions || 0],
        ["Memories", sessionMetrics.total_memories || 0],
        ["Session States", sessionMetrics.total_session_states || 0],
        ["Session Reviews", sessionMetrics.total_session_reviews || 0],
        ["今日 Daily Reviews", reviewMetrics.daily_reviews_today || 0],
      ])}

      ${renderMetricGroup("Stage Readiness", [
        ["Stage 3 就绪度", formatRatio(stage3Readiness.readiness_ratio)],
        ["缺 State 的 Sessions", stage3Readiness.sessions_missing_state || 0],
        ["缺 Review 的 Sessions", stage3Readiness.sessions_missing_review || 0],
        ["需补 Daily Review", stage3Readiness.sessions_needing_review || 0],
        ["重复记忆 Sessions", stage3Readiness.sessions_with_duplicate_memories || 0],
        ["Stage 4 门禁覆盖", formatRatio(stage4Readiness.change_gate_coverage_ratio)],
        ["已应用变更单", stage4Readiness.change_request_applied_count || 0],
        ["变更闭环率", formatRatio(stage4Readiness.change_request_closure_ratio)],
        ["Actor / Quota 对齐", stage4Readiness.actor_quota_alignment_ok ? "OK" : "待补"],
        ["配额压力", stage4Readiness.quota_pressure_count || 0],
        ["Stage 5 Runtime Fanout", formatRatio(stage5Readiness.runtime_fanout_ratio)],
        ["Stage 5 角色骨架", formatRatio(stage5Readiness.role_skeleton_ratio)],
        ["Stage 5 终态收口", formatRatio(stage5Readiness.terminal_readiness_ratio)],
        ["Stage 5 Missing Postrun", stage5Readiness.terminal_tasks_missing_postrun || 0],
        ["Stage 5 非只读 Specialist", stage5Readiness.non_readonly_specialist_task_count || 0],
        ["Stage 5 Completion Gaps", (stage5Readiness.missing_completion_gates || []).length],
        ["Stage 6 Proposal 覆盖", formatRatio(stage6Readiness.workflow_proposal_coverage_ratio)],
        ["Stage 6 Auto Mapping", stage6Readiness.auto_mapped_proposal_count || 0],
        ["Stage 6 Bridge 激活", formatRatio(stage6Readiness.bridge_activation_ratio)],
        ["Stage 6 Bridged CR", stage6Readiness.mainline_bridged_change_request_count || 0],
        ["Stage 6 Failure Taxonomy", stage6Readiness.failure_taxonomy_count || 0],
        ["Stage 6 Shadow Validation", stage6Readiness.shadow_validation_count || 0],
        ["Stage 6 Completion Gaps", (stage6Readiness.missing_completion_gates || []).length],
        ["Stage 7 Groundwork", formatRatio(stage7Readiness.groundwork_ratio)],
        ["Stage 7 Workflow CR", stage7Readiness.workflow_improvement_change_request_count || 0],
        ["Stage 7 Shadow 完成", stage7Readiness.shadow_completed_change_request_count || 0],
        ["Stage 7 Candidate Overlay", stage7Readiness.candidate_overlay_validation_count || 0],
        ["Stage 7 Payload Hash Match", stage7Readiness.candidate_match_change_request_count || 0],
        ["Stage 7 Rollback Ready", stage7Readiness.rollback_ready_count || 0],
        ["Stage 7 Rollback Applied", stage7Readiness.rollback_applied_count || 0],
        ["Stage 7 Sandbox File", stage7Readiness.sandbox_file_applied_count || 0],
        ["Stage 7 Source Copy", stage7Readiness.sandbox_source_copy_applied_count || 0],
        ["Stage 7 Source Patch", stage7Readiness.sandbox_source_patch_applied_count || 0],
        ["Stage 7 Acceptance Pass", stage7Readiness.sandbox_acceptance_passed_count || 0],
        ["Stage 7 Acceptance Fail", stage7Readiness.sandbox_acceptance_failed_count || 0],
        ["Stage 7 Auto Rollback", stage7Readiness.sandbox_auto_rollback_applied_count || 0],
        ["Stage 7 Operational", stage7Readiness.operational ? "OK" : "待补"],
        ["Stage 7 Groundwork Gaps", (stage7Readiness.missing_groundwork_gates || []).length],
      ])}

      ${renderMetricGroup("治理控制面", [
        ["风险策略数", riskMetrics.risk_policy_count || 0],
        ["注册工具数", toolMetrics.tool_registry_count || 0],
        ["禁用工具数", toolMetrics.disabled_tool_count || 0],
        ["模型 Provider 数", modelMetrics.model_provider_count || 0],
        ["禁用 Provider", modelMetrics.disabled_model_provider_count || 0],
        ["模型路由数", modelMetrics.model_route_count || 0],
        ["禁用模型路由", modelMetrics.disabled_model_route_count || 0],
        ["变更单总数", changeMetrics.total_change_requests || 0],
        ["待处理变更单", changeMetrics.pending_change_requests || 0],
        ["强制门禁目标", changeMetrics.enforced_target_count || 0],
      ])}

      ${renderMetricGroup("Stage 5 基础观测", [
        ["Agent Runs", agentMetrics.total_agent_runs || 0],
        ["Running Agents", agentMetrics.running_agent_runs || 0],
        ["Blocked Agents", agentMetrics.blocked_agent_runs || 0],
        ["待 Finalize Tasks", agentMetrics.tasks_requiring_finalize || 0],
        ["待 Operator 接管", agentMetrics.tasks_requiring_operator_escalation || 0],
        ["Agent Messages", agentMetrics.total_agent_messages || 0],
        ["Agent Artifacts", agentMetrics.total_agent_artifacts || 0],
      ])}

      ${renderMetricGroup("Stage 6 Evaluator", [
        ["Evaluator Runs", evaluatorMetrics.total_evaluator_runs || 0],
        ["平均评分", evaluatorMetrics.avg_score == null ? "-" : Number(evaluatorMetrics.avg_score).toFixed(1)],
        ["Approved", (evaluatorMetrics.runs_by_decision || {}).approved || 0],
        ["Rework", (evaluatorMetrics.runs_by_decision || {}).rework_required || 0],
        ["Rejected", (evaluatorMetrics.runs_by_decision || {}).rejected || 0],
      ])}

      ${renderMetricGroup("访问控制", [
        ["Actors", accessMetrics.actor_count || 0],
        ["Quotas", accessMetrics.quota_count || 0],
        ["配额压力", accessMetrics.quota_pressure_count || 0],
      ])}

      ${renderInfoRows(escapeHtml, [
        ["状态分布", Object.entries(tasksByStatus).map(([status, count]) => `${status}=${count}`).join(" / ") || "暂无"],
        ["生成时间", monitorOverview.generated_at || "-"],
        ["最近 Daily Review", reviewMetrics.last_daily_review_at || "-"],
        ["Step Request 协议", runtimeMetadata.step_request_protocol_version || "-"],
        ["Multi-Agent 协议", runtimeMetadata.multi_agent_protocol_version || "-"],
        ["角色分布", Object.entries(accessMetrics.actors_by_role || {}).map(([role, count]) => `${role}=${count}`).join(" / ") || "暂无"],
        ["Agent 状态分布", Object.entries(agentMetrics.agent_runs_by_status || {}).map(([status, count]) => `${status}=${count}`).join(" / ") || "暂无"],
        ["Agent 角色分布", Object.entries(agentMetrics.agent_runs_by_role || {}).map(([role, count]) => `${role}=${count}`).join(" / ") || "暂无"],
      ])}

      ${renderRecentList("最近任务", recentTasks, (item) => `
        <div class="monitor-item">
          <div class="monitor-item-title">#${item.id} ${escapeHtml(item.status || "")}</div>
          <div class="monitor-item-meta">${escapeHtml(item.display_user_input || item.user_input || "")}</div>
          <div class="monitor-item-meta">更新时间：${escapeHtml(item.updated_at || "-")}</div>
        </div>
      `)}

      ${renderRecentList("最近审计事件", recentAuditLogs, (item) => `
        <div class="monitor-item">
          <div class="monitor-item-title">${escapeHtml(item.event_type || "")}</div>
          <div class="monitor-item-meta">actor=${escapeHtml(item.actor || "")} / task_id=${escapeHtml(item.task_id ?? "-")}</div>
          <div class="monitor-item-meta">details=${escapeHtml(JSON.stringify(item.details || {}))}</div>
        </div>
      `)}

      ${renderRecentList("最近 Reviews", recentReviews, (item) => `
        <div class="monitor-item">
          <div class="monitor-item-title">session=${escapeHtml(item.session_id ?? "-")} / ${escapeHtml(item.review_kind || "")}</div>
          <div class="monitor-item-meta">${escapeHtml(item.summary_text || "")}</div>
          <div class="monitor-item-meta">open_loops=${escapeHtml(String((item.open_loops || []).length))} / created_at=${escapeHtml(item.created_at || "-")}</div>
        </div>
      `)}

      ${renderRecentList("最近 Agent Runs", recentAgentRuns, (item) => `
        <div class="monitor-item">
          <div class="monitor-item-title">#${item.id} / task=${escapeHtml(item.task_run_id ?? "-")} / ${escapeHtml(item.role || "")} / ${escapeHtml(item.status || "")}</div>
          <div class="monitor-item-meta">attempt=${escapeHtml(String(item.attempt || 1))} / model=${escapeHtml(item.assigned_model || "-")} / profile=${escapeHtml(item.assigned_tool_profile || "-")}</div>
          <div class="monitor-item-meta">updated_at=${escapeHtml(item.updated_at || "-")}</div>
        </div>
      `)}

      ${renderRecentList("最近 Evaluator Runs", recentEvaluatorRuns, (item) => `
        <div class="monitor-item">
          <div class="monitor-item-title">#${item.id} / task=${escapeHtml(item.task_run_id ?? "-")} / ${escapeHtml(item.decision || "")}</div>
          <div class="monitor-item-meta">score=${escapeHtml(String(item.score ?? "-"))} / recommendation=${escapeHtml(item.recommendation || "-")}</div>
          <div class="monitor-item-meta">source=${escapeHtml(item.source || "-")} / created_at=${escapeHtml(item.created_at || "-")}</div>
        </div>
      `)}
    `;
  }

  function renderMetricGroup(title, items) {
    return `
      <div class="monitor-group">
        <div class="monitor-section-title">${title}</div>
        <div class="monitor-grid">
          ${items
            .map(
              ([label, value]) => `
                <div class="metric-card">
                  <div class="metric-label">${label}</div>
                  <div class="metric-value">${value}</div>
                </div>
              `
            )
            .join("")}
        </div>
      </div>
    `;
  }

  function renderInfoRows(escapeHtml, rows) {
    return rows
      .map(
        ([label, value]) => `
          <div class="info-row">
            <span class="label">${escapeHtml(label)}：</span>${escapeHtml(String(value))}
          </div>
        `
      )
      .join("");
  }

  function renderRecentList(title, items, renderItem) {
    return `
      <div class="monitor-section-title">${title}</div>
      <div class="monitor-list">
        ${items.length ? items.map(renderItem).join("") : `<div class="empty">暂无数据</div>`}
      </div>
    `;
  }

  async function loadMonitorOverview(ctx) {
    try {
      ctx.monitorOverview = await ctx.fetchJson(`${ctx.API_BASE}/monitor/overview`);
      renderMonitorOverview(ctx);
      ctx.renderGlobalStatusBar();
      ctx.renderHomeOverview();
      ctx.renderSettingsView();
    } catch (err) {
      document.getElementById("monitorOverview").innerHTML = `<div class="empty">${ctx.escapeHtml(err.message)}</div>`;
      ctx.renderGlobalStatusBar();
    }
  }

  async function runDailyReviews(ctx) {
    const note = window.prompt("请输入 daily review 备注（可留空）", "") ?? "";
    try {
      ctx.setAppTab("monitor");
      const result = await ctx.fetchJson(`${ctx.API_BASE}/reviews/daily-run`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          review_kind: "daily",
          note,
          session_limit: 20,
          active_within_hours: 24,
          force: false,
        }),
      });
      await loadMonitorOverview(ctx);
      if (ctx.selectedTaskId !== null) {
        await ctx.selectTask(ctx.selectedTaskId);
      }
      if (ctx.selectedSessionId !== null) {
        await ctx.refreshSelectedSessionBrowser(ctx.selectedSessionId);
      }
      alert(`Daily review 已触发。created=${(result.created || []).length}, skipped=${(result.skipped || []).length}`);
    } catch (err) {
      alert(err.message);
    }
  }

  window.DashboardMonitor = {
    loadMonitorOverview,
    renderMonitorOverview,
    runDailyReviews,
  };
})();
