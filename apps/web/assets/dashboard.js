    const {
      API_BASE_CANDIDATES,
      API_BASE,
      appTabMeta,
      buildApiRequestCandidates,
      loadFrontendPrefs,
      loadTaskDialogues,
      persistFrontendPrefs: persistFrontendPrefsStorage,
      persistTaskDialogues: persistTaskDialoguesStorage,
    } = window.DashboardRuntime;
    const {
      formatDateTime,
      getTaskActionCategory,
      getTaskAttentionLevel,
      getTaskSearchableText,
      safeArray,
      summarizeTaskStatus,
    } = window.DashboardTaskUtils;
    const {
      buildRuntimeVersionSummary,
      formatRetrievedMemoriesForDisplay,
    } = window.DashboardExperience;
    const {
      DashboardComposer,
      DashboardHome,
      DashboardGovernance,
      DashboardMonitor,
      DashboardSettings,
      DashboardShell,
      DashboardSessions,
      DashboardWorkspace,
    } = window;

    function persistFrontendPrefs() {
      persistFrontendPrefsStorage(frontendPrefs);
    }

    function persistTaskDialogues() {
      persistTaskDialoguesStorage(taskDialogues, currentTaskDialogueId);
    }

    let frontendPrefs = loadFrontendPrefs();
    let autoRefreshTimer = null;
    let taskDialogues = [];
    let currentTaskDialogueId = window.localStorage.getItem("ai-assistant-current-task-dialogue") || "";
    taskDialogues = loadTaskDialogues();
    if (!currentTaskDialogueId && taskDialogues.length) {
      currentTaskDialogueId = taskDialogues[0].id;
    }
    let currentAppTab = window.localStorage.getItem("ai-assistant-tab") || "home";
    let currentWorkspaceTab = window.localStorage.getItem("ai-assistant-workspace-tab") || "overview";
    let selectedTaskId = null;
    const storedSessionId = parseInt(window.localStorage.getItem("ai-assistant-session-browser") || "", 10);
    let selectedSessionId = Number.isFinite(storedSessionId) ? storedSessionId : null;
    let currentActorName = window.localStorage.getItem("ai-assistant-actor") || "local_admin";
    let riskPolicies = [];
    let riskEditorKey = "";
    let monitorOverview = null;
    let taskAgentSummaries = new Map();
    let changeRequests = [];
    let accessActors = [];
    let accessQuotaUsage = [];
    let sessions = [];
    let sessionBrowserSnapshot = null;
    let sessionBrowserRequestToken = 0;
    let skillRegistry = [];
    let selectedGovernanceSkillId = "";
    let selectedGovernanceSkillVersion = "";
    let taskSkillDetail = null;
    let currentTaskDraft = null;
    let currentFastPathAnswer = null;
    let lastMemorySearchQuery = "";
    let allTasks = [];
    let currentTaskSnapshot = null;
    let toolRegistry = [];
    let modelRoutes = [];
    let modelProviders = [];
    const ACTOR_ROLE_PERMISSIONS = {
      viewer: ["read"],
      operator: ["read", "operate"],
      admin: ["read", "operate", "admin"]
    };
    const DEFAULT_ACTOR_ROLE_MAP = {
      local_admin: "admin",
      local_operator: "operator",
      local_viewer: "viewer"
    };

    function buildDashboardModuleContext() {
      return {
        API_BASE,
        escapeHtml,
        fetchJson,
        formatRatio,
        get selectedTaskId() {
          return selectedTaskId;
        },
        get selectedSessionId() {
          return selectedSessionId;
        },
        get riskPolicies() {
          return riskPolicies;
        },
        set riskPolicies(value) {
          riskPolicies = Array.isArray(value) ? value : [];
        },
        get riskEditorKey() {
          return riskEditorKey;
        },
        set riskEditorKey(value) {
          riskEditorKey = String(value || "");
        },
        get monitorOverview() {
          return monitorOverview;
        },
        set monitorOverview(value) {
          monitorOverview = value || null;
        },
        get taskAgentSummaries() {
          return taskAgentSummaries;
        },
        set taskAgentSummaries(value) {
          taskAgentSummaries = value instanceof Map ? value : new Map();
        },
        get changeRequests() {
          return changeRequests;
        },
        set changeRequests(value) {
          changeRequests = Array.isArray(value) ? value : [];
        },
        get accessActors() {
          return accessActors;
        },
        set accessActors(value) {
          accessActors = Array.isArray(value) ? value : [];
        },
        get accessQuotaUsage() {
          return accessQuotaUsage;
        },
        set accessQuotaUsage(value) {
          accessQuotaUsage = Array.isArray(value) ? value : [];
        },
        get toolRegistry() {
          return toolRegistry;
        },
        set toolRegistry(value) {
          toolRegistry = Array.isArray(value) ? value : [];
        },
        get modelRoutes() {
          return modelRoutes;
        },
        set modelRoutes(value) {
          modelRoutes = Array.isArray(value) ? value : [];
        },
        get modelProviders() {
          return modelProviders;
        },
        set modelProviders(value) {
          modelProviders = Array.isArray(value) ? value : [];
        },
        loadMonitorOverview,
        refreshSelectedSessionBrowser,
        renderActorContext,
        renderGlobalStatusBar,
        renderHomeOverview,
        renderSettingsView,
        sanitizePolicyKey,
        selectTask,
        setAppTab,
        setChangeRequestMessage,
        setRiskMessage,
        showToast,
      };
    }

    function buildShellModuleContext() {
      return {
        API_BASE,
        appTabMeta,
        actorRolePermissions: ACTOR_ROLE_PERMISSIONS,
        defaultActorRoleMap: DEFAULT_ACTOR_ROLE_MAP,
        escapeHtml,
        frontendPrefs,
        get accessActors() {
          return accessActors;
        },
        get autoRefreshTimer() {
          return autoRefreshTimer;
        },
        set autoRefreshTimer(value) {
          autoRefreshTimer = value;
        },
        get currentActorName() {
          return currentActorName;
        },
        set currentActorName(value) {
          currentActorName = String(value || "local_admin");
        },
        get currentAppTab() {
          return currentAppTab;
        },
        set currentAppTab(value) {
          currentAppTab = String(value || "home");
        },
        get currentWorkspaceTab() {
          return currentWorkspaceTab;
        },
        set currentWorkspaceTab(value) {
          currentWorkspaceTab = String(value || "overview");
        },
        get selectedTaskId() {
          return selectedTaskId;
        },
        loadSessions,
        loadTasks,
        reloadGovernanceData,
        renderCurrentTaskDialogue,
        renderHomeOverview,
        renderSettingsView,
        renderTaskDialogueList,
        renderTaskSubmissionState,
        selectTask,
        setActorContextMessage,
        setAppTab,
      };
    }

    function buildHomeModuleContext() {
      return {
        API_BASE,
        describeNextAction,
        escapeHtml,
        formatDateTime,
        frontendPrefs,
        get allTasks() {
          return allTasks;
        },
        get currentActorName() {
          return currentActorName;
        },
        get modelRoutes() {
          return modelRoutes;
        },
        get monitorOverview() {
          return monitorOverview;
        },
        actorHasPermission,
        getActorRole,
        getTaskActionCategory,
        getTaskAttentionLevel,
        selectTask,
        setAppTab,
        summarizeTaskStatus,
      };
    }

    function buildGovernanceTemplateContext() {
      return {
        escapeHtml,
        setAppTab,
      };
    }

    function buildSettingsModuleContext() {
      return {
        API_BASE,
        API_BASE_CANDIDATES,
        actorRolePermissions: ACTOR_ROLE_PERMISSIONS,
        buildRuntimeVersionSummary,
        escapeHtml,
        fetchJson,
        frontendPrefs,
        get currentActorName() {
          return currentActorName;
        },
        get monitorOverview() {
          return monitorOverview;
        },
        get modelProviders() {
          return modelProviders;
        },
        get modelRoutes() {
          return modelRoutes;
        },
        getActorRole,
        persistFrontendPrefs,
        renderGlobalStatusBar,
        restartAutoRefreshLoop,
        setTaskSkillMessage,
        showToast,
      };
    }

    function buildSessionsModuleContext() {
      return {
        API_BASE,
        escapeHtml,
        fetchJson,
        get lastMemorySearchQuery() {
          return lastMemorySearchQuery;
        },
        set lastMemorySearchQuery(value) {
          lastMemorySearchQuery = String(value || "");
        },
        get selectedSessionId() {
          return selectedSessionId;
        },
        set selectedSessionId(value) {
          selectedSessionId = value == null ? null : Number(value);
        },
        get selectedTaskId() {
          return selectedTaskId;
        },
        get sessionBrowserRequestToken() {
          return sessionBrowserRequestToken;
        },
        nextSessionBrowserRequestToken() {
          sessionBrowserRequestToken += 1;
          return sessionBrowserRequestToken;
        },
        get sessionBrowserSnapshot() {
          return sessionBrowserSnapshot;
        },
        set sessionBrowserSnapshot(value) {
          sessionBrowserSnapshot = value || null;
        },
        get sessions() {
          return sessions;
        },
        set sessions(value) {
          sessions = Array.isArray(value) ? value : [];
        },
        loadMonitorOverview,
        loadSessions,
        selectTask,
        setAppTab,
        setMemorySearchMessage,
        showToast,
      };
    }

    function buildComposerModuleContext() {
      return {
        API_BASE,
        actorHasPermission,
        currentActorName,
        escapeHtml,
        fetchJson,
        formatDateTime,
        formatRetrievedMemoriesForDisplay,
        get currentAppTab() {
          return currentAppTab;
        },
        get currentFastPathAnswer() {
          return currentFastPathAnswer;
        },
        set currentFastPathAnswer(value) {
          currentFastPathAnswer = value || null;
        },
        get currentTaskDialogueId() {
          return currentTaskDialogueId;
        },
        set currentTaskDialogueId(value) {
          currentTaskDialogueId = String(value || "");
        },
        get currentTaskDraft() {
          return currentTaskDraft;
        },
        set currentTaskDraft(value) {
          currentTaskDraft = value || null;
        },
        get currentTaskSnapshot() {
          return currentTaskSnapshot;
        },
        get frontendPrefs() {
          return frontendPrefs;
        },
        get skillRegistry() {
          return skillRegistry;
        },
        set skillRegistry(value) {
          skillRegistry = Array.isArray(value) ? value : [];
        },
        get taskDialogues() {
          return taskDialogues;
        },
        set taskDialogues(value) {
          taskDialogues = Array.isArray(value) ? value : [];
        },
        get taskSkillDetail() {
          return taskSkillDetail;
        },
        set taskSkillDetail(value) {
          taskSkillDetail = value || null;
        },
        getActorOperateHint,
        loadTasks,
        persistTaskDialogues,
        renderAppVisibility,
        renderGlobalStatusBar,
        renderSettingsView,
        safeArray,
        selectTask,
        setAppTab,
        setTaskSkillMessage,
        setTaskSubmitMessage,
        showToast,
      };
    }

    function buildWorkspaceModuleContext() {
      return {
        API_BASE,
        buildSandboxFileSourcePatchTemplate,
        currentAppTab,
        describeNextAction,
        describeTaskStage,
        escapeHtml,
        fetchJson,
        formatDateTime,
        get allTasks() {
          return allTasks;
        },
        set allTasks(value) {
          allTasks = Array.isArray(value) ? value : [];
        },
        get currentTaskSnapshot() {
          return currentTaskSnapshot;
        },
        set currentTaskSnapshot(value) {
          currentTaskSnapshot = value || null;
        },
        get monitorOverview() {
          return monitorOverview;
        },
        get selectedTaskId() {
          return selectedTaskId;
        },
        set selectedTaskId(value) {
          selectedTaskId = value == null ? null : Number(value);
        },
        get taskAgentSummaries() {
          return taskAgentSummaries;
        },
        set taskAgentSummaries(value) {
          taskAgentSummaries = value instanceof Map ? value : new Map();
        },
        getTaskActionCategory,
        getTaskAttentionLevel,
        getTaskSearchableText,
        summarizeTaskStatus,
        loadMonitorOverview,
        openChangeRequestTemplate,
        openSessionBrowser,
        renderGlobalStatusBar,
        renderHomeOverview,
        renderMonitorOverview,
        renderSessionRecommendedActions,
        renderSettingsView,
        renderTaskTraces,
        safeArray,
        setAppTab,
        setWorkspaceTab,
        showToast,
        statusClass,
      };
    }

    function showToast(message, variant = "info") {
      return DashboardShell.showToast(buildShellModuleContext(), message, variant);
    }

    function applyTaskTemplate(text) {
      return DashboardComposer.applyTaskTemplate(buildComposerModuleContext(), text);
    }

    function renderSettingsView() {
      return DashboardSettings.renderSettingsView(buildSettingsModuleContext());
    }

    function updateFrontendPreference(key, value) {
      return DashboardSettings.updateFrontendPreference(buildSettingsModuleContext(), key, value);
    }

    function updateRefreshInterval() {
      return DashboardSettings.updateRefreshInterval(buildSettingsModuleContext());
    }

    async function testApiConnection() {
      return DashboardSettings.testApiConnection(buildSettingsModuleContext());
    }

    function restartAutoRefreshLoop() {
      return DashboardShell.restartAutoRefreshLoop(buildShellModuleContext());
    }

    function getChangeTargetMeta(targetType) {
      return DashboardGovernance.getChangeTargetMeta(targetType);
    }

    function buildSandboxFileSourcePatchTemplate(note = "stage7 sandbox_file patch template") {
      return DashboardGovernance.buildSandboxFileSourcePatchTemplate(note);
    }

    function fillChangePayloadTemplate(force = true, overrides = {}) {
      return DashboardGovernance.fillChangePayloadTemplate(buildGovernanceTemplateContext(), force, overrides);
    }

    function jumpToChangeTemplate(targetType, targetKey = "", payload = null, rationale = "") {
      return DashboardGovernance.jumpToChangeTemplate(
        buildGovernanceTemplateContext(),
        targetType,
        targetKey,
        payload,
        rationale,
      );
    }

    function openChangeRequestTemplate(targetType, targetKey, payload = null, rationale = "") {
      return DashboardGovernance.openChangeRequestTemplate(
        buildGovernanceTemplateContext(),
        targetType,
        targetKey,
        payload,
        rationale,
      );
    }

    function setAppTab(tabName) {
      return DashboardShell.setAppTab(buildShellModuleContext(), tabName);
    }

    function setWorkspaceTab(tabName) {
      return DashboardShell.setWorkspaceTab(buildShellModuleContext(), tabName);
    }

    function renderTraceMetaRows(trace = {}) {
      return DashboardWorkspace.renderTraceMetaRows(buildWorkspaceModuleContext(), trace);
    }

    function renderTraceCardList(title, items, buildTitle) {
      return DashboardWorkspace.renderTraceCardList(buildWorkspaceModuleContext(), title, items, buildTitle);
    }

    function renderTraceSummary(tracePayload = {}) {
      return DashboardWorkspace.renderTraceSummary(buildWorkspaceModuleContext(), tracePayload);
    }

    function renderTaskReplay(replayPayload = null) {
      return DashboardWorkspace.renderTaskReplay(buildWorkspaceModuleContext(), replayPayload);
    }

    function renderTaskTraces(tracePayload = {}, replayPayload = null) {
      return DashboardWorkspace.renderTaskTraces(buildWorkspaceModuleContext(), tracePayload, replayPayload);
    }

    function setupTabKeyboardNavigation(buttonSelector, activateFn) {
      const buttons = Array.from(document.querySelectorAll(buttonSelector));
      if (!buttons.length) return;

      buttons.forEach((button, index) => {
        button.addEventListener("keydown", (event) => {
          if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
            return;
          }

          event.preventDefault();
          let nextIndex = index;
          if (event.key === "ArrowRight") {
            nextIndex = (index + 1) % buttons.length;
          } else if (event.key === "ArrowLeft") {
            nextIndex = (index - 1 + buttons.length) % buttons.length;
          } else if (event.key === "Home") {
            nextIndex = 0;
          } else if (event.key === "End") {
            nextIndex = buttons.length - 1;
          }

          const nextButton = buttons[nextIndex];
          const targetTabName = nextButton.id.replace(/^app-tab-/, "").replace(/^workspace-tab-/, "");
          activateFn(targetTabName);
          nextButton.focus();

          const controls = nextButton.getAttribute("aria-controls");
          const panel = controls ? document.getElementById(controls) : null;
          if (panel) {
            window.requestAnimationFrame(() => panel.focus());
          }
        });
      });
    }

    function statusClass(status) {
      if (status === "pending") return "status-pending";
      if (status === "running") return "status-running";
      if (status === "completed") return "status-completed";
      if (status === "waiting_clarification") return "status-waiting_clarification";
      if (status === "waiting_approval") return "status-waiting_approval";
      if (status === "paused") return "status-paused";
      if (status === "interrupt_requested") return "status-interrupt_requested";
      if (status === "failed") return "status-failed";
      return "status-pending";
    }

    function formatRatio(value) {
      const numeric = Number(value);
      if (!Number.isFinite(numeric)) {
        return "-";
      }
      return `${Math.round(numeric * 100)}%`;
    }

    function describeTaskStage(task, validationReport, recoveryAction) {
      const status = String((task || {}).status || "");
      if (status === "waiting_clarification") {
        return "任务在进入执行链前识别到关键信息缺口，当前等待补充澄清，不属于系统故障。";
      }
      if (status === "completed" && validationReport?.passed === true) {
        return "任务已经形成最终交付，当前可直接验收或引用历史经验。";
      }
      if (status === "waiting_approval") {
        return "任务被高风险步骤阻塞，需要先处理审批后才能继续。";
      }
      if (status === "failed" && recoveryAction?.action && recoveryAction.action !== "none") {
        return "任务已失败，但系统已经给出了可执行的恢复动作。";
      }
      if (status === "running" || status === "pending") {
        return "任务仍在执行链路中，建议先看步骤和 traces，再决定是否干预。";
      }
      return "当前任务仍处于执行控制台视图，可结合验收状态和下一步动作继续处理。";
    }

    function describeNextAction(task, validationReport, recoveryAction) {
      const status = String((task || {}).status || "");
      if (status === "waiting_clarification" || recoveryAction?.action === "clarify") {
        return "先补充待澄清信息，系统会据此重新规划任务。";
      }
      if (recoveryAction?.action && recoveryAction.action !== "none") {
        return `优先应用恢复动作：${recoveryAction.action}。`;
      }
      if (status === "waiting_approval") {
        return "切到审批页签，确认是否批准阻塞步骤。";
      }
      if (status === "completed" && validationReport?.passed === true) {
        return "可以结束本次任务，或把结论沉淀到 session / memory。";
      }
      return "优先查看步骤与 traces，确认当前执行是否需要人工干预。";
    }

    async function fetchJson(url, options = {}) {
      const headers = new Headers(options.headers || {});
      if (currentActorName) {
        headers.set("X-Actor-Name", currentActorName);
      }
      const requestCandidates = buildApiRequestCandidates(url);
      let lastError = null;

      for (let index = 0; index < requestCandidates.length; index += 1) {
        const requestUrl = requestCandidates[index];
        try {
          const res = await fetch(requestUrl, { ...options, headers });
          if (res.ok) {
            return res.json();
          }

          const text = await res.text();
          lastError = new Error(`请求失败: ${res.status} ${text}`);
          const shouldRetry = res.status === 404 && index < requestCandidates.length - 1;
          if (shouldRetry) {
            continue;
          }
          throw lastError;
        } catch (error) {
          lastError = error instanceof Error ? error : new Error(String(error));
          if (index < requestCandidates.length - 1) {
            continue;
          }
          throw lastError;
        }
      }

      throw lastError || new Error("请求失败: 未知错误");
    }

    function sanitizePolicyKey(policyKey) {
      return policyKey.replace(/[^a-z0-9]/gi, "_");
    }

    function setRiskMessage(text, isError = false) {
      const el = document.getElementById("riskPolicyMessage");
      el.textContent = text;
      el.style.color = isError ? "#b91c1c" : "#0f172a";
    }

    function setActorContextMessage(text, isError = false) {
      const el = document.getElementById("actorContextMessage");
      el.textContent = text;
      el.style.color = isError ? "#b91c1c" : "#0f172a";
    }

    function setTaskSubmitMessage(text, isError = false) {
      const el = document.getElementById("taskSubmitMessage");
      el.textContent = text;
      el.style.color = isError ? "#b91c1c" : "#0f172a";
    }

    function setTaskSkillMessage(text, isError = false) {
      const el = document.getElementById("taskSkillMessage");
      el.textContent = text;
      el.style.color = isError ? "#b91c1c" : "#0f172a";
    }

    function setMemorySearchMessage(text, isError = false) {
      const el = document.getElementById("memorySearchMessage");
      if (!el) {
        return;
      }
      el.textContent = text;
      el.style.color = isError ? "#b91c1c" : "#0f172a";
    }

    function setChangeRequestMessage(text, isError = false) {
      const el = document.getElementById("changeRequestMessage");
      el.textContent = text;
      el.style.color = isError ? "#b91c1c" : "#0f172a";
    }

    function getActorRole(actorName) {
      return DashboardShell.getActorRole(buildShellModuleContext(), actorName);
    }

    function actorHasPermission(actorName, permission) {
      return DashboardShell.actorHasPermission(buildShellModuleContext(), actorName, permission);
    }

    function getActorOperateHint(actorName) {
      return DashboardShell.getActorOperateHint(buildShellModuleContext(), actorName);
    }

    function renderAppVisibility() {
      return DashboardShell.renderAppVisibility(buildShellModuleContext());
    }

    function renderGlobalStatusBar() {
      return DashboardHome.renderGlobalStatusBar(buildHomeModuleContext());
    }

    function renderHomeOverview() {
      return DashboardHome.renderHomeOverview(buildHomeModuleContext());
    }

    function renderHomeDialogueSummary() {
      return DashboardComposer.renderHomeDialogueSummary(buildComposerModuleContext());
    }

    function renderTaskDialogueList() {
      return DashboardComposer.renderTaskDialogueList(buildComposerModuleContext());
    }

    function renderCurrentTaskDialogue() {
      return DashboardComposer.renderCurrentTaskDialogue(buildComposerModuleContext());
    }

    function selectTaskDialogue(dialogueId, focusComposer = false) {
      return DashboardComposer.selectTaskDialogue(buildComposerModuleContext(), dialogueId, focusComposer);
    }

    async function startNewTaskDialogue(options = {}) {
      return DashboardComposer.startNewTaskDialogue(buildComposerModuleContext(), options);
    }

    async function openComposerAndStartDialogue() {
      return DashboardComposer.openComposerAndStartDialogue(buildComposerModuleContext());
    }

    function renderTasksView() {
      return DashboardWorkspace.renderTasksView(buildWorkspaceModuleContext());
    }

    function renderTaskTimeline(steps = []) {
      return DashboardWorkspace.renderTaskTimeline
        ? DashboardWorkspace.renderTaskTimeline(buildWorkspaceModuleContext(), steps)
        : "";
    }

    function renderTraceHighlights(tracePayload = {}, replayPayload = null) {
      return DashboardWorkspace.renderTraceHighlights
        ? DashboardWorkspace.renderTraceHighlights(buildWorkspaceModuleContext(), tracePayload, replayPayload)
        : "";
    }

    function renderWorkspaceLoadingState(taskId) {
      return DashboardWorkspace.renderWorkspaceLoadingState
        ? DashboardWorkspace.renderWorkspaceLoadingState(buildWorkspaceModuleContext(), taskId)
        : undefined;
    }

    function renderTaskSubmissionState() {
      return DashboardComposer.renderTaskSubmissionState(buildComposerModuleContext());
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

    function renderTaskSkillOptions() {
      return DashboardComposer.renderTaskSkillOptions(buildComposerModuleContext());
    }

    async function loadSkillDetail(skillId, version = "") {
      const params = version ? `?version=${encodeURIComponent(version)}` : "";
      return fetchJson(`${API_BASE}/skills/${encodeURIComponent(skillId)}${params}`);
    }

    function renderSkillRegistry() {
      const listEl = document.getElementById("skillRegistryList");
      const detailEl = document.getElementById("skillRegistryDetail");
      const total = skillRegistry.length;
      const activeCount = skillRegistry.filter(item => item.status === "active").length;
      const draftCount = skillRegistry.filter(item => item.status !== "active").length;
      document.getElementById("skillRegistryCount").textContent = String(total);
      document.getElementById("skillRegistryActiveCount").textContent = String(activeCount);
      document.getElementById("skillRegistryDraftCount").textContent = String(draftCount);

      if (!skillRegistry.length) {
        listEl.innerHTML = `<div class="empty">暂无 skill 数据</div>`;
        detailEl.innerHTML = `<div class="empty">暂无 skill detail</div>`;
        return;
      }

      listEl.innerHTML = skillRegistry.map(item => `
        <div class="governance-card ${item.skill_id === selectedGovernanceSkillId ? "active" : ""}">
          <div class="governance-card-title">${escapeHtml(item.display_name || item.skill_id)}</div>
          <div class="governance-card-meta">
            id=${escapeHtml(item.skill_id)} · status=${escapeHtml(item.status || "-")} · latest=${escapeHtml(item.latest_version || "-")}
          </div>
          <div class="info-row"><span class="label">Entrypoint：</span>${escapeHtml(item.entrypoint_kind || "-")}</div>
          <div class="info-row"><span class="label">说明：</span>${escapeHtml(item.description || "无")}</div>
          <div class="governance-card-actions">
            <button class="ghost-btn" onclick="inspectGovernanceSkill('${escapeHtml(item.skill_id)}', '${escapeHtml(item.latest_version || "")}')">查看详情</button>
            <button class="ghost-btn" onclick="applySkillToTask('${escapeHtml(item.skill_id)}')">用于任务区</button>
          </div>
        </div>
      `).join("");

      if (!selectedGovernanceSkillId) {
        detailEl.innerHTML = `<div class="empty">请选择左侧 skill</div>`;
      }
    }

    async function inspectGovernanceSkill(skillId, version = "") {
      selectedGovernanceSkillId = skillId;
      selectedGovernanceSkillVersion = version;
      renderSkillRegistry();
      const detailEl = document.getElementById("skillRegistryDetail");
      detailEl.innerHTML = `<div class="empty">正在加载 ${escapeHtml(skillId)} …</div>`;
      try {
        const detail = await loadSkillDetail(skillId, version);
        const versionInfo = detail.version || {};
        const packageBody = versionInfo.package_body || {};
        const stepsTemplate = Array.isArray(packageBody.steps_template) ? packageBody.steps_template : [];
        const argKeys = extractSkillArgKeysFromPackage(packageBody);
        detailEl.innerHTML = `
          <div class="governance-card">
            <div class="governance-card-title">${escapeHtml((detail.skill || {}).display_name || skillId)}</div>
            <div class="governance-card-meta">
              ${escapeHtml((detail.skill || {}).skill_id || skillId)}@${escapeHtml(versionInfo.version || "-")} · ${escapeHtml((detail.skill || {}).status || "-")}
            </div>
            <div class="info-row"><span class="label">Package Source：</span>${escapeHtml(versionInfo.package_source || "-")}</div>
            <div class="info-row"><span class="label">Entrypoint：</span>${escapeHtml((detail.skill || {}).entrypoint_kind || "-")}</div>
            <div class="info-row"><span class="label">Args：</span>${argKeys.length ? escapeHtml(argKeys.join(", ")) : "无显式 args 占位"}</div>
            <div class="info-row"><span class="label">Steps：</span>${escapeHtml(String(stepsTemplate.length))}</div>
            <div class="info-row"><span class="label">原始 package：</span><pre>${escapeHtml(JSON.stringify(packageBody, null, 2))}</pre></div>
            <div class="governance-card-actions">
              <button class="ghost-btn" onclick="applySkillToTask('${escapeHtml(skillId)}')">在任务区使用</button>
            </div>
          </div>
        `;
      } catch (err) {
        detailEl.innerHTML = `<div class="empty">${escapeHtml(err.message)}</div>`;
      }
    }

    async function syncTaskSkillSelection() {
      return DashboardComposer.syncTaskSkillSelection(buildComposerModuleContext());
    }

    async function changeTaskSkillSelection() {
      return DashboardComposer.changeTaskSkillSelection(buildComposerModuleContext());
    }

    async function applySkillToTask(skillId) {
      return DashboardComposer.applySkillToTask(buildComposerModuleContext(), skillId);
    }

    function renderActorContext() {
      return DashboardShell.renderActorContext(buildShellModuleContext());
    }

    async function changeActorContext() {
      return DashboardShell.changeActorContext(buildShellModuleContext());
    }

    async function reloadGovernanceData() {
      await Promise.all([
        loadMonitorOverview(),
        loadRiskPolicies(),
        loadChangeRequests(),
        loadAccessActors(),
        loadAccessQuotaUsage(),
        loadSkillRegistry(),
        loadToolRegistry(),
        loadModelRegistry(),
      ]);
    }

    async function loadRiskPolicies() {
      return DashboardGovernance.loadRiskPolicies(buildDashboardModuleContext());
    }

    async function loadMonitorOverview() {
      return DashboardMonitor.loadMonitorOverview(buildDashboardModuleContext());
    }

    async function loadChangeRequests() {
      return DashboardGovernance.loadChangeRequests(buildDashboardModuleContext());
    }

    async function loadAccessQuotaUsage() {
      return DashboardGovernance.loadAccessQuotaUsage(buildDashboardModuleContext());
    }

    async function loadAccessActors() {
      return DashboardGovernance.loadAccessActors(buildDashboardModuleContext());
    }

    async function loadSkillRegistry() {
      try {
        skillRegistry = await fetchJson(`${API_BASE}/skills`);
        renderTaskSkillOptions();
        renderSkillRegistry();
        await syncTaskSkillSelection();
      } catch (err) {
        document.getElementById("skillRegistryList").innerHTML = `<div class="empty">${escapeHtml(err.message)}</div>`;
        document.getElementById("skillRegistryDetail").innerHTML = `<div class="empty">读取 skill detail 失败</div>`;
        setTaskSkillMessage("读取 skill registry 失败，任务区暂时只支持默认 planner。", true);
      }
    }

    async function loadToolRegistry() {
      return DashboardGovernance.loadToolRegistry(buildDashboardModuleContext());
    }

    async function loadModelRegistry() {
      return DashboardGovernance.loadModelRegistry(buildDashboardModuleContext());
    }

    function renderMonitorOverview() {
      return DashboardMonitor.renderMonitorOverview(buildDashboardModuleContext());
    }

    function renderChangeRequests() {
      return DashboardGovernance.renderChangeRequests(buildDashboardModuleContext());
    }

    function renderAccessQuotaUsage() {
      return DashboardGovernance.renderAccessQuotaUsage(buildDashboardModuleContext());
    }

    function renderAccessActors() {
      return DashboardGovernance.renderAccessActors(buildDashboardModuleContext());
    }

    function renderToolRegistry() {
      return DashboardGovernance.renderToolRegistry(buildDashboardModuleContext());
    }

    function renderModelRegistry() {
      return DashboardGovernance.renderModelRegistry(buildDashboardModuleContext());
    }

    async function runDailyReviews() {
      return DashboardMonitor.runDailyReviews(buildDashboardModuleContext());
    }

    function renderRiskPolicies() {
      return DashboardGovernance.renderRiskPolicies(buildDashboardModuleContext());
    }

    function toggleRiskEditor(policyKey) {
      return DashboardGovernance.toggleRiskEditor(buildDashboardModuleContext(), policyKey);
    }

    function cancelRiskEdit() {
      return DashboardGovernance.cancelRiskEdit(buildDashboardModuleContext());
    }

    async function saveRiskPolicy(policyKey, valueType) {
      return DashboardGovernance.saveRiskPolicy(buildDashboardModuleContext(), policyKey, valueType);
    }

    async function loadTasks() {
      return DashboardWorkspace.loadTasks(buildWorkspaceModuleContext());
    }

    function renderSessionsList() {
      return DashboardSessions.renderSessionsList(buildSessionsModuleContext());
    }

    async function loadSessions(options = {}) {
      return DashboardSessions.loadSessions(buildSessionsModuleContext(), options);
    }

    function selectSession(sessionId, focusTab = false) {
      return DashboardSessions.selectSession(buildSessionsModuleContext(), sessionId, focusTab);
    }

    function openSessionBrowser(sessionId) {
      return DashboardSessions.openSessionBrowser(buildSessionsModuleContext(), sessionId);
    }

    async function loadSessionBrowserDetail(sessionId) {
      return DashboardSessions.loadSessionBrowserDetail(buildSessionsModuleContext(), sessionId);
    }

    async function refreshSelectedSessionBrowser(sessionId) {
      return DashboardSessions.refreshSelectedSessionBrowser(buildSessionsModuleContext(), sessionId);
    }

    function renderSessionRecommendedActions(sessionId, recommendedActions = []) {
      return DashboardSessions.renderSessionRecommendedActions(buildSessionsModuleContext(), sessionId, recommendedActions);
    }

    function renderTaskAgentRuns(taskId, agentRuns = [], agentDetails = {}) {
      return DashboardWorkspace.renderTaskAgentRuns(buildWorkspaceModuleContext(), taskId, agentRuns, agentDetails);
    }

    function renderStage5TaskChips(summary) {
      return DashboardWorkspace.renderStage5TaskChips(buildWorkspaceModuleContext(), summary);
    }

    function formatWorkflowProposalLabel(proposal = {}) {
      return DashboardWorkspace.formatWorkflowProposalLabel(proposal);
    }

    function buildWorkflowProposalSandboxFileTemplate(proposal = {}) {
      return DashboardWorkspace.buildWorkflowProposalSandboxFileTemplate(buildWorkspaceModuleContext(), proposal);
    }

    function buildWorkflowProposalModelRouteTemplate(proposal = {}) {
      return DashboardWorkspace.buildWorkflowProposalModelRouteTemplate(proposal);
    }

    function renderWorkflowProposalTemplateActions(proposal = {}) {
      return DashboardWorkspace.renderWorkflowProposalTemplateActions(buildWorkspaceModuleContext(), proposal);
    }

    async function selectTask(taskId, options = {}) {
      return DashboardWorkspace.selectTask(buildWorkspaceModuleContext(), taskId, options);
    }

    async function applyRecoveryAction(taskId) {
      return DashboardWorkspace.applyRecoveryAction(buildWorkspaceModuleContext(), taskId);
    }

    async function clarifyTask(taskId) {
      return DashboardWorkspace.clarifyTask(buildWorkspaceModuleContext(), taskId);
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

    function renderTaskDraft(draft = null) {
      return DashboardComposer.renderTaskDraft(buildComposerModuleContext(), draft);
    }

    function renderFastPathAnswer(response = null) {
      return DashboardComposer.renderFastPathAnswer(buildComposerModuleContext(), response);
    }

    async function runFastPathAnswer() {
      return DashboardComposer.runFastPathAnswer(buildComposerModuleContext());
    }

    function renderMemorySearchResults(query, rows = []) {
      return DashboardSessions.renderMemorySearchResults(buildSessionsModuleContext(), query, rows);
    }

    async function searchLongTermMemories(options = {}) {
      return DashboardSessions.searchLongTermMemories(buildSessionsModuleContext(), options);
    }

    async function analyzeTaskInput() {
      return DashboardComposer.analyzeTaskInput(buildComposerModuleContext());
    }

    async function confirmTaskDraft() {
      return DashboardComposer.confirmTaskDraft(buildComposerModuleContext());
    }

    async function createSessionReview(sessionId) {
      return DashboardSessions.createSessionReview(buildSessionsModuleContext(), sessionId);
    }

    async function bootstrapTaskAgentRuns(taskId) {
      return DashboardWorkspace.bootstrapTaskAgentRuns(buildWorkspaceModuleContext(), taskId);
    }

    async function executeTaskAgentRuns(taskId) {
      return DashboardWorkspace.executeTaskAgentRuns(buildWorkspaceModuleContext(), taskId);
    }

    async function executeTaskAgentRunsViaWorker(taskId) {
      return DashboardWorkspace.executeTaskAgentRunsViaWorker(buildWorkspaceModuleContext(), taskId);
    }

    async function rerunTaskAgentRuns(taskId) {
      return DashboardWorkspace.rerunTaskAgentRuns(buildWorkspaceModuleContext(), taskId);
    }

    async function finalizeTaskAgentRuns(taskId) {
      return DashboardWorkspace.finalizeTaskAgentRuns(buildWorkspaceModuleContext(), taskId);
    }

    async function editSessionState(sessionId) {
      return DashboardSessions.editSessionState(buildSessionsModuleContext(), sessionId);
    }

    async function rebuildSessionState(sessionId) {
      return DashboardSessions.rebuildSessionState(buildSessionsModuleContext(), sessionId);
    }

    async function createTask() {
      return DashboardComposer.createTask(buildComposerModuleContext());
    }

    async function createChangeRequest() {
      return DashboardGovernance.createChangeRequest(buildDashboardModuleContext());
    }

    async function decideChangeRequest(changeRequestId, approved) {
      return DashboardGovernance.decideChangeRequest(buildDashboardModuleContext(), changeRequestId, approved);
    }

    async function applyChangeRequest(changeRequestId) {
      return DashboardGovernance.applyChangeRequest(buildDashboardModuleContext(), changeRequestId);
    }

    async function runChangeRequestShadowValidation(changeRequestId) {
      return DashboardGovernance.runChangeRequestShadowValidation(buildDashboardModuleContext(), changeRequestId);
    }

    async function showChangeRequestShadowValidation(changeRequestId) {
      return DashboardGovernance.showChangeRequestShadowValidation(buildDashboardModuleContext(), changeRequestId);
    }

    async function createRollbackChangeRequest(changeRequestId) {
      return DashboardGovernance.createRollbackChangeRequest(buildDashboardModuleContext(), changeRequestId);
    }

    async function decideApproval(approvalId, approved) {
      return DashboardWorkspace.decideApproval(buildWorkspaceModuleContext(), approvalId, approved);
    }

    function escapeHtml(str) {
      return String(str)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
    }

    renderActorContext();
    setAppTab(currentAppTab);
    setWorkspaceTab(currentWorkspaceTab);
    setupTabKeyboardNavigation(".app-tab", setAppTab);
    setupTabKeyboardNavigation(".subtab", setWorkspaceTab);
    document.getElementById("changeTargetType").addEventListener("change", () => fillChangePayloadTemplate(false));
    fillChangePayloadTemplate(false);
    renderSettingsView();
    renderTaskDialogueList();
    renderHomeDialogueSummary();
    renderCurrentTaskDialogue();
    loadTasks();
    if (currentAppTab === "sessions") {
      loadSessions();
    }
    reloadGovernanceData();
    restartAutoRefreshLoop();
