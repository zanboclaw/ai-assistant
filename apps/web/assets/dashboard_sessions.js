(function () {
  function renderSessionsList(ctx) {
    const sessionList = document.getElementById("sessionList");
    if (!sessionList) {
      return;
    }

    if (!ctx.sessions.length) {
      sessionList.innerHTML = `<div class="empty">暂无 sessions</div>`;
      const detail = document.getElementById("sessionBrowserDetail");
      if (detail) {
        detail.innerHTML = `<div class="empty">当前没有可查看的 session</div>`;
      }
      ctx.sessionBrowserSnapshot = null;
      return;
    }

    sessionList.innerHTML = ctx.sessions.map((session) => `
      <div class="task-card ${session.id === ctx.selectedSessionId ? "active" : ""}" onclick="selectSession(${session.id})">
        <div class="task-title">#${session.id} ${ctx.escapeHtml(session.name || "未命名 session")}</div>
        <div class="task-meta">${ctx.escapeHtml(session.description || "无描述")}</div>
        <div class="task-meta">更新时间：${ctx.escapeHtml(session.updated_at || "-")}</div>
      </div>
    `).join("");
  }

  async function loadSessions(ctx, options = {}) {
    const reloadDetail = options.reloadDetail !== false;
    try {
      ctx.sessions = await ctx.fetchJson(`${ctx.API_BASE}/sessions`);
      renderSessionsList(ctx);

      if (!ctx.sessions.length) {
        ctx.selectedSessionId = null;
        window.localStorage.removeItem("ai-assistant-session-browser");
        return;
      }

      if (ctx.selectedSessionId === null || !ctx.sessions.some((item) => item.id === ctx.selectedSessionId)) {
        ctx.selectedSessionId = ctx.sessions[0].id;
        window.localStorage.setItem("ai-assistant-session-browser", String(ctx.selectedSessionId));
      }

      if (reloadDetail) {
        await loadSessionBrowserDetail(ctx, ctx.selectedSessionId);
      }
    } catch (err) {
      const sessionList = document.getElementById("sessionList");
      if (sessionList) {
        sessionList.innerHTML = `<div class="empty">${ctx.escapeHtml(err.message)}</div>`;
      }
    }
  }

  function selectSession(ctx, sessionId, focusTab = false) {
    ctx.selectedSessionId = sessionId;
    window.localStorage.setItem("ai-assistant-session-browser", String(sessionId));
    renderSessionsList(ctx);

    if (focusTab) {
      ctx.setAppTab("sessions");
    }

    void loadSessionBrowserDetail(ctx, sessionId);
  }

  function openSessionBrowser(ctx, sessionId) {
    selectSession(ctx, sessionId, true);
  }

  async function loadSessionBrowserDetail(ctx, sessionId) {
    const detailEl = document.getElementById("sessionBrowserDetail");
    if (!detailEl) {
      return;
    }

    const token = ctx.nextSessionBrowserRequestToken();
    detailEl.innerHTML = `<div class="empty">正在加载 session #${sessionId}…</div>`;

    try {
      const [summary, reviews] = await Promise.all([
        ctx.fetchJson(`${ctx.API_BASE}/sessions/${sessionId}/summary`),
        ctx.fetchJson(`${ctx.API_BASE}/sessions/${sessionId}/reviews?limit=5`)
      ]);
      if (token !== ctx.sessionBrowserRequestToken) {
        return;
      }

      const session = summary.session || { id: sessionId };
      const health = summary.health || {};
      const state = summary.session_state || {};
      const recentTasks = summary.recent_tasks || [];
      const recommendedActions = health.recommended_actions || [];
      const latestTask = recentTasks[0];
      ctx.sessionBrowserSnapshot = {
        sessionId,
        session,
        summary,
        reviews,
      };

      detailEl.innerHTML = `
        <div class="session-detail-stack">
          <div class="session-detail-head">
            <div>
              <div class="panel-title">#${session.id} ${ctx.escapeHtml(session.name || "未命名 session")}</div>
              <div class="panel-subtitle">${ctx.escapeHtml(session.description || "无描述")} · 创建于 ${ctx.escapeHtml(session.created_at || "-")} · 更新于 ${ctx.escapeHtml(session.updated_at || "-")}</div>
            </div>
            <div class="top-actions">
              <button class="ghost-btn" onclick="loadSessions()">刷新当前 Session</button>
              ${latestTask ? `<button class="ghost-btn" onclick="selectTask(${latestTask.id}, { focusWorkspace: true })">打开最新任务</button>` : ""}
              <button class="ghost-btn" onclick="createSessionReview(${sessionId})">创建 Review</button>
              <button class="ghost-btn" onclick="editSessionState(${sessionId})">编辑 State</button>
              <button class="ghost-btn" onclick="rebuildSessionState(${sessionId})">重建 State</button>
            </div>
          </div>

          <div class="task-summary-grid">
            <div class="task-summary-card">
              <div class="task-summary-label">Tasks</div>
              <div class="task-summary-value">${ctx.escapeHtml(String(summary.task_metrics?.total_tasks || 0))}</div>
            </div>
            <div class="task-summary-card">
              <div class="task-summary-label">Memories</div>
              <div class="task-summary-value">${ctx.escapeHtml(String(summary.memory_metrics?.total_memories || 0))}</div>
            </div>
            <div class="task-summary-card">
              <div class="task-summary-label">Pending Approvals</div>
              <div class="task-summary-value">${ctx.escapeHtml(String(summary.approval_metrics?.pending_approvals || 0))}</div>
            </div>
            <div class="task-summary-card">
              <div class="task-summary-label">Recent Task</div>
              <div class="task-summary-value">${latestTask ? `#${latestTask.id}` : "无"}</div>
            </div>
          </div>

          <div class="session-health-grid">
            <div class="session-health-card">
              <div class="session-health-label">Active Tasks</div>
              <div class="session-health-value">${ctx.escapeHtml(String(health.active_task_count || 0))}</div>
            </div>
            <div class="session-health-card">
              <div class="session-health-label">Reviews</div>
              <div class="session-health-value">${ctx.escapeHtml(String(health.total_reviews || 0))}</div>
            </div>
            <div class="session-health-card">
              <div class="session-health-label">Open Loops</div>
              <div class="session-health-value">${ctx.escapeHtml(String(health.open_loop_count || 0))}</div>
            </div>
            <div class="session-health-card">
              <div class="session-health-label">State Stale</div>
              <div class="session-health-value">${health.state_is_stale ? "是" : "否"}</div>
            </div>
          </div>
          ${renderSessionRecommendedActions(ctx, sessionId, recommendedActions)}

          <div class="session-detail-grid">
            <div class="panel" style="margin-bottom: 0;">
              <div class="panel-title">Summary</div>
              <div class="panel-subtitle">任务、记忆和 review 汇总。</div>
              <div class="info-row"><span class="label">任务分布：</span>${ctx.escapeHtml(
                Object.entries(summary.task_metrics?.tasks_by_status || {})
                  .map(([status, count]) => `${status}=${count}`)
                  .join(" / ") || "暂无"
              )}</div>
              <div class="info-row"><span class="label">记忆分布：</span>${ctx.escapeHtml(
                Object.entries(summary.memory_metrics?.by_category || {})
                  .map(([category, count]) => `${category}=${count}`)
                  .join(" / ") || "暂无"
              )}</div>
              <div class="info-row"><span class="label">State 摘要：</span>${ctx.escapeHtml(state.summary_text || "暂无")}</div>
              <div class="info-row"><span class="label">推荐动作：</span><pre>${ctx.escapeHtml(
                recommendedActions.length
                  ? recommendedActions.map((item) => `${item.action}: ${item.reason}`).join("\n")
                  : "当前没有明显阻塞"
              )}</pre></div>
              <div class="info-row"><span class="label">最近任务：</span>
                <pre>${ctx.escapeHtml(
                  recentTasks.length
                    ? recentTasks.map((item) => `#${item.id} ${item.status || ""} | ${item.display_user_input || item.user_input || ""}`).join("\n")
                    : "暂无任务"
                )}</pre>
              </div>
            </div>

            <div class="panel" style="margin-bottom: 0;">
              <div class="panel-title">Health / State</div>
              <div class="panel-subtitle">查看 working memory、健康信号和今日 review 覆盖。</div>
              <div class="info-row"><span class="label">Health：</span>${ctx.escapeHtml(
                `active=${health.active_task_count || 0} / reviews=${health.total_reviews || 0} / stale=${health.state_is_stale ? "yes" : "no"} / open_loops=${health.open_loop_count || 0}`
              )}</div>
              <div class="info-row"><span class="label">今日 Daily Review：</span>${health.daily_review_today ? "已覆盖" : "未覆盖"}</div>
              <div class="info-row"><span class="label">Preferences：</span><pre>${ctx.escapeHtml((state.preferences || []).join("\n") || "暂无")}</pre></div>
              <div class="info-row"><span class="label">Open Loops：</span><pre>${ctx.escapeHtml((state.open_loops || []).join("\n") || "暂无")}</pre></div>
            </div>
          </div>

          <div class="panel" style="margin-bottom: 0;">
            <div class="panel-title">Reviews</div>
            <div class="panel-subtitle">最近的 session reviews。</div>
            ${
              reviews.length
                ? reviews.map((item) => `
                  <div class="step-card">
                    <div class="step-title">Review #${item.id} / ${ctx.escapeHtml(item.review_kind || "")}</div>
                    <div class="info-row"><span class="label">摘要：</span>${ctx.escapeHtml(item.summary_text || "无")}</div>
                    <div class="info-row"><span class="label">Open Loops：</span>${ctx.escapeHtml(String((item.open_loops || []).length))}</div>
                    <div class="info-row"><span class="label">创建时间：</span>${ctx.escapeHtml(item.created_at || "-")}</div>
                    <div class="info-row"><span class="label">Highlights：</span><pre>${ctx.escapeHtml((item.highlights || []).join("\n") || "暂无")}</pre></div>
                  </div>
                `).join("")
                : `<div class="empty">暂无 reviews</div>`
            }
          </div>
        </div>
      `;
    } catch (err) {
      if (token !== ctx.sessionBrowserRequestToken) {
        return;
      }
      detailEl.innerHTML = `<div class="empty">${ctx.escapeHtml(err.message)}</div>`;
    }
  }

  async function refreshSelectedSessionBrowser(ctx, sessionId) {
    if (ctx.selectedSessionId !== sessionId) {
      return;
    }
    await loadSessionBrowserDetail(ctx, sessionId);
    await loadSessions(ctx, { reloadDetail: false });
  }

  function renderSessionRecommendedActions(ctx, sessionId, recommendedActions = []) {
    const actions = Array.isArray(recommendedActions) ? recommendedActions : [];
    if (!actions.length) {
      return "";
    }

    const actionMeta = {
      create_review: {
        label: "创建 Review",
        handler: `createSessionReview(${sessionId})`,
      },
      rebuild_state: {
        label: "重建 State",
        handler: `rebuildSessionState(${sessionId})`,
      },
      run_daily_review: {
        label: "运行 Daily Review",
        handler: `runDailyReviews(${sessionId})`,
      },
    };

    const buttons = actions
      .map((item) => {
        const meta = actionMeta[item.action];
        if (!meta) {
          return "";
        }
        const title = item.reason ? ` title="${ctx.escapeHtml(item.reason)}"` : "";
        return `<button type="button" class="session-action-chip ghost-btn" onclick="${meta.handler}"${title}>${ctx.escapeHtml(meta.label)}</button>`;
      })
      .filter(Boolean)
      .join("");

    if (!buttons) {
      return "";
    }

    return `
      <div class="info-row">
        <span class="label">建议动作：</span>
        <div class="session-action-row">${buttons}</div>
      </div>
    `;
  }

  function renderMemorySearchResults(ctx, query, rows = []) {
    const container = document.getElementById("memorySearchResult");
    if (!container) {
      return;
    }
    ctx.lastMemorySearchQuery = query || "";
    if (!rows.length) {
      container.innerHTML = query
        ? `<div class="empty">未找到与“${ctx.escapeHtml(query)}”相关的长期记忆。</div>`
        : `<div class="empty">输入检索词后显示长期记忆结果。</div>`;
      return;
    }

    container.innerHTML = rows.map((item, index) => {
      const metadata = item.metadata || {};
      const matchedKeywords = Array.isArray(metadata.matched_keywords) ? metadata.matched_keywords : [];
      const explanation = metadata.match_explanation || metadata.reason || metadata.retrieval_reason || "";
      const citationHint = metadata.citation_hint || "可在任务详情中引用为历史经验来源";
      return `
        <div class="step-card memory-search-card" data-testid="memory-search-card">
          <div class="step-title">${index + 1}. ${ctx.escapeHtml(item.title || "未命名记忆")}</div>
          <div class="info-row"><span class="label">类型：</span>${ctx.escapeHtml(item.memory_kind || "memory")}</div>
          <div class="info-row"><span class="label">命中原因：</span>${ctx.escapeHtml(explanation || "关键词与内容相关")}</div>
          <div class="info-row"><span class="label">匹配关键词：</span>${ctx.escapeHtml(matchedKeywords.join(", ") || "未返回")}</div>
          <div class="info-row"><span class="label">引用建议：</span>${ctx.escapeHtml(citationHint)}</div>
          <div class="info-row"><span class="label">内容：</span><pre>${ctx.escapeHtml(item.content || "")}</pre></div>
        </div>
      `;
    }).join("");
  }

  async function searchLongTermMemories(ctx, options = {}) {
    const input = document.getElementById("memorySearchInput");
    if (!input) {
      return;
    }
    let query = input.value.trim();
    if (options.useSelectedTask && !query) {
      const taskValue = document.querySelector("[data-testid='task-final-deliverable']");
      const taskSummary = document.querySelector("#taskDetail .info-row");
      query = ((taskSummary && taskSummary.textContent) || (taskValue && taskValue.textContent) || "").trim();
      if (query) {
        input.value = query;
      }
    }

    if (!query) {
      renderMemorySearchResults(ctx, "", []);
      ctx.setMemorySearchMessage("请输入检索词，或先选择一个任务后再用当前任务搜索。", true);
      return;
    }

    try {
      ctx.setMemorySearchMessage(`正在检索“${query}”相关的长期记忆…`);
      const params = new URLSearchParams({ query, limit: "5" });
      const rows = await ctx.fetchJson(`${ctx.API_BASE}/memories/search?${params.toString()}`);
      renderMemorySearchResults(ctx, query, Array.isArray(rows) ? rows : []);
      ctx.setMemorySearchMessage(`已完成长期记忆检索：${query}`);
    } catch (err) {
      renderMemorySearchResults(ctx, query, []);
      ctx.setMemorySearchMessage(`长期记忆检索失败：${err.message}`, true);
    }
  }

  async function createSessionReview(ctx, sessionId) {
    const note = window.prompt("请输入 review 备注（可留空）", "") ?? "";
    try {
      await ctx.fetchJson(`${ctx.API_BASE}/sessions/${sessionId}/reviews`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ review_kind: "manual", note })
      });
      if (ctx.selectedTaskId !== null) {
        await ctx.selectTask(ctx.selectedTaskId);
      }
      await refreshSelectedSessionBrowser(ctx, sessionId);
      await ctx.loadMonitorOverview();
      ctx.showToast(`Session #${sessionId} Review 已创建`, "success");
    } catch (err) {
      ctx.showToast("创建 Session Review 失败", "error");
      alert(err.message);
    }
  }

  async function editSessionState(ctx, sessionId) {
    try {
      const currentState = ctx.sessionBrowserSnapshot?.sessionId === sessionId
        ? (ctx.sessionBrowserSnapshot.summary?.session_state || {})
        : (await ctx.fetchJson(`${ctx.API_BASE}/sessions/${sessionId}/summary`)).session_state || {};
      const summaryText = window.prompt("请输入 summary_text", currentState.summary_text || "");
      if (summaryText === null) return;
      const preferencesText = window.prompt(
        "请输入 preferences JSON 数组",
        JSON.stringify(currentState.preferences || [], null, 2)
      );
      if (preferencesText === null) return;
      const openLoopsText = window.prompt(
        "请输入 open_loops JSON 数组",
        JSON.stringify(currentState.open_loops || [], null, 2)
      );
      if (openLoopsText === null) return;

      let preferences = [];
      let openLoops = [];
      try {
        preferences = preferencesText.trim() ? JSON.parse(preferencesText) : [];
        openLoops = openLoopsText.trim() ? JSON.parse(openLoopsText) : [];
      } catch (err) {
        alert(`JSON 解析失败: ${err.message}`);
        return;
      }

      await ctx.fetchJson(`${ctx.API_BASE}/sessions/${sessionId}/state`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          summary_text: summaryText,
          preferences,
          open_loops: openLoops
        })
      });

      if (ctx.selectedTaskId !== null) {
        await ctx.selectTask(ctx.selectedTaskId);
      }
      await refreshSelectedSessionBrowser(ctx, sessionId);
      await ctx.loadMonitorOverview();
    } catch (err) {
      alert(err.message);
    }
  }

  async function rebuildSessionState(ctx, sessionId) {
    try {
      await ctx.fetchJson(`${ctx.API_BASE}/sessions/${sessionId}/state/rebuild`, {
        method: "POST"
      });
      if (ctx.selectedTaskId !== null) {
        await ctx.selectTask(ctx.selectedTaskId);
      }
      await refreshSelectedSessionBrowser(ctx, sessionId);
      await ctx.loadMonitorOverview();
    } catch (err) {
      alert(err.message);
    }
  }

  window.DashboardSessions = {
    renderSessionsList,
    loadSessions,
    selectSession,
    openSessionBrowser,
    loadSessionBrowserDetail,
    refreshSelectedSessionBrowser,
    renderSessionRecommendedActions,
    renderMemorySearchResults,
    searchLongTermMemories,
    createSessionReview,
    editSessionState,
    rebuildSessionState,
  };
})();
