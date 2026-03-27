(function () {
  function renderTasksView(ctx) {
    const taskList = document.getElementById("taskList");
    const queueSummary = document.getElementById("taskQueueSummary");
    if (!taskList || !queueSummary) {
      return;
    }
    const searchKeyword = String(document.getElementById("taskSearchInput")?.value || "").trim().toLowerCase();
    const statusFilter = document.getElementById("taskStatusFilter")?.value || "";
    const actionFilter = document.getElementById("taskActionFilter")?.value || "";
    const filteredTasks = ctx.allTasks.filter((task) => {
      if (searchKeyword && !ctx.getTaskSearchableText(task).includes(searchKeyword)) {
        return false;
      }
      if (statusFilter && task.status !== statusFilter) {
        return false;
      }
      if (actionFilter && ctx.getTaskActionCategory(task) !== actionFilter) {
        return false;
      }
      return true;
    });

    const runningCount = ctx.allTasks.filter((task) => task.status === "running").length;
    const blockedCount = ctx.allTasks.filter((task) => ["waiting_approval", "waiting_clarification"].includes(task.status)).length;
    const actionCount = ctx.allTasks.filter((task) => ctx.getTaskActionCategory(task) === "attention").length;

    queueSummary.innerHTML = `
      <div class="queue-chip">
        <div class="queue-chip-label">Total</div>
        <div class="queue-chip-value">${ctx.allTasks.length}</div>
      </div>
      <div class="queue-chip">
        <div class="queue-chip-label">Running</div>
        <div class="queue-chip-value">${runningCount}</div>
      </div>
      <div class="queue-chip">
        <div class="queue-chip-label">Blocked</div>
        <div class="queue-chip-value">${blockedCount}</div>
      </div>
      <div class="queue-chip">
        <div class="queue-chip-label">Needs Action</div>
        <div class="queue-chip-value">${actionCount}</div>
      </div>
    `;

    if (!filteredTasks.length) {
      taskList.innerHTML = `<div class="empty">没有符合当前筛选条件的任务。</div>`;
      return;
    }

    taskList.innerHTML = filteredTasks
      .map((task) => {
        const recoveryAction = task.recovery_action || {};
        const validationReport = task.validation_report || {};
        const skillInvocation = (task.runtime_overrides || {}).skill_invocation || null;
        const stage5 = task.stage5 || {};
        return `
          <button type="button" class="task-card task-card-operational ${task.id === ctx.selectedTaskId ? "active" : ""}" data-testid="task-card" onclick="selectTask(${task.id}, { focusWorkspace: true })">
            <div class="task-card-topline">
              <div class="task-title">#${task.id} ${ctx.escapeHtml(task.display_user_input || task.user_input || "未命名任务")}</div>
              <span class="status-badge ${ctx.statusClass(task.status)}">${ctx.escapeHtml(ctx.summarizeTaskStatus(task))}</span>
            </div>
            <div class="task-meta task-meta-strong">${ctx.escapeHtml(ctx.describeNextAction(task, validationReport, recoveryAction))}</div>
            <div class="task-meta">阶段：${ctx.escapeHtml(ctx.describeTaskStage(task, validationReport, recoveryAction))}</div>
            <div class="task-meta">更新时间：${ctx.escapeHtml(ctx.formatDateTime(task.updated_at || task.created_at))}</div>
            <div class="task-meta">Skill：${skillInvocation ? `${ctx.escapeHtml(skillInvocation.skill_id || "-")}@${ctx.escapeHtml(skillInvocation.skill_version || "-")}` : "默认 planner"}</div>
            <div class="task-chip-row">
              <span class="task-mini-chip task-mini-chip-${ctx.getTaskAttentionLevel(task)}">${ctx.escapeHtml(ctx.getTaskActionCategory(task))}</span>
              ${recoveryAction.action && recoveryAction.action !== "none" ? `<span class="task-mini-chip task-mini-chip-high">${ctx.escapeHtml(recoveryAction.action === "clarify" ? "待澄清" : `recovery:${recoveryAction.action}`)}</span>` : ""}
              ${validationReport.passed === false ? `<span class="task-mini-chip task-mini-chip-medium">${ctx.escapeHtml(task.status === "waiting_clarification" ? "need clarify" : "validation failed")}</span>` : ""}
              ${stage5.recommended_action ? `<span class="task-mini-chip">${ctx.escapeHtml(stage5.recommended_action)}</span>` : ""}
            </div>
            ${renderStage5TaskChips(ctx, stage5)}
          </button>
        `;
      })
      .join("");
  }

  function renderTaskTimeline(ctx, steps = []) {
    if (!steps.length) {
      return `<div class="empty">暂无步骤。可能仍在规划中，也可能在更早阶段失败，建议先看概览中的恢复动作。</div>`;
    }
    return steps
      .map(
        (step) => `
      <div class="timeline-card">
        <div class="timeline-rail">
          <div class="timeline-dot ${ctx.statusClass(step.status)}"></div>
          <div class="timeline-line"></div>
        </div>
        <div class="timeline-body">
          <div class="timeline-head">
            <div class="step-title">步骤 ${step.step_order}：${ctx.escapeHtml(step.step_name || "未命名步骤")}</div>
            <span class="status-badge ${ctx.statusClass(step.status)}">${ctx.escapeHtml(step.status || "-")}</span>
          </div>
          <div class="timeline-meta-row">
            <span>工具：${ctx.escapeHtml(step.tool_name || "-")}</span>
            <span>重试：${ctx.escapeHtml(String(step.retry_count || 0))} / ${ctx.escapeHtml(String(step.max_retries || 0))}</span>
          </div>
          ${step.error_message ? `<div class="timeline-alert">失败原因：${ctx.escapeHtml(step.error_message)}</div>` : ""}
          <details>
            <summary>查看输入 / 输出细节</summary>
            <div class="info-row"><span class="label">输入：</span><pre>${ctx.escapeHtml(step.input_payload || "无")}</pre></div>
            <div class="info-row"><span class="label">输出：</span><pre>${ctx.escapeHtml(step.output_payload || "暂无输出")}</pre></div>
          </details>
        </div>
      </div>
    `,
      )
      .join("");
  }

  function renderTraceHighlights(ctx, tracePayload = {}, replayPayload = null) {
    const taskTrace = tracePayload.task_trace || {};
    const stepTraces = ctx.safeArray(tracePayload.step_traces);
    const modelTraces = ctx.safeArray(tracePayload.model_traces);
    const toolTraces = ctx.safeArray(tracePayload.tool_traces);
    const skillTraces = ctx.safeArray(tracePayload.skill_traces);
    const retrievalTraces = ctx.safeArray(tracePayload.retrieval_traces);
    const replaySummary = replayPayload?.summary || {};
    return `
      <div class="task-summary-grid">
        <div class="task-summary-card">
          <div class="task-summary-label">Task Trace</div>
          <div class="task-summary-value">${ctx.escapeHtml(taskTrace.status || "-")}</div>
        </div>
        <div class="task-summary-card">
          <div class="task-summary-label">Replay Step Count</div>
          <div class="task-summary-value">${ctx.escapeHtml(String(replaySummary.step_count || 0))}</div>
        </div>
        <div class="task-summary-card">
          <div class="task-summary-label">Model Calls</div>
          <div class="task-summary-value">${modelTraces.length}</div>
        </div>
        <div class="task-summary-card">
          <div class="task-summary-label">Tool Calls</div>
          <div class="task-summary-value">${toolTraces.length}</div>
        </div>
        <div class="task-summary-card">
          <div class="task-summary-label">Skill Traces</div>
          <div class="task-summary-value">${skillTraces.length}</div>
        </div>
        <div class="task-summary-card">
          <div class="task-summary-label">Retrieval Traces</div>
          <div class="task-summary-value">${retrievalTraces.length}</div>
        </div>
      </div>
      <div class="info-row"><span class="label">Task Trace 摘要：</span>${ctx.escapeHtml(taskTrace.trace_id || "-")} / ${ctx.escapeHtml(taskTrace.plan_source || replaySummary.plan_source || "-")}</div>
      <details style="margin-top: 12px;">
        <summary>查看完整追踪与 Replay</summary>
        ${ctx.renderTaskTraces(tracePayload, replayPayload)}
      </details>
    `;
  }

  function renderTraceMetaRows(ctx, trace = {}) {
    const rows = [];
    if (trace.status) {
      rows.push(`<div class="info-row"><span class="label">状态：</span><span class="status-badge ${ctx.statusClass(trace.status)}">${ctx.escapeHtml(trace.status)}</span></div>`);
    }
    if (trace.trace_id) {
      rows.push(`<div class="info-row"><span class="label">trace_id：</span>${ctx.escapeHtml(trace.trace_id)}</div>`);
    }
    if (trace.plan_source) {
      rows.push(`<div class="info-row"><span class="label">plan_source：</span>${ctx.escapeHtml(trace.plan_source)}</div>`);
    }
    if (trace.route_name) {
      rows.push(`<div class="info-row"><span class="label">route_name：</span>${ctx.escapeHtml(trace.route_name)}</div>`);
    }
    if (trace.tool_name) {
      rows.push(`<div class="info-row"><span class="label">tool_name：</span>${ctx.escapeHtml(trace.tool_name)}</div>`);
    }
    if (trace.skill_id) {
      rows.push(`<div class="info-row"><span class="label">skill_id：</span>${ctx.escapeHtml(trace.skill_id)}</div>`);
    }
    if (trace.skill_version) {
      rows.push(`<div class="info-row"><span class="label">skill_version：</span>${ctx.escapeHtml(trace.skill_version)}</div>`);
    }
    if (trace.retrieval_scope) {
      rows.push(`<div class="info-row"><span class="label">retrieval_scope：</span>${ctx.escapeHtml(trace.retrieval_scope)}</div>`);
    }
    if (trace.model_name) {
      rows.push(`<div class="info-row"><span class="label">model_name：</span>${ctx.escapeHtml(trace.model_name)}</div>`);
    }
    if (trace.provider) {
      rows.push(`<div class="info-row"><span class="label">provider：</span>${ctx.escapeHtml(trace.provider)}</div>`);
    }
    if (trace.task_step_id) {
      rows.push(`<div class="info-row"><span class="label">task_step_id：</span>#${ctx.escapeHtml(trace.task_step_id)}</div>`);
    }
    if (trace.step_trace_id) {
      rows.push(`<div class="info-row"><span class="label">step_trace_id：</span>#${ctx.escapeHtml(trace.step_trace_id)}</div>`);
    }
    if (trace.started_at || trace.ended_at) {
      rows.push(`<div class="info-row"><span class="label">时间：</span>${ctx.escapeHtml(trace.started_at || "-")} → ${ctx.escapeHtml(trace.ended_at || "-")}</div>`);
    }
    if (trace.input_summary) {
      rows.push(`<div class="info-row"><span class="label">input_summary：</span><pre>${ctx.escapeHtml(trace.input_summary)}</pre></div>`);
    }
    if (trace.request_excerpt) {
      rows.push(`<div class="info-row"><span class="label">request_excerpt：</span><pre>${ctx.escapeHtml(trace.request_excerpt)}</pre></div>`);
    }
    if (trace.response_excerpt) {
      rows.push(`<div class="info-row"><span class="label">response_excerpt：</span><pre>${ctx.escapeHtml(trace.response_excerpt)}</pre></div>`);
    }
    if (trace.metadata_json) {
      rows.push(`<div class="info-row"><span class="label">metadata：</span><pre>${ctx.escapeHtml(JSON.stringify(trace.metadata_json, null, 2))}</pre></div>`);
    }
    if (trace.output_snapshot) {
      rows.push(`<div class="info-row"><span class="label">output_snapshot：</span><pre>${ctx.escapeHtml(JSON.stringify(trace.output_snapshot, null, 2))}</pre></div>`);
    }
    if (trace.error_summary) {
      rows.push(`<div class="info-row"><span class="label">错误：</span>${ctx.escapeHtml(trace.error_summary)}</div>`);
    }
    return rows.join("");
  }

  function renderTraceCardList(ctx, title, items, buildTitle) {
    if (!items.length) {
      return `
        <div class="panel">
          <div class="panel-title">${ctx.escapeHtml(title)}</div>
          <div class="empty">暂无数据</div>
        </div>
      `;
    }
    return `
      <div class="panel">
        <div class="panel-title">${ctx.escapeHtml(title)}</div>
        ${items.map((item, index) => `
          <div class="step-card">
            <div class="step-title">${buildTitle(item, index)}</div>
            ${renderTraceMetaRows(ctx, item)}
            <div class="info-row"><span class="label">原始记录：</span><pre>${ctx.escapeHtml(JSON.stringify(item || {}, null, 2))}</pre></div>
          </div>
        `).join("")}
      </div>
    `;
  }

  function renderTraceSummary(ctx, tracePayload = {}) {
    const cards = [
      { label: "Task", value: tracePayload.task_trace ? 1 : 0 },
      { label: "Steps", value: Array.isArray(tracePayload.step_traces) ? tracePayload.step_traces.length : 0 },
      { label: "Models", value: Array.isArray(tracePayload.model_traces) ? tracePayload.model_traces.length : 0 },
      { label: "Tools", value: Array.isArray(tracePayload.tool_traces) ? tracePayload.tool_traces.length : 0 },
      { label: "Skills", value: Array.isArray(tracePayload.skill_traces) ? tracePayload.skill_traces.length : 0 },
      { label: "Retrieval", value: Array.isArray(tracePayload.retrieval_traces) ? tracePayload.retrieval_traces.length : 0 },
    ];
    return `
      <div class="task-summary-grid">
        ${cards.map((item) => `
          <div class="task-summary-card">
            <div class="task-summary-label">${ctx.escapeHtml(item.label)}</div>
            <div class="task-summary-value">${ctx.escapeHtml(String(item.value))}</div>
          </div>
        `).join("")}
      </div>
    `;
  }

  function renderTaskReplay(ctx, replayPayload = null) {
    if (!replayPayload || !Array.isArray(replayPayload.steps)) {
      return `
        <div class="panel">
          <div class="panel-title">Trace Replay</div>
          <div class="empty">当前任务暂无 replay 视图</div>
        </div>
      `;
    }
    const summary = replayPayload.summary || {};
    const task = replayPayload.task || {};
    const skillInvocation = ((task.runtime_overrides || {}).skill_invocation) || null;
    return `
      <div class="panel">
        <div class="panel-title">Trace Replay</div>
        <div class="panel-subtitle">只读回放当前任务的执行编排，不会重新执行任务。</div>
        <div class="task-summary-grid" data-testid="task-summary-grid">
          <div class="task-summary-card">
            <div class="task-summary-label">Plan Source</div>
            <div class="task-summary-value">${ctx.escapeHtml(summary.plan_source || "-")}</div>
          </div>
          <div class="task-summary-card">
            <div class="task-summary-label">Steps</div>
            <div class="task-summary-value">${ctx.escapeHtml(String(summary.step_count || 0))}</div>
          </div>
          <div class="task-summary-card">
            <div class="task-summary-label">Traces</div>
            <div class="task-summary-value">${ctx.escapeHtml(String((summary.model_trace_count || 0) + (summary.tool_trace_count || 0) + (summary.skill_trace_count || 0) + (summary.retrieval_trace_count || 0)))}</div>
          </div>
          <div class="task-summary-card">
            <div class="task-summary-label">Skill</div>
            <div class="task-summary-value">${skillInvocation ? ctx.escapeHtml(`${skillInvocation.skill_id || "-"}@${skillInvocation.skill_version || "-"}`) : "默认 planner"}</div>
          </div>
        </div>
        ${replayPayload.steps.map((step) => `
          <div class="step-card">
            <div class="step-title">步骤 ${ctx.escapeHtml(step.step_order || "-")}：${ctx.escapeHtml(step.step_name || "-")}</div>
            <div class="info-row"><span class="label">状态：</span><span class="status-badge ${ctx.statusClass(step.status)}">${ctx.escapeHtml(step.status || "-")}</span></div>
            <div class="info-row"><span class="label">工具：</span>${ctx.escapeHtml(step.tool_name || "-")}</div>
            <div class="info-row"><span class="label">重试：</span>${ctx.escapeHtml(String(step.retry_count || 0))} / ${ctx.escapeHtml(String(step.max_retries || 0))}</div>
            <div class="info-row"><span class="label">条件：</span>run_if=${ctx.escapeHtml(JSON.stringify(step.run_if ?? null))} · skip_if=${ctx.escapeHtml(JSON.stringify(step.skip_if ?? null))}</div>
            <div class="info-row"><span class="label">输入：</span><pre>${ctx.escapeHtml(JSON.stringify(step.input_payload ?? null, null, 2))}</pre></div>
            <div class="info-row"><span class="label">输出摘要：</span><pre>${ctx.escapeHtml(step.output_payload || "暂无输出")}</pre></div>
            <div class="info-row"><span class="label">输出结构：</span><pre>${ctx.escapeHtml(JSON.stringify(step.output_data ?? null, null, 2))}</pre></div>
            <div class="info-row"><span class="label">Replay Hints：</span><pre>${ctx.escapeHtml(JSON.stringify(step.replay_hints || {}, null, 2))}</pre></div>
            <div class="info-row"><span class="label">Trace Counts：</span>step=${ctx.escapeHtml(String((step.trace_counts || {}).step || 0))} · model=${ctx.escapeHtml(String((step.trace_counts || {}).model || 0))} · tool=${ctx.escapeHtml(String((step.trace_counts || {}).tool || 0))} · skill=${ctx.escapeHtml(String((step.trace_counts || {}).skill || 0))} · retrieval=${ctx.escapeHtml(String((step.trace_counts || {}).retrieval || 0))}</div>
            <div class="info-row"><span class="label">Approvals：</span><pre>${ctx.escapeHtml(JSON.stringify(step.approvals || [], null, 2))}</pre></div>
          </div>
        `).join("")}
      </div>
    `;
  }

  function renderTaskTraces(ctx, tracePayload = {}, replayPayload = null) {
    const taskTrace = tracePayload.task_trace || null;
    const stepTraces = Array.isArray(tracePayload.step_traces) ? tracePayload.step_traces : [];
    const modelTraces = Array.isArray(tracePayload.model_traces) ? tracePayload.model_traces : [];
    const toolTraces = Array.isArray(tracePayload.tool_traces) ? tracePayload.tool_traces : [];
    const skillTraces = Array.isArray(tracePayload.skill_traces) ? tracePayload.skill_traces : [];
    const retrievalTraces = Array.isArray(tracePayload.retrieval_traces) ? tracePayload.retrieval_traces : [];

    const taskTracePanel = taskTrace
      ? `
        <div class="panel">
          <div class="panel-title">Task Trace</div>
          <div class="step-card">
            <div class="step-title">task_trace #${ctx.escapeHtml(taskTrace.id || "-")}</div>
            ${renderTraceMetaRows(ctx, taskTrace)}
            <div class="info-row"><span class="label">原始记录：</span><pre>${ctx.escapeHtml(JSON.stringify(taskTrace || {}, null, 2))}</pre></div>
          </div>
        </div>
      `
      : `
        <div class="panel">
          <div class="panel-title">Task Trace</div>
          <div class="empty">当前任务暂无 task trace</div>
        </div>
      `;

    return `
      ${renderTaskReplay(ctx, replayPayload)}
      ${renderTraceSummary(ctx, tracePayload)}
      ${taskTracePanel}
      ${renderTraceCardList(ctx, "Step Traces", stepTraces, (item, index) => `step_trace #${ctx.escapeHtml(item.id || "-")} · 步骤 ${ctx.escapeHtml(item.step_order || index + 1)}`)}
      ${renderTraceCardList(ctx, "Model Traces", modelTraces, (item, index) => `model_trace #${ctx.escapeHtml(item.id || "-")} · ${ctx.escapeHtml(item.route_name || `调用 ${index + 1}`)}`)}
      ${renderTraceCardList(ctx, "Tool Traces", toolTraces, (item, index) => `tool_trace #${ctx.escapeHtml(item.id || "-")} · ${ctx.escapeHtml(item.tool_name || `工具 ${index + 1}`)}`)}
      ${renderTraceCardList(ctx, "Skill Traces", skillTraces, (item, index) => `skill_trace #${ctx.escapeHtml(item.id || "-")} · ${ctx.escapeHtml(item.skill_id || `skill ${index + 1}`)}`)}
      ${renderTraceCardList(ctx, "Retrieval Traces", retrievalTraces, (item, index) => `retrieval_trace #${ctx.escapeHtml(item.id || "-")} · ${ctx.escapeHtml(item.retrieval_scope || `检索 ${index + 1}`)}`)}
    `;
  }

  function renderWorkspaceLoadingState(ctx, taskId) {
    document.getElementById("workspaceHero").innerHTML = `
      <div class="workspace-hero-card">
        <div class="workspace-hero-label">当前任务</div>
        <div class="workspace-hero-value">#${ctx.escapeHtml(String(taskId || "-"))}</div>
      </div>
      <div class="workspace-hero-card">
        <div class="workspace-hero-label">状态</div>
        <div class="workspace-hero-value">加载中</div>
      </div>
      <div class="workspace-hero-card">
        <div class="workspace-hero-label">下一步</div>
        <div class="workspace-hero-value">正在同步任务概览、步骤、审批和 session 信息</div>
      </div>
      <div class="workspace-hero-card">
        <div class="workspace-hero-label">Session</div>
        <div class="workspace-hero-value">读取中</div>
      </div>
      <div class="workspace-hero-card">
        <div class="workspace-hero-label">当前步骤</div>
        <div class="workspace-hero-value">读取中</div>
      </div>
    `;
    document.getElementById("taskDetail").innerHTML = `<div class="empty">正在加载任务 #${ctx.escapeHtml(String(taskId || "-"))} 的工作区数据...</div>`;
    document.getElementById("stepsDetail").innerHTML = `<div class="empty">正在加载步骤时间线...</div>`;
    document.getElementById("traceDetail").innerHTML = `<div class="empty">正在加载 traces 与 replay...</div>`;
    document.getElementById("approvalDetail").innerHTML = `<div class="empty">正在加载审批状态...</div>`;
    document.getElementById("taskAgentsDetail").innerHTML = `<div class="empty">正在加载 Agent 观察视图...</div>`;
    document.getElementById("sessionReviewDetail").innerHTML = `<div class="empty">正在加载 session review...</div>`;
    document.getElementById("sessionStateDetail").innerHTML = `<div class="empty">正在加载 session state...</div>`;
    document.getElementById("sessionHealthDetail").innerHTML = `<div class="empty">正在加载 session health...</div>`;
  }

  function formatWorkflowProposalLabel(proposal = {}) {
    const actionKey = String(proposal.action_key || "").trim();
    const priority = String(proposal.priority || "").trim();
    if (actionKey && priority) {
      return `${actionKey} (${priority})`;
    }
    if (actionKey) {
      return actionKey;
    }
    if (priority) {
      return `priority=${priority}`;
    }
    return "-";
  }

  function buildWorkflowProposalSandboxFileTemplate(ctx, proposal = {}) {
    const proposalId = Number(proposal.id || 0);
    const actionKey = String(proposal.action_key || "unknown").trim() || "unknown";
    return {
      targetType: "sandbox_file",
      targetKey: `bridge/proposal_${proposalId || "latest"}_assistant_cli_patch.py`,
      payload: {
        source_path: "scripts/assistant_cli.py",
        patch: ctx.buildSandboxFileSourcePatchTemplate(`workflow proposal #${proposalId || "-"} ${actionKey} bridge`),
        acceptance: {
          script_path: "scripts/stage7_sandbox_file_acceptance_probe.sh",
          timeout_seconds: 20,
          env: {
            STAGE7_EXPECT_CONTAINS: `workflow proposal #${proposalId || "-"} ${actionKey} bridge`,
          },
        },
      },
      rationale: `workflow proposal #${proposalId || "-"} sandbox_file source-patch experiment (${actionKey})`,
    };
  }

  function buildWorkflowProposalModelRouteTemplate(proposal = {}) {
    const proposalId = Number(proposal.id || 0);
    return {
      targetType: "model_route",
      targetKey: "planner",
      payload: {
        provider: "deepseek_default",
        enabled: true,
        model_name: "deepseek-chat",
        temperature: 0.2,
        max_tokens: 1800,
        description: `workflow proposal #${proposalId || "-"} planner route template`,
      },
      rationale: `workflow proposal #${proposalId || "-"} planner route bridge template`,
    };
  }

  function renderWorkflowProposalTemplateActions(ctx, proposal = {}) {
    const proposalId = Number(proposal.id || 0);
    if (!proposalId) {
      return "";
    }

    const actionKey = String(proposal.action_key || "").trim();
    const templates = [buildWorkflowProposalSandboxFileTemplate(ctx, proposal)];
    if (actionKey === "expand_specialist_scope") {
      templates.unshift(buildWorkflowProposalModelRouteTemplate(proposal));
    }

    const buttons = templates
      .map((template) => {
        const encodedTargetKey = encodeURIComponent(String(template.targetKey || ""));
        const encodedPayload = encodeURIComponent(JSON.stringify(template.payload || {}));
        const encodedRationale = encodeURIComponent(String(template.rationale || ""));
        const label = template.targetType === "sandbox_file" ? "打开 sandbox_file source-patch 模板" : "打开 model_route 模板";
        return `<button class="ghost-btn" onclick="openChangeRequestTemplate('${ctx.escapeHtml(template.targetType)}', decodeURIComponent('${encodedTargetKey}'), JSON.parse(decodeURIComponent('${encodedPayload}')), decodeURIComponent('${encodedRationale}'))">${ctx.escapeHtml(label)}</button>`;
      })
      .join("");

    return buttons ? `<div class="top-actions">${buttons}</div>` : "";
  }

  function renderTaskAgentRuns(ctx, taskId, agentRuns = [], agentDetails = {}) {
    const summary = window.currentTaskAgentSummary || null;
    const isMainlinePostrun = summary?.implementation_status === "task_runtime_postrun_v1";
    if (!agentRuns.length) {
      return `
        <div class="top-actions">
          <button onclick="bootstrapTaskAgentRuns(${taskId})">生成 Agent 骨架（smoke/debug）</button>
        </div>
        <div class="empty">当前任务还没有 agent runs。主链以 postrun 只读观测优先；如需专项调试，可手动生成 demo 骨架（smoke/debug）。</div>
      `;
    }

    const grouped = agentRuns.reduce((acc, item) => {
      const key = item.role || "unknown";
      if (!acc[key]) acc[key] = [];
      acc[key].push(item);
      return acc;
    }, {});
    const roleSummary = Object.entries(grouped)
      .map(([role, items]) => `${role}=${items.length}`)
      .join(" / ");
    const renderAgentExecutionSnapshot = (detail = {}) => {
      const artifacts = detail.artifacts || [];
      const latestDraft = artifacts.find((item) => item.artifact_type === "draft");
      const latestBrief = artifacts.find((item) => item.artifact_type === "brief");
      const content = latestDraft?.content || {};
      const output = content.output || {};
      const subtask = output.subtask || {};
      const briefContent = latestBrief?.content || {};
      const briefExecutionRequest = briefContent.execution_request || {};
      const executionResult = output.execution_result || {};
      const assignedOrders = subtask.assigned_step_orders || executionResult.assigned_step_orders || [];
      const followups = executionResult.recommended_followups || [];
      if (!latestDraft && !latestBrief) {
        return "";
      }
      return `
        <div class="info-row"><span class="label">Brief 子任务：</span>${ctx.escapeHtml(briefExecutionRequest.subtask_type || "-")}</div>
        <div class="info-row"><span class="label">执行模式：</span>${ctx.escapeHtml(subtask.execution_mode || executionResult.execution_mode || "-")}</div>
        <div class="info-row"><span class="label">子任务类型：</span>${ctx.escapeHtml(subtask.type || executionResult.subtask_type || "-")}</div>
        <div class="info-row"><span class="label">步骤覆盖：</span>${ctx.escapeHtml((assignedOrders.length ? assignedOrders.join(", ") : "fallback").toString())}</div>
        <div class="info-row"><span class="label">建议后续：</span>${ctx.escapeHtml((followups.length ? followups.join("；") : "无").toString())}</div>
      `;
    };

    const renderTaskAgentSummary = () => {
      if (!summary) {
        return "";
      }
      const latestFinal = summary.latest_final_artifact || null;
      const latestReview = summary.latest_review_artifact || null;
      const latestEvaluator = summary.latest_evaluator || null;
      const latestWorkflowProposal = summary.latest_workflow_proposal || {};
      const latestValidation = summary.latest_validation_report || {};
      const latestRecoveryAction = summary.latest_recovery_action || {};
      const workflowProposalLabel = formatWorkflowProposalLabel(latestWorkflowProposal);
      const capabilities = summary.capabilities || {};
      return `
        <div class="step-card">
          <div class="step-title">Stage 5 Summary</div>
          <div class="info-row"><span class="label">实现状态：</span>${ctx.escapeHtml(summary.implementation_status || "-")}</div>
          <div class="info-row"><span class="label">推荐动作：</span>${ctx.escapeHtml(summary.recommended_action || "none")}</div>
          <div class="info-row"><span class="label">等待角色：</span>${ctx.escapeHtml(summary.awaiting_role || "-")}</div>
          <div class="info-row"><span class="label">阻塞原因：</span>${ctx.escapeHtml(summary.blocking_reason || "-")}</div>
          <div class="info-row"><span class="label">执行后端：</span>${ctx.escapeHtml(summary.execution_backend || "none")}</div>
          <div class="info-row"><span class="label">执行模式：</span>${ctx.escapeHtml((summary.specialist_execution_modes || []).join(" / ") || "-")}</div>
          <div class="info-row"><span class="label">Manager 状态：</span>${ctx.escapeHtml(summary.manager?.status || "-")}</div>
          <div class="info-row"><span class="label">Reviewer 决策：</span>${ctx.escapeHtml(summary.latest_reviewer_decision || "-")}</div>
          <div class="info-row"><span class="label">决策来源：</span>${ctx.escapeHtml(summary.latest_decision_source || "-")}</div>
          <div class="info-row"><span class="label">Next Strategy：</span>${ctx.escapeHtml(summary.latest_next_strategy || "-")}</div>
          <div class="info-row"><span class="label">Final 版本：</span>${ctx.escapeHtml(String(latestFinal?.version || 0))}</div>
          <div class="info-row"><span class="label">Review 版本：</span>${ctx.escapeHtml(String(latestReview?.version || 0))}</div>
          <div class="info-row"><span class="label">Quality Score：</span>${ctx.escapeHtml(String(latestFinal?.quality_score ?? latestReview?.quality_score ?? "-"))}</div>
          <div class="info-row"><span class="label">Evaluator 决策：</span>${ctx.escapeHtml(latestEvaluator?.decision || "-")}</div>
          <div class="info-row"><span class="label">Evaluator Score：</span>${ctx.escapeHtml(String(latestEvaluator?.score ?? "-"))}</div>
          <div class="info-row"><span class="label">Evaluator 来源：</span>${ctx.escapeHtml(latestEvaluator?.source || "-")}</div>
          <div class="info-row"><span class="label">Validation：</span>${ctx.escapeHtml(summary.validation_passed === true ? "passed" : summary.validation_passed === false ? "failed" : "-")}</div>
          <div class="info-row"><span class="label">Validation 摘要：</span>${ctx.escapeHtml(summary.validation_summary || latestValidation.summary || "-")}</div>
          <div class="info-row"><span class="label">Recovery：</span>${ctx.escapeHtml(summary.recovery_action_key || latestRecoveryAction.action || "-")}</div>
          <div class="info-row"><span class="label">Recovery 摘要：</span>${ctx.escapeHtml(summary.recovery_summary || latestRecoveryAction.summary || "-")}</div>
          <div class="info-row"><span class="label">Workflow Proposal：</span>${ctx.escapeHtml(workflowProposalLabel)}</div>
          ${renderWorkflowProposalTemplateActions(ctx, latestWorkflowProposal)}
          <div class="info-row"><span class="label">Evaluator 建议：</span>${ctx.escapeHtml(latestEvaluator?.recommendation || "-")}</div>
          <div class="info-row"><span class="label">可执行动作：</span>${ctx.escapeHtml([
            capabilities.can_execute ? "execute" : "",
            capabilities.can_force_rerun ? "force_rerun" : "",
            capabilities.can_finalize ? "finalize" : "",
            capabilities.can_allow_retry ? "allow_retry" : "",
          ].filter(Boolean).join(" / ") || "无")}</div>
        </div>
      `;
    };

    return `
      <div class="top-actions">
        <button class="ghost-btn" onclick="selectTask(${taskId}, { focusWorkspace: true, workspaceTab: 'agents' })">刷新 Agent 视图</button>
        <button class="ghost-btn" onclick="executeTaskAgentRunsViaWorker(${taskId})">Worker 执行 Specialists（smoke/debug）</button>
        <button class="ghost-btn" onclick="executeTaskAgentRuns(${taskId})">执行 Specialists（demo）</button>
        <button class="ghost-btn" onclick="rerunTaskAgentRuns(${taskId})">重跑 Specialists（debug）</button>
        <button onclick="finalizeTaskAgentRuns(${taskId})">汇总 Final Artifact（demo）</button>
      </div>
      ${isMainlinePostrun ? '<div class="info-row"><span class="label">说明：</span>当前任务已进入主链 postrun 只读观测，以上按钮主要用于 smoke/debug，不是默认执行路径。</div>' : ""}
      ${renderTaskAgentSummary()}
      <div class="info-row"><span class="label">角色分布：</span>${ctx.escapeHtml(roleSummary || "暂无")}</div>
      ${agentRuns
        .map(
          (item) => `
        <div class="step-card">
          <div class="step-title">Agent #${item.id} / ${ctx.escapeHtml(item.role || "")} / ${ctx.escapeHtml(item.status || "")}</div>
          <div class="info-row"><span class="label">attempt：</span>${ctx.escapeHtml(String(item.attempt || 1))}</div>
          <div class="info-row"><span class="label">父 Agent：</span>${ctx.escapeHtml(item.parent_agent_run_id ?? "-")}</div>
          <div class="info-row"><span class="label">brief artifact：</span>${ctx.escapeHtml(item.brief_artifact_id ?? "-")}</div>
          <div class="info-row"><span class="label">output artifact：</span>${ctx.escapeHtml(item.output_artifact_id ?? "-")}</div>
          <div class="info-row"><span class="label">review artifact：</span>${ctx.escapeHtml(item.review_artifact_id ?? "-")}</div>
          <div class="info-row"><span class="label">model：</span>${ctx.escapeHtml(item.assigned_model || "-")}</div>
          <div class="info-row"><span class="label">tool profile：</span>${ctx.escapeHtml(item.assigned_tool_profile || "-")}</div>
          <div class="info-row"><span class="label">错误：</span>${ctx.escapeHtml(item.error_summary || "无")}</div>
          <div class="info-row"><span class="label">更新时间：</span>${ctx.escapeHtml(item.updated_at || "-")}</div>
          ${renderAgentExecutionSnapshot(agentDetails[item.id] || {})}
          <details style="margin-top: 10px;">
            <summary>消息与工件明细</summary>
            <div class="info-row"><span class="label">Messages：</span>${ctx.escapeHtml(String((agentDetails[item.id]?.messages || []).length))}</div>
            <div class="info-row"><span class="label">Artifacts：</span>${ctx.escapeHtml(String((agentDetails[item.id]?.artifacts || []).length))}</div>
            <div class="info-row"><span class="label">Messages：</span><pre>${ctx.escapeHtml(((agentDetails[item.id]?.messages || []).map((msg) => `${msg.message_type} ${msg.sender_role}->${msg.recipient_role} ${JSON.stringify(msg.payload || {})}`).join("\n\n")) || "暂无")}</pre></div>
            <div class="info-row"><span class="label">Artifacts：</span><pre>${ctx.escapeHtml(((agentDetails[item.id]?.artifacts || []).map((art) => `${art.artifact_type}#${art.id} ${art.summary || ""}\n${JSON.stringify(art.content || {}, null, 2)}`).join("\n\n")) || "暂无")}</pre></div>
          </details>
        </div>
      `,
        )
        .join("")}
    `;
  }

  function renderStage5TaskChips(ctx, summary) {
    if (!summary) {
      return "";
    }
    const chips = [];
    const latestEvaluator = summary.latest_evaluator || {};
    const latestWorkflowProposal = summary.latest_workflow_proposal || {};
    if (summary.recommended_action) {
      chips.push(`<span class="stage5-chip">Stage 5: ${ctx.escapeHtml(summary.recommended_action)}</span>`);
    }
    if (summary.latest_reviewer_decision) {
      const decisionClass =
        summary.latest_reviewer_decision === "rejected"
          ? "stage5-chip-danger"
          : summary.latest_reviewer_decision === "rework_required"
            ? "stage5-chip-warn"
            : "stage5-chip";
      chips.push(`<span class="stage5-chip ${decisionClass}">review: ${ctx.escapeHtml(summary.latest_reviewer_decision)}</span>`);
    }
    if (summary.latest_decision_source) {
      chips.push(`<span class="stage5-chip stage5-chip-muted">${ctx.escapeHtml(summary.latest_decision_source)}</span>`);
    }
    if (summary.validation_passed === true) {
      chips.push(`<span class="stage5-chip">validation: passed</span>`);
    } else if (summary.validation_passed === false) {
      chips.push(`<span class="stage5-chip stage5-chip-warn">validation: failed</span>`);
    }
    if (summary.recovery_action_key && summary.recovery_action_key !== "none") {
      chips.push(`<span class="stage5-chip stage5-chip-warn">recovery: ${ctx.escapeHtml(summary.recovery_action_key)}</span>`);
    }
    if (summary.execution_backend) {
      chips.push(`<span class="stage5-chip stage5-chip-muted">backend: ${ctx.escapeHtml(summary.execution_backend)}</span>`);
    }
    if (summary.implementation_status) {
      chips.push(`<span class="stage5-chip stage5-chip-muted">impl: ${ctx.escapeHtml(summary.implementation_status)}</span>`);
    }
    if (latestEvaluator.source) {
      chips.push(`<span class="stage5-chip stage5-chip-muted">evaluator: ${ctx.escapeHtml(latestEvaluator.source)}</span>`);
    }
    if (latestWorkflowProposal.action_key || latestWorkflowProposal.priority) {
      chips.push(`<span class="stage5-chip stage5-chip-muted">proposal: ${ctx.escapeHtml(formatWorkflowProposalLabel(latestWorkflowProposal))}</span>`);
    }
    if (summary.latest_final_artifact?.version) {
      chips.push(`<span class="stage5-chip stage5-chip-muted">final v${ctx.escapeHtml(String(summary.latest_final_artifact.version))}</span>`);
    }
    if (summary.latest_final_artifact?.quality_score !== undefined && summary.latest_final_artifact?.quality_score !== null) {
      chips.push(`<span class="stage5-chip stage5-chip-muted">score ${ctx.escapeHtml(String(summary.latest_final_artifact.quality_score))}</span>`);
    }
    return chips.length ? `<div class="task-stage5-row">${chips.join("")}</div>` : "";
  }

  async function loadTasks(ctx) {
    try {
      const tasks = await ctx.fetchJson(`${ctx.API_BASE}/tasks?include_stage5_summary=true&limit=40`);
      ctx.allTasks = Array.isArray(tasks) ? tasks : [];
      ctx.taskAgentSummaries = new Map(ctx.allTasks.map((task) => [task.id, task.stage5 || null]).filter(([, summary]) => Boolean(summary)));
      renderTasksView(ctx);
      ctx.renderHomeOverview();
      ctx.renderGlobalStatusBar();
      ctx.renderSettingsView();
      if (ctx.monitorOverview) {
        ctx.renderMonitorOverview();
      }
    } catch (err) {
      document.getElementById("taskList").innerHTML = `<div class="empty">${ctx.escapeHtml(err.message)}</div>`;
      const homePending = document.getElementById("homePendingList");
      if (homePending) {
        homePending.innerHTML = `<div class="empty">${ctx.escapeHtml(err.message)}</div>`;
      }
    }
  }

  async function selectTask(ctx, taskId, options = {}) {
    ctx.selectedTaskId = taskId;
    if (options.focusWorkspace) {
      ctx.setAppTab("workspace");
      ctx.setWorkspaceTab(options.workspaceTab || "overview");
    }
    await loadTasks(ctx);
    renderWorkspaceLoadingState(ctx, taskId);

    try {
      const [task, steps, approvals, agentRuns, agentSummary, tracePayload, replayPayload] = await Promise.all([
        ctx.fetchJson(`${ctx.API_BASE}/tasks/${taskId}`),
        ctx.fetchJson(`${ctx.API_BASE}/tasks/${taskId}/steps`),
        ctx.fetchJson(`${ctx.API_BASE}/tasks/${taskId}/approvals`),
        ctx.fetchJson(`${ctx.API_BASE}/tasks/${taskId}/agent-runs`),
        ctx.fetchJson(`${ctx.API_BASE}/tasks/${taskId}/agent-runs/summary`),
        ctx.fetchJson(`${ctx.API_BASE}/tasks/${taskId}/traces`),
        ctx.fetchJson(`${ctx.API_BASE}/tasks/${taskId}/replay`),
      ]);
      ctx.currentTaskSnapshot = task;
      window.currentTaskAgentSummary = agentSummary;
      ctx.taskAgentSummaries.set(taskId, agentSummary);
      if (ctx.monitorOverview) {
        ctx.renderMonitorOverview();
      }
      const agentDetailsEntries = await Promise.all(
        agentRuns.map(async (agentRun) => {
          const [messages, artifacts] = await Promise.all([
            ctx.fetchJson(`${ctx.API_BASE}/agent-runs/${agentRun.id}/messages?limit=20`),
            ctx.fetchJson(`${ctx.API_BASE}/agent-runs/${agentRun.id}/artifacts?limit=20`),
          ]);
          return [agentRun.id, { messages, artifacts }];
        }),
      );
      const agentDetails = Object.fromEntries(agentDetailsEntries);
      const sessionSummary = task.session_id ? await ctx.fetchJson(`${ctx.API_BASE}/sessions/${task.session_id}/summary`) : null;
      const sessionReviews = task.session_id ? await ctx.fetchJson(`${ctx.API_BASE}/sessions/${task.session_id}/reviews?limit=5`) : [];
      const sessionState = sessionSummary?.session_state || null;
      const sessionHealth = sessionSummary?.health || null;

      document.getElementById("workspaceHero").innerHTML = `
        <div class="workspace-hero-card">
          <div class="workspace-hero-label">当前任务</div>
          <div class="workspace-hero-value">#${task.id}</div>
        </div>
        <div class="workspace-hero-card">
          <div class="workspace-hero-label">状态</div>
          <div class="workspace-hero-value">${ctx.escapeHtml(ctx.summarizeTaskStatus(task))}</div>
        </div>
        <div class="workspace-hero-card">
          <div class="workspace-hero-label">下一步</div>
          <div class="workspace-hero-value">${ctx.escapeHtml(ctx.describeNextAction(task, task.validation_report || {}, task.recovery_action || {}))}</div>
        </div>
        <div class="workspace-hero-card">
          <div class="workspace-hero-label">Session</div>
          <div class="workspace-hero-value">${task.session_id ? `#${task.session_id}` : "未绑定"}</div>
        </div>
        <div class="workspace-hero-card">
          <div class="workspace-hero-label">当前步骤</div>
          <div class="workspace-hero-value">${task.current_step ? `步骤 ${task.current_step}` : "未进入"}</div>
        </div>
      `;

      const validationReport = task.validation_report || {};
      const recoveryAction = task.recovery_action || {};
      const deliverableSpec = task.deliverable_spec || {};
      const taskIntent = task.task_intent || {};
      const taskStageExplanation = ctx.describeTaskStage(task, validationReport, recoveryAction);
      const taskNextAction = ctx.describeNextAction(task, validationReport, recoveryAction);
      const validationChecks = Array.isArray(validationReport.checks) ? validationReport.checks : [];
      const failedChecks = validationChecks.filter((item) => item && item.passed === false);
      const clarifyQuestions = (deliverableSpec.clarify || {}).questions || [];
      const waitingClarification = task.status === "waiting_clarification";
      const validationSummary = waitingClarification
        ? "待补信息"
        : validationReport.passed === true
          ? "已通过"
          : validationReport.passed === false
            ? "未通过"
            : "待校验";

      document.getElementById("taskDetail").innerHTML = `
        <div class="top-actions">
          <button class="ghost-btn" onclick="setAppTab('tasks')">回到任务列表</button>
          ${task.session_id ? `<button class="ghost-btn" onclick="openSessionBrowser(${task.session_id})">打开 Session</button>` : ""}
          ${
            recoveryAction && recoveryAction.action && recoveryAction.action !== "none"
              ? recoveryAction.action === "clarify"
                ? `<button class="secondary-btn" onclick="clarifyTask(${task.id})">补充澄清信息</button>`
                : `<button onclick="applyRecoveryAction(${task.id})">应用 Recovery Action</button>`
              : ""
          }
        </div>
        <div class="task-summary-grid">
          <div class="task-summary-card">
            <div class="task-summary-label">当前说明</div>
            <div class="task-summary-value">${ctx.escapeHtml(taskStageExplanation)}</div>
          </div>
          <div class="task-summary-card">
            <div class="task-summary-label">下一步动作</div>
            <div class="task-summary-value">${ctx.escapeHtml(taskNextAction)}</div>
          </div>
          <div class="task-summary-card">
            <div class="task-summary-label">验收状态</div>
            <div class="task-summary-value">${validationSummary}</div>
          </div>
          <div class="task-summary-card">
            <div class="task-summary-label">恢复动作</div>
            <div class="task-summary-value">${ctx.escapeHtml(recoveryAction.action || "none")}</div>
          </div>
        </div>
        <div class="task-summary-grid">
          <div class="task-summary-card">
            <div class="task-summary-label">任务 ID</div>
            <div class="task-summary-value">#${task.id}</div>
          </div>
          <div class="task-summary-card">
            <div class="task-summary-label">当前状态</div>
            <div class="task-summary-value"><span class="status-badge ${ctx.statusClass(task.status)}">${ctx.escapeHtml(ctx.summarizeTaskStatus(task))}</span></div>
          </div>
          <div class="task-summary-card">
            <div class="task-summary-label">绑定 Session</div>
            <div class="task-summary-value">${task.session_id ? `#${task.session_id}` : "无"}</div>
          </div>
          <div class="task-summary-card">
            <div class="task-summary-label">更新时间</div>
            <div class="task-summary-value">${task.updated_at || "-"}</div>
          </div>
          <div class="task-summary-card">
            <div class="task-summary-label">验收状态</div>
            <div class="task-summary-value">${validationSummary}</div>
          </div>
          <div class="task-summary-card">
            <div class="task-summary-label">恢复动作</div>
            <div class="task-summary-value">${ctx.escapeHtml(recoveryAction.action || "none")}</div>
          </div>
        </div>
        <div class="info-row"><span class="label">任务内容：</span>${ctx.escapeHtml(task.display_user_input || task.user_input)}</div>
        ${task.clarification_count ? `<div class="info-row"><span class="label">原始任务：</span>${ctx.escapeHtml(task.original_user_input || task.user_input || "")}</div>` : ""}
        <div class="info-row">
          <span class="label">最终交付：</span>
          <pre data-testid="task-final-deliverable">${ctx.escapeHtml(task.result || (waitingClarification ? "当前尚未进入执行链；请先补充澄清信息。" : "尚未形成最终交付；如果任务仍在运行，可先查看步骤与 traces。"))}</pre>
        </div>
        <div class="info-row"><span class="label">验收摘要：</span>${ctx.escapeHtml(validationReport.summary || "暂无校验摘要")}</div>
        <div class="info-row"><span class="label">恢复建议：</span>${ctx.escapeHtml(recoveryAction.summary || "当前没有恢复动作")}</div>
        <div class="info-row"><span class="label">失败检查：</span><pre>${ctx.escapeHtml(
          failedChecks.length
            ? failedChecks.map((item) => `${item.name}: expected=${JSON.stringify(item.expected)} / actual=${JSON.stringify(item.actual)}`).join("\n")
            : (waitingClarification ? "当前没有系统失败；这是待补信息阻断。" : "当前没有失败检查"),
        )}</pre></div>
        <div class="info-row"><span class="label">待澄清问题：</span><pre>${ctx.escapeHtml((clarifyQuestions || []).join("\n") || "暂无")}</pre></div>
        <details style="margin-top: 12px;">
          <summary>高级视图：Task Intent / Deliverable / Validation / Runtime</summary>
          <div class="info-row"><span class="label">Task Intent：</span><pre>${ctx.escapeHtml(JSON.stringify(taskIntent, null, 2))}</pre></div>
          <div class="info-row"><span class="label">Deliverable Spec：</span><pre>${ctx.escapeHtml(JSON.stringify(deliverableSpec, null, 2))}</pre></div>
          <div class="info-row"><span class="label">Validation Report：</span><pre>${ctx.escapeHtml(JSON.stringify(validationReport, null, 2))}</pre></div>
          <div class="info-row"><span class="label">Recovery Action：</span><pre>${ctx.escapeHtml(JSON.stringify(recoveryAction, null, 2))}</pre></div>
          <div class="info-row"><span class="label">Skill Invocation：</span><pre>${ctx.escapeHtml(JSON.stringify((task.runtime_overrides || {}).skill_invocation || { mode: "default_planner" }, null, 2))}</pre></div>
          <div class="info-row"><span class="label">长期记忆：</span><pre>${ctx.escapeHtml(JSON.stringify(((task.runtime_overrides || {}).memory_context || {}).retrieved_memories || [], null, 2))}</pre></div>
          <div class="info-row"><span class="label">创建时间：</span>${task.created_at || "-"}</div>
          <div class="info-row"><span class="label">错误信息：</span>${task.error_message ? ctx.escapeHtml(task.error_message) : "无"}</div>
        </details>
      `;

      document.getElementById("stepsDetail").innerHTML = renderTaskTimeline(ctx, steps);
      document.getElementById("traceDetail").innerHTML = renderTraceHighlights(ctx, tracePayload, replayPayload);

      const pendingApprovals = approvals.filter((item) => item.status === "pending");
      if (!pendingApprovals.length) {
        document.getElementById("approvalDetail").innerHTML = `<div class="empty">暂无待审批项。当前任务没有被高风险步骤阻塞。</div>`;
      } else {
        document.getElementById("approvalDetail").innerHTML = pendingApprovals
          .map(
            (item) => `
            <div class="approval-card">
              <div class="step-title">审批 #${item.id} / 步骤 ${item.step_order}：${ctx.escapeHtml(item.step_name)}</div>
              <div class="info-row"><span class="label">工具：</span>${ctx.escapeHtml(item.tool_name)}</div>
              <div class="info-row"><span class="label">原因：</span>${ctx.escapeHtml(item.reason)}</div>
              <div class="info-row"><span class="label">输入：</span><pre>${ctx.escapeHtml(item.input_payload || "无")}</pre></div>
              <div class="top-actions">
                <button onclick="decideApproval(${item.id}, true)">批准</button>
                <button class="secondary-btn" onclick="decideApproval(${item.id}, false)">拒绝</button>
              </div>
            </div>
          `,
          )
          .join("");
      }

      document.getElementById("taskAgentsDetail").innerHTML = renderTaskAgentRuns(ctx, taskId, agentRuns, agentDetails);

      if (!task.session_id) {
        document.getElementById("sessionReviewDetail").innerHTML = `<div class="empty">该任务未绑定 session</div>`;
      } else if (!sessionReviews.length) {
        document.getElementById("sessionReviewDetail").innerHTML = `
          <div class="top-actions">
            <button onclick="createSessionReview(${task.session_id})">创建 Review</button>
            <button class="ghost-btn" onclick="openSessionBrowser(${task.session_id})">打开独立 Session 视图</button>
          </div>
          <div class="empty">session #${task.session_id} 暂无 reviews</div>
        `;
      } else {
        document.getElementById("sessionReviewDetail").innerHTML = `
          <div class="top-actions">
            <button onclick="createSessionReview(${task.session_id})">创建 Review</button>
            <button class="ghost-btn" onclick="openSessionBrowser(${task.session_id})">打开独立 Session 视图</button>
          </div>
          ${sessionReviews
            .map(
              (item) => `
            <div class="step-card">
              <div class="step-title">Review #${item.id} / ${ctx.escapeHtml(item.review_kind || "")}</div>
              <div class="info-row"><span class="label">摘要：</span>${ctx.escapeHtml(item.summary_text || "无")}</div>
              <div class="info-row"><span class="label">Open Loops：</span>${ctx.escapeHtml(String((item.open_loops || []).length))}</div>
              <div class="info-row"><span class="label">创建时间：</span>${ctx.escapeHtml(item.created_at || "-")}</div>
              <div class="info-row"><span class="label">Highlights：</span><pre>${ctx.escapeHtml((item.highlights || []).join("\n"))}</pre></div>
            </div>
          `,
            )
            .join("")}
        `;
      }

      if (!task.session_id) {
        document.getElementById("sessionStateDetail").innerHTML = `<div class="empty">该任务未绑定 session</div>`;
      } else if (!sessionState) {
        document.getElementById("sessionStateDetail").innerHTML = `
          <div class="top-actions">
            <button onclick="rebuildSessionState(${task.session_id})">重建 State</button>
            <button class="ghost-btn" onclick="openSessionBrowser(${task.session_id})">打开独立 Session 视图</button>
          </div>
          <div class="empty">session #${task.session_id} 暂无 state</div>
        `;
      } else {
        document.getElementById("sessionStateDetail").innerHTML = `
          <div class="top-actions">
            <button onclick="rebuildSessionState(${task.session_id})">重建 State</button>
            <button class="ghost-btn" onclick="openSessionBrowser(${task.session_id})">打开独立 Session 视图</button>
          </div>
          <div class="step-card">
            <div class="step-title">Session #${task.session_id} Working Memory</div>
            <div class="info-row"><span class="label">摘要：</span>${ctx.escapeHtml(sessionState.summary_text || "无")}</div>
            <div class="info-row"><span class="label">偏好数：</span>${ctx.escapeHtml(String((sessionState.preferences || []).length))}</div>
            <div class="info-row"><span class="label">Open Loops 数：</span>${ctx.escapeHtml(String((sessionState.open_loops || []).length))}</div>
            <div class="info-row"><span class="label">更新时间：</span>${ctx.escapeHtml(sessionState.updated_at || "-")}</div>
            <div class="info-row"><span class="label">Preferences：</span><pre>${ctx.escapeHtml((sessionState.preferences || []).join("\n") || "暂无")}</pre></div>
            <div class="info-row"><span class="label">Open Loops：</span><pre>${ctx.escapeHtml((sessionState.open_loops || []).join("\n") || "暂无")}</pre></div>
          </div>
        `;
      }

      if (!task.session_id) {
        document.getElementById("sessionHealthDetail").innerHTML = `<div class="empty">该任务未绑定 session</div>`;
      } else if (!sessionHealth) {
        document.getElementById("sessionHealthDetail").innerHTML = `<div class="empty">session #${task.session_id} 暂无 health 数据</div>`;
      } else {
        const recommendedActions = sessionHealth.recommended_actions || [];
        document.getElementById("sessionHealthDetail").innerHTML = `
          <div class="top-actions">
            <button class="ghost-btn" onclick="openSessionBrowser(${task.session_id})">打开独立 Session 视图</button>
          </div>
          <div class="step-card">
            <div class="step-title">Session #${task.session_id} Health Snapshot</div>
            <div class="info-row"><span class="label">活跃任务：</span>${ctx.escapeHtml(String(sessionHealth.active_task_count || 0))}</div>
            <div class="info-row"><span class="label">高重要记忆：</span>${ctx.escapeHtml(String(sessionHealth.high_importance_memory_count || 0))}</div>
            <div class="info-row"><span class="label">重复记忆：</span>${ctx.escapeHtml(String(sessionHealth.duplicate_memory_count || 0))}</div>
            <div class="info-row"><span class="label">Open Loops：</span>${ctx.escapeHtml(String(sessionHealth.open_loop_count || 0))}</div>
            <div class="info-row"><span class="label">Reviews：</span>${ctx.escapeHtml(String(sessionHealth.total_reviews || 0))}</div>
            <div class="info-row"><span class="label">State 是否过期：</span>${sessionHealth.state_is_stale ? "是" : "否"}</div>
            <div class="info-row"><span class="label">今日 Daily Review：</span>${sessionHealth.daily_review_today ? "已覆盖" : "未覆盖"}</div>
            ${ctx.renderSessionRecommendedActions(task.session_id, recommendedActions)}
          </div>
        `;
      }
    } catch (err) {
      ctx.currentTaskSnapshot = null;
      window.currentTaskAgentSummary = null;
      document.getElementById("workspaceHero").innerHTML = `
        <div class="workspace-hero-card">
          <div class="workspace-hero-label">当前任务</div>
          <div class="workspace-hero-value">读取失败</div>
        </div>
        <div class="workspace-hero-card">
          <div class="workspace-hero-label">状态</div>
          <div class="workspace-hero-value">-</div>
        </div>
        <div class="workspace-hero-card">
          <div class="workspace-hero-label">下一步</div>
          <div class="workspace-hero-value">-</div>
        </div>
        <div class="workspace-hero-card">
          <div class="workspace-hero-label">Session</div>
          <div class="workspace-hero-value">-</div>
        </div>
        <div class="workspace-hero-card">
          <div class="workspace-hero-label">当前步骤</div>
          <div class="workspace-hero-value">-</div>
        </div>
      `;
      document.getElementById("taskDetail").innerHTML = `<div class="empty">${ctx.escapeHtml(err.message)}</div>`;
      document.getElementById("stepsDetail").innerHTML = `<div class="empty">读取步骤失败</div>`;
      document.getElementById("traceDetail").innerHTML = `<div class="empty">读取 traces 失败</div>`;
      document.getElementById("approvalDetail").innerHTML = `<div class="empty">读取审批失败</div>`;
      document.getElementById("taskAgentsDetail").innerHTML = `<div class="empty">读取 agent runs 失败</div>`;
      document.getElementById("sessionReviewDetail").innerHTML = `<div class="empty">读取 session reviews 失败</div>`;
      document.getElementById("sessionStateDetail").innerHTML = `<div class="empty">读取 session state 失败</div>`;
      document.getElementById("sessionHealthDetail").innerHTML = `<div class="empty">读取 session health 失败</div>`;
    }
  }

  async function applyRecoveryAction(ctx, taskId) {
    const note = window.prompt("请输入恢复备注（可留空）", "") ?? "";
    try {
      await ctx.fetchJson(`${ctx.API_BASE}/tasks/${taskId}/apply-recovery-action`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ note }),
      });
      await selectTask(ctx, taskId, { focusWorkspace: true, workspaceTab: "overview" });
      await loadTasks(ctx);
      await ctx.loadMonitorOverview();
      ctx.showToast(`任务 #${taskId} 已触发恢复动作`, "success");
    } catch (err) {
      ctx.showToast("恢复动作执行失败", "error");
      alert(err.message);
    }
  }

  async function clarifyTask(ctx, taskId) {
    const clarification = window.prompt("请输入补充说明（必填）", "") ?? "";
    if (!clarification.trim()) {
      alert("补充说明不能为空");
      return;
    }
    const note = window.prompt("请输入 clarification 备注（可留空）", "") ?? "";
    try {
      await ctx.fetchJson(`${ctx.API_BASE}/tasks/${taskId}/clarify`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ clarification, note }),
      });
      await selectTask(ctx, taskId, { focusWorkspace: true, workspaceTab: "overview" });
      await loadTasks(ctx);
      await ctx.loadMonitorOverview();
      ctx.showToast(`任务 #${taskId} 已提交 Clarification`, "success");
    } catch (err) {
      ctx.showToast("Clarification 提交失败", "error");
      alert(err.message);
    }
  }

  async function bootstrapTaskAgentRuns(ctx, taskId) {
    const objective = window.prompt("请输入 agent bootstrap 的目标（留空则使用当前任务内容）", "") ?? "";
    const specialistRaw = window.prompt("请输入 specialist 数量（1-4）", "2") ?? "2";
    const specialistCount = Math.max(1, Math.min(4, parseInt(specialistRaw, 10) || 2));
    const includeReviewer = window.confirm("是否同时创建 reviewer 占位？\n选择“确定”会创建 reviewer，“取消”则只创建 manager + specialists。");
    const note = window.prompt("请输入 bootstrap 备注（可留空）", "") ?? "";

    try {
      await ctx.fetchJson(`${ctx.API_BASE}/tasks/${taskId}/agent-runs/bootstrap-demo`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          objective,
          specialist_count: specialistCount,
          include_reviewer: includeReviewer,
          note,
        }),
      });
      await selectTask(ctx, taskId, { focusWorkspace: true, workspaceTab: "agents" });
      await ctx.loadMonitorOverview();
    } catch (err) {
      alert(err.message);
    }
  }

  async function executeTaskAgentRuns(ctx, taskId) {
    const note = window.prompt("请输入 execute 备注（可留空）", "") ?? "";

    try {
      await ctx.fetchJson(`${ctx.API_BASE}/tasks/${taskId}/agent-runs/execute-demo`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          note,
        }),
      });
      await selectTask(ctx, taskId, { focusWorkspace: true, workspaceTab: "agents" });
      await ctx.loadMonitorOverview();
    } catch (err) {
      alert(err.message);
    }
  }

  async function executeTaskAgentRunsViaWorker(ctx, taskId) {
    const note = window.prompt("请输入 worker execute 备注（可留空）", "") ?? "";

    try {
      await ctx.fetchJson(`${ctx.API_BASE}/tasks/${taskId}/agent-runs/execute-worker-demo`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          note,
        }),
      });
      await selectTask(ctx, taskId, { focusWorkspace: true, workspaceTab: "agents" });
      await ctx.loadMonitorOverview();
    } catch (err) {
      alert(err.message);
    }
  }

  async function rerunTaskAgentRuns(ctx, taskId) {
    const note = window.prompt("请输入重跑备注（可留空）", "") ?? "";
    const forceRerun = window.confirm("是否强制重跑 Specialists？\n确定=force_rerun，取消=普通执行。");

    try {
      await ctx.fetchJson(`${ctx.API_BASE}/tasks/${taskId}/agent-runs/execute-demo`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          note,
          force_rerun: forceRerun,
        }),
      });
      await selectTask(ctx, taskId, { focusWorkspace: true, workspaceTab: "agents" });
      await ctx.loadMonitorOverview();
    } catch (err) {
      alert(err.message);
    }
  }

  async function finalizeTaskAgentRuns(ctx, taskId) {
    const summary = window.prompt("请输入 final artifact 摘要（留空则使用默认汇总）", "") ?? "";
    const note = window.prompt("请输入 finalize 备注（可留空）", "") ?? "";
    const reviewerDecisionRaw = window.prompt("请输入 reviewer 决策：auto / approved / rework_required / rejected（回车默认 auto）", "auto") ?? "auto";
    const reviewerDecision = ["auto", "approved", "rework_required", "rejected"].includes(reviewerDecisionRaw.trim()) ? reviewerDecisionRaw.trim() : "auto";
    const allowRetry = window.confirm("是否允许 rework_required 后继续重跑 Specialists？");

    try {
      await ctx.fetchJson(`${ctx.API_BASE}/tasks/${taskId}/agent-runs/finalize-demo`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          summary,
          note,
          reviewer_decision: reviewerDecision,
          allow_retry: allowRetry,
        }),
      });
      await selectTask(ctx, taskId, { focusWorkspace: true, workspaceTab: "agents" });
      await ctx.loadMonitorOverview();
    } catch (err) {
      alert(err.message);
    }
  }

  async function decideApproval(ctx, approvalId, approved) {
    const note = window.prompt(approved ? "请输入批准备注（可留空）" : "请输入拒绝原因", "");
    if (note === null) return;

    const path = approved ? "approve" : "reject";
    try {
      await ctx.fetchJson(`${ctx.API_BASE}/approvals/${approvalId}/${path}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ note }),
      });

      if (ctx.selectedTaskId !== null) {
        await selectTask(ctx, ctx.selectedTaskId);
      } else {
        await loadTasks(ctx);
      }
      ctx.showToast(`审批 #${approvalId} 已${approved ? "批准" : "拒绝"}`, "success");
    } catch (err) {
      ctx.showToast("审批操作失败", "error");
      alert(err.message);
    }
  }

  window.DashboardWorkspace = {
    applyRecoveryAction,
    bootstrapTaskAgentRuns,
    clarifyTask,
    decideApproval,
    executeTaskAgentRuns,
    executeTaskAgentRunsViaWorker,
    finalizeTaskAgentRuns,
    loadTasks,
    renderStage5TaskChips,
    renderTaskAgentRuns,
    renderTaskTimeline,
    renderTasksView,
    renderTaskTraces,
    renderTaskReplay,
    renderTraceCardList,
    renderTraceHighlights,
    renderTraceMetaRows,
    renderTraceSummary,
    renderWorkspaceLoadingState,
    rerunTaskAgentRuns,
    selectTask,
    buildWorkflowProposalModelRouteTemplate,
    buildWorkflowProposalSandboxFileTemplate,
    formatWorkflowProposalLabel,
    renderWorkflowProposalTemplateActions,
  };
})();
