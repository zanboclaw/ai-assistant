(function () {
  function newDialogueId() {
    return `dialogue_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
  }

  function getCurrentTaskDialogue(ctx) {
    return ctx.taskDialogues.find((thread) => thread.id === ctx.currentTaskDialogueId) || null;
  }

  function summarizeDialogueThread(thread = {}) {
    const turns = ctxSafeArray(thread.turns);
    const lastTurn = turns[turns.length - 1] || null;
    return lastTurn?.text || lastTurn?.summary || thread.title || "未命名任务对话";
  }

  function ctxSafeArray(value) {
    return Array.isArray(value) ? value : [];
  }

  function upsertTaskDialogue(ctx, thread) {
    const previous = ctx.taskDialogues.find((item) => item.id === thread.id) || null;
    const merged = {
      ...previous,
      ...thread,
      createdAt: thread.createdAt || previous?.createdAt || new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };
    const others = ctx.taskDialogues.filter((item) => item.id !== merged.id);
    ctx.taskDialogues = [merged, ...others].sort((a, b) => {
      return new Date(b.updatedAt || 0).getTime() - new Date(a.updatedAt || 0).getTime();
    });
    ctx.persistTaskDialogues();
    renderTaskDialogueList(ctx);
    renderHomeDialogueSummary(ctx);
    return merged;
  }

  function updateCurrentTaskDialogue(ctx, mutator) {
    const current = getCurrentTaskDialogue(ctx);
    if (!current) {
      return null;
    }
    const next = mutator(current);
    return upsertTaskDialogue(ctx, next);
  }

  function addTaskDialogueTurn(ctx, turn) {
    return updateCurrentTaskDialogue(ctx, (thread) => ({
      ...thread,
      title: thread.title || (turn.role === "user" ? String(turn.text || "").slice(0, 40) : thread.title),
      turns: [...ctx.safeArray(thread.turns), { id: `turn_${Date.now()}`, createdAt: new Date().toISOString(), ...turn }],
    }));
  }

  async function ensureTaskDialogueSession(ctx, thread) {
    if (!thread) {
      throw new Error("请先创建一个任务对话");
    }
    if (thread.sessionId) {
      return thread;
    }
    if (!ctx.actorHasPermission(ctx.currentActorName, "operate")) {
      return thread;
    }
    const baseTitle = thread.title || `任务对话 ${ctx.formatDateTime(new Date().toISOString())}`;
    const session = await ctx.fetchJson(`${ctx.API_BASE}/sessions`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        name: baseTitle.slice(0, 60),
        description: "由 Web 任务起草器自动创建，用于承接多轮任务对话上下文。",
      }),
    });
    const updated = upsertTaskDialogue(ctx, {
      ...thread,
      sessionId: session.id,
      title: thread.title || session.name || baseTitle,
    });
    ctx.currentTaskDialogueId = updated.id;
    ctx.persistTaskDialogues();
    return updated;
  }

  function buildDialogueContextInput(ctx, rawInput, thread = null) {
    const text = String(rawInput || "").trim();
    const dialogue = thread || getCurrentTaskDialogue(ctx);
    const turns = ctx.safeArray(dialogue?.turns).slice(-6);
    if (!turns.length) {
      return text;
    }
    const contextLines = turns
      .map((item) => {
        if (item.role === "user") {
          return `用户: ${item.text || ""}`;
        }
        if (item.type === "draft") {
          const preview = (item.draft || {}).draft_preview || {};
          return `系统理解: route=${(item.draft || {}).route_mode || "-"}; goal=${preview.goal_summary || ""}; deliverable=${preview.deliverable_type || ""}`;
        }
        if (item.type === "fast_path") {
          return `系统回答摘要: ${(item.response || {}).answer || ""}`;
        }
        if (item.type === "task_created") {
          return `系统已创建任务 #${item.taskId || "-"}: ${item.summary || ""}`;
        }
        return `${item.role || "system"}: ${item.text || item.summary || ""}`;
      })
      .filter(Boolean);
    if (!contextLines.length) {
      return text;
    }
    return [
      "以下是同一任务对话的历史上下文，请结合这些内容继续理解当前输入：",
      ...contextLines,
      "",
      `当前新的用户输入：${text}`,
    ].join("\n");
  }

  function applyTaskTemplate(ctx, text) {
    const input = document.getElementById("taskInput");
    if (!input) {
      return;
    }
    if (ctx.currentAppTab !== "composer") {
      ctx.setAppTab("composer");
    }
    input.value = text;
    input.focus();
  }

  function renderHomeDialogueSummary(ctx) {
    const container = document.getElementById("homeDialogueSummary");
    if (!container) {
      return;
    }
    if (!ctx.taskDialogues.length) {
      container.innerHTML = `<div class="empty">最近任务对话会显示在这里。</div>`;
      return;
    }
    container.innerHTML = ctx.taskDialogues
      .slice(0, 3)
      .map(
        (thread) => `
        <button type="button" class="deliverable-item" onclick="selectTaskDialogue('${ctx.escapeHtml(thread.id)}', true)">
          <div class="deliverable-item-title">${ctx.escapeHtml(thread.title || summarizeDialogueThread(thread))}</div>
          <div class="deliverable-item-meta">Session ${ctx.escapeHtml(thread.sessionId ? `#${thread.sessionId}` : "未绑定")} · ${ctx.escapeHtml(ctx.formatDateTime(thread.updatedAt))}</div>
        </button>
      `,
      )
      .join("");
  }

  function renderTaskDialogueList(ctx) {
    const container = document.getElementById("taskDialogueList");
    if (!container) {
      return;
    }
    if (!ctx.taskDialogues.length) {
      container.innerHTML = `<div class="empty">还没有任务对话，点击“开始新任务对话”即可。</div>`;
      return;
    }
    if (!getCurrentTaskDialogue(ctx)) {
      ctx.currentTaskDialogueId = ctx.taskDialogues[0].id;
      ctx.persistTaskDialogues();
    }
    container.innerHTML = ctx.taskDialogues
      .map(
        (thread) => `
        <button type="button" class="task-card task-dialogue-card ${thread.id === ctx.currentTaskDialogueId ? "active" : ""}" onclick="selectTaskDialogue('${ctx.escapeHtml(thread.id)}', true)">
          <div class="task-title">${ctx.escapeHtml(thread.title || summarizeDialogueThread(thread))}</div>
          <div class="task-meta">Session：${ctx.escapeHtml(thread.sessionId ? `#${thread.sessionId}` : "未绑定")}</div>
          <div class="task-meta">轮次：${ctx.escapeHtml(String(ctx.safeArray(thread.turns).filter((item) => item.role === "user").length))} / 更新时间：${ctx.escapeHtml(ctx.formatDateTime(thread.updatedAt))}</div>
        </button>
      `,
      )
      .join("");
  }

  function renderCurrentTaskDialogue(ctx) {
    const metaEl = document.getElementById("taskDialogueMeta");
    const timelineEl = document.getElementById("taskDialogueTimeline");
    if (!metaEl || !timelineEl) {
      return;
    }
    const thread = getCurrentTaskDialogue(ctx);
    if (!thread) {
      metaEl.innerHTML = `<div class="empty">请选择或创建一个任务对话。</div>`;
      timelineEl.innerHTML = `<div class="empty">任务对话会显示在这里。</div>`;
      renderTaskDraft(ctx, null);
      return;
    }

    metaEl.innerHTML = `
      <div class="composer-thread-summary">
        <div class="composer-thread-title">${ctx.escapeHtml(thread.title || summarizeDialogueThread(thread))}</div>
        <div class="composer-thread-summary-meta">Session：${ctx.escapeHtml(thread.sessionId ? `#${thread.sessionId}` : "未绑定")} · 创建于 ${ctx.escapeHtml(ctx.formatDateTime(thread.createdAt))} · 更新于 ${ctx.escapeHtml(ctx.formatDateTime(thread.updatedAt))}</div>
      </div>
    `;

    const turns = ctx.safeArray(thread.turns);
    timelineEl.innerHTML = turns.length
      ? turns
          .map((item) => {
            if (item.role === "user") {
              return `
                <div class="dialogue-turn dialogue-user">
                  <div class="dialogue-turn-role">用户</div>
                  <div class="dialogue-turn-body">${ctx.escapeHtml(item.text || "")}</div>
                </div>
              `;
            }
            if (item.type === "draft") {
              const preview = (item.draft || {}).draft_preview || {};
              return `
                <div class="dialogue-turn dialogue-assistant">
                  <div class="dialogue-turn-role">系统理解</div>
                  <div class="dialogue-turn-body">
                    <div class="dialogue-card-title">${ctx.escapeHtml((item.draft || {}).route_mode || "draft_task")}</div>
                    <div class="dialogue-card-text">goal：${ctx.escapeHtml(preview.goal_summary || "-")}</div>
                    <div class="dialogue-card-text">deliverable：${ctx.escapeHtml(preview.deliverable_type || "-")}</div>
                    <div class="dialogue-card-text">acceptance：${ctx.escapeHtml((preview.acceptance_hints || []).join(" / ") || "暂无")}</div>
                  </div>
                </div>
              `;
            }
            if (item.type === "fast_path") {
              return `
                <div class="dialogue-turn dialogue-assistant">
                  <div class="dialogue-turn-role">Fast Path</div>
                  <div class="dialogue-turn-body"><pre>${ctx.escapeHtml((item.response || {}).answer || "")}</pre></div>
                </div>
              `;
            }
            if (item.type === "task_created") {
              return `
                <div class="dialogue-turn dialogue-system">
                  <div class="dialogue-turn-role">正式任务</div>
                  <div class="dialogue-turn-body">
                    <div class="dialogue-card-title">已创建任务 #${ctx.escapeHtml(String(item.taskId || "-"))}</div>
                    <div class="dialogue-card-text">${ctx.escapeHtml(item.summary || "可进入任务工作区继续查看。")}</div>
                    ${item.taskId ? `<div class="top-actions"><button class="ghost-btn" onclick="selectTask(${Number(item.taskId)}, { focusWorkspace: true })">打开任务工作区</button></div>` : ""}
                  </div>
                </div>
              `;
            }
            return `
              <div class="dialogue-turn dialogue-system">
                <div class="dialogue-turn-role">系统</div>
                <div class="dialogue-turn-body">${ctx.escapeHtml(item.text || item.summary || "")}</div>
              </div>
            `;
          })
          .join("")
      : `<div class="empty">这个任务对话还没有内容，先输入一条任务消息吧。</div>`;
  }

  function selectTaskDialogue(ctx, dialogueId, focusComposer = false) {
    ctx.currentTaskDialogueId = dialogueId;
    ctx.persistTaskDialogues();
    renderTaskDialogueList(ctx);
    renderCurrentTaskDialogue(ctx);
    const thread = getCurrentTaskDialogue(ctx);
    if (thread && thread.latestDraft) {
      ctx.currentTaskDraft = thread.latestDraft;
      renderTaskDraft(ctx, thread.latestDraft);
    } else {
      ctx.currentTaskDraft = null;
      renderTaskDraft(ctx, null);
    }
    if (thread && thread.latestFastPath) {
      ctx.currentFastPathAnswer = thread.latestFastPath;
      renderFastPathAnswer(ctx, thread.latestFastPath);
    } else {
      ctx.currentFastPathAnswer = null;
      renderFastPathAnswer(ctx, null);
    }
    if (focusComposer) {
      ctx.setAppTab("composer");
    }
  }

  async function startNewTaskDialogue(ctx, options = {}) {
    let thread = {
      id: newDialogueId(),
      title: "新任务对话",
      sessionId: null,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      turns: [],
      latestDraft: null,
      latestFastPath: null,
    };
    if (ctx.actorHasPermission(ctx.currentActorName, "operate")) {
      try {
        thread = await ensureTaskDialogueSession(ctx, thread);
      } catch (err) {
        ctx.showToast(`创建任务对话 Session 失败：${err.message}`, "error");
      }
    }
    upsertTaskDialogue(ctx, thread);
    ctx.currentTaskDialogueId = thread.id;
    ctx.persistTaskDialogues();
    renderTaskDialogueList(ctx);
    renderCurrentTaskDialogue(ctx);
    renderTaskDraft(ctx, null);
    renderFastPathAnswer(ctx, null);
    const input = document.getElementById("taskInput");
    if (input) {
      if (!options.preserveInputValue) {
        input.value = "";
      }
      input.focus();
    }
    ctx.setAppTab("composer");
    ctx.showToast("已开始新的任务对话", "success");
  }

  async function openComposerAndStartDialogue(ctx) {
    await startNewTaskDialogue(ctx);
  }

  function renderTaskSubmissionState(ctx) {
    const button = document.getElementById("taskSubmitButton");
    const hint = ctx.getActorOperateHint(ctx.currentActorName);
    const canRead = ctx.actorHasPermission(ctx.currentActorName, "read");
    const canOperate = ctx.actorHasPermission(ctx.currentActorName, "operate");
    if (button) {
      button.disabled = !canRead;
      button.title = canRead ? "分析输入并生成草稿" : "当前 actor 无法读取输入路由";
    }
    ctx.setTaskSubmitMessage(
      canOperate
        ? `草稿确认后可创建任务：${hint.text}`
        : `当前 actor 可分析输入，但不能直接创建任务：${hint.text}`,
      !canRead,
    );
    renderTaskDraft(ctx, ctx.currentTaskDraft);
    ctx.renderAppVisibility();
    ctx.renderSettingsView();
    ctx.renderGlobalStatusBar();
  }

  function extractSkillArgKeysFromPackage(packageBody = {}) {
    const text = JSON.stringify(packageBody || {});
    const matches = [...text.matchAll(/\{\{args\.([a-zA-Z0-9_]+)\}\}/g)];
    return [...new Set(matches.map((match) => match[1]).filter(Boolean))];
  }

  function buildSkillDefaultArgs(argKeys = []) {
    const payload = {};
    argKeys.forEach((key) => {
      payload[key] = "";
    });
    return payload;
  }

  function renderTaskSkillOptions(ctx) {
    const select = document.getElementById("taskSkillSelect");
    if (!select) {
      return;
    }
    const previousValue = select.value;
    const activeSkills = ctx.skillRegistry.filter((item) => item.status === "active");
    select.innerHTML = [
      `<option value="">直接按自然语言执行（不显式指定 skill）</option>`,
      ...activeSkills.map(
        (item) =>
          `<option value="${ctx.escapeHtml(item.skill_id)}">${ctx.escapeHtml(item.display_name || item.skill_id)} · ${ctx.escapeHtml(item.skill_id)}@${ctx.escapeHtml(item.latest_version || "-")}</option>`,
      ),
    ].join("");
    select.value = activeSkills.some((item) => item.skill_id === previousValue) ? previousValue : "";
  }

  async function loadSkillDetail(ctx, skillId, version = "") {
    const params = version ? `?version=${encodeURIComponent(version)}` : "";
    return ctx.fetchJson(`${ctx.API_BASE}/skills/${encodeURIComponent(skillId)}${params}`);
  }

  async function syncTaskSkillSelection(ctx) {
    const select = document.getElementById("taskSkillSelect");
    const versionInput = document.getElementById("taskSkillVersion");
    const argsInput = document.getElementById("taskSkillArgs");
    if (!select || !versionInput || !argsInput) {
      return;
    }

    const skillId = select.value;
    if (!skillId) {
      ctx.taskSkillDetail = null;
      versionInput.value = "";
      if (!argsInput.value.trim()) {
        argsInput.value = "";
      }
      ctx.setTaskSkillMessage("当前未显式指定 skill，任务会走默认 planner。");
      return;
    }

    ctx.setTaskSkillMessage(`正在加载 skill ${skillId} ...`);
    try {
      const detail = await loadSkillDetail(ctx, skillId);
      ctx.taskSkillDetail = detail;
      const versionInfo = detail.version || {};
      const packageBody = versionInfo.package_body || {};
      const argKeys = extractSkillArgKeysFromPackage(packageBody);
      versionInput.value = versionInfo.version || "";
      if (!argsInput.value.trim()) {
        argsInput.value = JSON.stringify(buildSkillDefaultArgs(argKeys), null, 2);
      }
      ctx.setTaskSkillMessage(
        `已选择 skill：${(detail.skill || {}).display_name || skillId} @ ${versionInfo.version || "-"}；建议 args：${argKeys.length ? argKeys.join(", ") : "无显式占位参数"}`,
      );
    } catch (err) {
      ctx.taskSkillDetail = null;
      versionInput.value = "";
      ctx.setTaskSkillMessage(`读取 skill 详情失败：${err.message}`, true);
    }
  }

  async function changeTaskSkillSelection(ctx) {
    await syncTaskSkillSelection(ctx);
  }

  async function applySkillToTask(ctx, skillId) {
    const select = document.getElementById("taskSkillSelect");
    if (!select) {
      return;
    }
    select.value = skillId;
    await syncTaskSkillSelection(ctx);
    ctx.setAppTab("tasks");
    select.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  function getRouteModeLabel(routeMode) {
    if (routeMode === "fast_path") {
      return "快速路径";
    }
    if (routeMode === "clarify_first") {
      return "先 clarify";
    }
    return "草稿确认";
  }

  function renderTaskDraft(ctx, draft = null) {
    const container = document.getElementById("taskDraftDetail");
    if (!container) {
      return;
    }
    ctx.currentTaskDraft = draft || null;
    renderFastPathAnswer(ctx, null);
    if (!draft) {
      container.innerHTML = `<div class="empty">输入后先在这里看系统理解，再决定是否创建正式任务。</div>`;
      return;
    }

    const preview = draft.draft_preview || {};
    const memoryContext = draft.memory_context || {};
    const retrievedMemories = Array.isArray(memoryContext.retrieved_memories) ? memoryContext.retrieved_memories : [];
    const canOperate = ctx.actorHasPermission(ctx.currentActorName, "operate");
    const confirmLabel =
      draft.route_mode === "fast_path"
        ? "按快速路径创建任务"
        : draft.route_mode === "clarify_first"
          ? "创建任务并进入 Clarify"
          : "确认创建正式任务";

    container.innerHTML = `
      <div class="step-card" data-testid="task-draft-card">
        <div class="step-title" data-testid="task-draft-route">${ctx.escapeHtml(getRouteModeLabel(draft.route_mode || "draft_task"))}</div>
        <div class="task-summary-grid">
          <div class="task-summary-card">
            <div class="task-summary-label">route_reason</div>
            <div class="task-summary-value">${ctx.escapeHtml(draft.route_reason || "无")}</div>
          </div>
          <div class="task-summary-card">
            <div class="task-summary-label">goal_summary</div>
            <div class="task-summary-value">${ctx.escapeHtml(preview.goal_summary || "-")}</div>
          </div>
          <div class="task-summary-card">
            <div class="task-summary-label">task_type</div>
            <div class="task-summary-value">${ctx.escapeHtml(preview.task_type || "-")}</div>
          </div>
          <div class="task-summary-card">
            <div class="task-summary-label">deliverable_type</div>
            <div class="task-summary-value">${ctx.escapeHtml(preview.deliverable_type || "-")}</div>
          </div>
        </div>
        <div class="info-row"><span class="label">needs_clarification：</span>${preview.needs_clarification ? "是" : "否"}</div>
        <div class="info-row"><span class="label">acceptance_hints：</span><pre>${ctx.escapeHtml((preview.acceptance_hints || []).join("\n") || "暂无")}</pre></div>
        <div class="info-row"><span class="label">clarify_questions：</span><pre>${ctx.escapeHtml((preview.clarification_questions || []).join("\n") || "暂无")}</pre></div>
        <div class="info-row"><span class="label">Task Intent：</span><pre>${ctx.escapeHtml(JSON.stringify(draft.task_intent || {}, null, 2))}</pre></div>
        <div class="info-row"><span class="label">Deliverable Spec：</span><pre>${ctx.escapeHtml(JSON.stringify(draft.deliverable_spec || {}, null, 2))}</pre></div>
        <div class="info-row"><span class="label">长期记忆召回：</span><pre>${ctx.escapeHtml(
          ctx.formatRetrievedMemoriesForDisplay(retrievedMemories, { includeCitationHint: true }),
        )}</pre></div>
        <div class="top-actions">
          ${draft.route_mode === "fast_path" ? `<button class="ghost-btn" data-testid="fast-path-answer-button" onclick="runFastPathAnswer()">先直接回答</button>` : ""}
          <button data-testid="task-confirm-button" onclick="confirmTaskDraft()" ${canOperate ? "" : "disabled"}>${ctx.escapeHtml(confirmLabel)}</button>
          <button class="ghost-btn" onclick="renderTaskDraft(null)">清空草稿</button>
        </div>
      </div>
    `;
  }

  function renderFastPathAnswer(ctx, response = null) {
    const container = document.getElementById("fastPathAnswerDetail");
    ctx.currentFastPathAnswer = response || null;
    if (!container) {
      return;
    }
    if (!response) {
      container.innerHTML = `<div class="empty">当输入被判定为 fast_path 时，这里会显示轻量回答结果。</div>`;
      return;
    }
    const memoryContext = response.memory_context || {};
    const retrievedMemories = Array.isArray(memoryContext.retrieved_memories) ? memoryContext.retrieved_memories : [];
    container.innerHTML = `
      <div class="step-card" data-testid="fast-path-answer-card">
        <div class="step-title">Fast Path 轻量回答</div>
        <div class="info-row"><span class="label">回答：</span><pre>${ctx.escapeHtml(response.answer || "")}</pre></div>
        <div class="info-row"><span class="label">召回记忆：</span><pre>${ctx.escapeHtml(
          ctx.formatRetrievedMemoriesForDisplay(retrievedMemories, { includeContent: false, includeCitationHint: true }),
        )}</pre></div>
        <div class="info-row"><span class="label">升级建议：</span>${ctx.escapeHtml(((response.promote_to_task || {}).reason) || "需要正式留痕时再升级为任务")}</div>
      </div>
    `;
  }

  async function runFastPathAnswer(ctx) {
    try {
      if (!ctx.currentTaskDraft) {
        throw new Error("请先分析输入并生成草稿");
      }
      const requestPayload = ctx.currentTaskDraft._request_payload || {};
      const payload = {
        user_input: requestPayload.contextual_user_input || requestPayload.raw_user_input || "",
        session_id: requestPayload.session_id || undefined,
        skill_id: requestPayload.skill_id || undefined,
        skill_version: requestPayload.skill_version || undefined,
        skill_args: requestPayload.skill_args || undefined,
      };
      const response = await ctx.fetchJson(`${ctx.API_BASE}/chat/fast-path`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });
      updateCurrentTaskDialogue(ctx, (thread) => ({
        ...thread,
        latestFastPath: response,
        turns: [
          ...ctx.safeArray(thread.turns),
          {
            id: `turn_${Date.now()}_fastpath`,
            role: "assistant",
            type: "fast_path",
            createdAt: new Date().toISOString(),
            response,
          },
        ],
      }));
      renderFastPathAnswer(ctx, response);
      renderCurrentTaskDialogue(ctx);
      ctx.setTaskSubmitMessage("已生成 fast_path 轻量回答；如需留痕与回放，再创建正式任务。");
      ctx.showToast("已生成 Fast Path 回答", "success");
    } catch (err) {
      renderFastPathAnswer(ctx, null);
      ctx.setTaskSubmitMessage(`fast_path 回答失败：${err.message}`, true);
      ctx.showToast("Fast Path 回答失败", "error");
    }
  }

  function parseTaskDraftPayload(ctx, options = {}) {
    const input = document.getElementById("taskInput");
    const taskSkillSelect = document.getElementById("taskSkillSelect");
    const taskSkillVersion = document.getElementById("taskSkillVersion");
    const taskSkillArgs = document.getElementById("taskSkillArgs");
    const rawUserInput = String(options.rawUserInput || input.value || "").trim();
    if (!rawUserInput) {
      throw new Error("请输入任务内容");
    }

    const thread = options.thread || getCurrentTaskDialogue(ctx);
    const payload = { user_input: buildDialogueContextInput(ctx, rawUserInput, thread) };
    const selectedSkillId = taskSkillSelect ? taskSkillSelect.value.trim() : "";
    if (selectedSkillId) {
      let parsedSkillArgs = {};
      const argsText = taskSkillArgs ? taskSkillArgs.value.trim() : "";
      if (argsText) {
        parsedSkillArgs = JSON.parse(argsText);
      }
      payload.skill_id = selectedSkillId;
      if (taskSkillVersion && taskSkillVersion.value.trim()) {
        payload.skill_version = taskSkillVersion.value.trim();
      }
      payload.skill_args = parsedSkillArgs;
    }
    if (thread?.sessionId) {
      payload.session_id = thread.sessionId;
    }
    payload._raw_user_input = rawUserInput;
    return payload;
  }

  async function analyzeTaskInput(ctx) {
    try {
      if (!getCurrentTaskDialogue(ctx)) {
        await startNewTaskDialogue(ctx, { preserveInputValue: true });
      }
      let thread = getCurrentTaskDialogue(ctx);
      thread = await ensureTaskDialogueSession(ctx, thread);
      const payload = parseTaskDraftPayload(ctx, { thread });
      addTaskDialogueTurn(ctx, {
        role: "user",
        type: "input",
        text: payload._raw_user_input,
      });
      const draft = await ctx.fetchJson(`${ctx.API_BASE}/intake/route`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          ...payload,
          user_input: payload.user_input,
        }),
      });
      draft._request_payload = {
        raw_user_input: payload._raw_user_input,
        contextual_user_input: payload.user_input,
        session_id: thread?.sessionId || null,
        skill_id: payload.skill_id || "",
        skill_version: payload.skill_version || "",
        skill_args: payload.skill_args || {},
      };
      updateCurrentTaskDialogue(ctx, (currentThread) => ({
        ...currentThread,
        title: currentThread.title === "新任务对话" ? String(payload._raw_user_input || "").slice(0, 40) : currentThread.title,
        latestDraft: draft,
        turns: [
          ...ctx.safeArray(currentThread.turns),
          {
            id: `turn_${Date.now()}_draft`,
            role: "assistant",
            type: "draft",
            createdAt: new Date().toISOString(),
            draft,
            rawUserInput: payload._raw_user_input,
            contextualUserInput: payload.user_input,
          },
        ],
      }));
      renderTaskDraft(ctx, draft);
      renderCurrentTaskDialogue(ctx);
      const memoryInput = document.getElementById("memorySearchInput");
      if (memoryInput && !memoryInput.value.trim()) {
        memoryInput.value = payload._raw_user_input;
      }
      ctx.setTaskSubmitMessage(`已生成 ${getRouteModeLabel(draft.route_mode || "draft_task")} 草稿，请确认后再创建任务。`);
      ctx.showToast("系统理解卡片已生成", "success");
    } catch (err) {
      ctx.setTaskSubmitMessage(`输入分流失败：${err.message}`, true);
      ctx.showToast("输入分流失败", "error");
      alert(err.message);
    }
  }

  async function confirmTaskDraft(ctx) {
    if (!ctx.currentTaskDraft) {
      alert("请先分析输入并生成草稿");
      return;
    }
    if (!ctx.actorHasPermission(ctx.currentActorName, "operate")) {
      const hint = ctx.getActorOperateHint(ctx.currentActorName);
      ctx.setTaskSubmitMessage(hint.text, true);
      alert(`当前 actor 无法创建任务。\n${hint.text}`);
      return;
    }

    try {
      let thread = getCurrentTaskDialogue(ctx);
      thread = await ensureTaskDialogueSession(ctx, thread);
      const requestPayload = ctx.currentTaskDraft._request_payload || {};
      const payload = {
        user_input: requestPayload.raw_user_input || document.getElementById("taskInput").value.trim(),
        session_id: thread?.sessionId || requestPayload.session_id || undefined,
        skill_id: requestPayload.skill_id || undefined,
        skill_version: requestPayload.skill_version || undefined,
        skill_args: requestPayload.skill_args || undefined,
        route: ctx.currentTaskDraft.route_mode || "draft_task",
      };
      const task = await ctx.fetchJson(`${ctx.API_BASE}/intake/confirm`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });

      document.getElementById("taskInput").value = "";
      renderTaskDraft(ctx, null);
      updateCurrentTaskDialogue(ctx, (currentThread) => ({
        ...currentThread,
        turns: [
          ...ctx.safeArray(currentThread.turns),
          {
            id: `turn_${Date.now()}_task`,
            role: "system",
            type: "task_created",
            createdAt: new Date().toISOString(),
            taskId: task.id,
            summary: task.display_user_input || task.user_input || "",
          },
        ],
      }));
      renderCurrentTaskDialogue(ctx);
      ctx.setTaskSubmitMessage(`已按 ${getRouteModeLabel(payload.route)} 创建任务 #${task.id}`);
      await ctx.loadTasks();
      await ctx.selectTask(task.id, { focusWorkspace: true });
      ctx.showToast(`任务 #${task.id} 已创建`, "success");
    } catch (err) {
      ctx.showToast("任务创建失败", "error");
      alert(err.message);
    }
  }

  async function createTask(ctx) {
    await analyzeTaskInput(ctx);
  }

  window.DashboardComposer = {
    analyzeTaskInput,
    applySkillToTask,
    applyTaskTemplate,
    changeTaskSkillSelection,
    confirmTaskDraft,
    createTask,
    getCurrentTaskDialogue,
    openComposerAndStartDialogue,
    renderCurrentTaskDialogue,
    renderFastPathAnswer,
    renderHomeDialogueSummary,
    renderTaskDialogueList,
    renderTaskDraft,
    renderTaskSkillOptions,
    renderTaskSubmissionState,
    runFastPathAnswer,
    selectTaskDialogue,
    startNewTaskDialogue,
    syncTaskSkillSelection,
  };
})();
