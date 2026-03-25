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
      DashboardGovernance,
      DashboardMonitor,
      DashboardSettings,
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
      const container = document.getElementById("toastStack");
      if (!container || !message) {
        return;
      }
      const item = document.createElement("div");
      item.className = `toast-item toast-${variant}`;
      item.textContent = message;
      container.appendChild(item);
      window.setTimeout(() => {
        item.classList.add("toast-leave");
        window.setTimeout(() => item.remove(), 220);
      }, 2600);
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
      if (autoRefreshTimer) {
        window.clearInterval(autoRefreshTimer);
        autoRefreshTimer = null;
      }
      if (!frontendPrefs.autoRefresh) {
        return;
      }
      autoRefreshTimer = window.setInterval(async () => {
        if (document.hidden) {
          return;
        }
        if (currentAppTab === "home" || currentAppTab === "composer" || currentAppTab === "tasks") {
          await loadTasks();
          return;
        }
        if (currentAppTab === "workspace") {
          if (selectedTaskId !== null) {
            await selectTask(selectedTaskId);
          } else {
            await loadTasks();
          }
          return;
        }
        if (currentAppTab === "sessions") {
          await loadSessions();
          return;
        }
        await reloadGovernanceData();
      }, Math.max(5, Number(frontendPrefs.refreshIntervalSeconds || 15)) * 1000);
    }

    function getChangeTargetMeta(targetType) {
      if (targetType === "access_actor") {
        return {
          title: "access_actor 模板",
          badge: "actor 变更",
          keyLabel: "target_key 写 actor_name",
          keyHint: "例如 local_operator、local_viewer、change_bot",
          formHint: "payload 需要包含 role、description，也可以补 tenant_key 和 permission_overrides，用来调整这个 actor 的权限身份。",
          example: "最常用：把 local_operator 改成 viewer，或补一个 operate/admin 级 permission override。",
        };
      }
      if (targetType === "access_quota") {
        return {
          title: "access_quota 模板",
          badge: "quota 变更",
          keyLabel: "target_key 写 actor_name",
          keyHint: "例如 local_operator、local_admin、change_bot",
          formHint: "payload 需要包含 daily_task_limit、active_task_limit，也可以补 daily_token_limit 和 max_parallel_agents，用来调整这个 actor 的运营额度。",
          example: "最常用：下调 local_operator 的 daily/active/token 配额，并限制并行 agents。",
        };
      }
      if (targetType === "tool_registry") {
        return {
          title: "tool_registry 模板",
          badge: "tool 变更",
          keyLabel: "target_key 写 tool_name",
          keyHint: "例如 web_search、shell_exec、file_write",
          formHint: "payload 需要包含 enabled、risk_level、description。",
          example: "常用于临时禁用高风险工具，或调整风险等级。",
        };
      }
      if (targetType === "model_route") {
        return {
          title: "model_route 模板",
          badge: "route 变更",
          keyLabel: "target_key 写 route_name",
          keyHint: "例如 planner、summarize_text、web_search_summary",
          formHint: "payload 需要包含 provider、model_name、temperature、max_tokens、enabled。",
          example: "常用于把 planner 指向新的 provider 或模型。",
        };
      }
      if (targetType === "model_provider") {
        return {
          title: "model_provider 模板",
          badge: "provider 变更",
          keyLabel: "target_key 写 provider_name",
          keyHint: "例如 deepseek_default、openai_compatible",
          formHint: "payload 需要包含 driver、base_url、api_key_env、enabled、description。",
          example: "常用于新增或切换模型 provider。",
        };
      }
      if (targetType === "sandbox_file") {
        return {
          title: "sandbox_file 模板",
          badge: "file 实验",
          keyLabel: "target_key 写相对 sandbox 路径",
          keyHint: "例如 smoke/assistant_cli_copy.py、experiments/route_patch.txt",
          formHint: "payload 可直接写 content；也可只写 source_path 从仓库内复制源码到 sandbox；若提供 source_path + patch，则会按 unified diff 基于源码副本生成最终内容。若再补 acceptance.script_path，则 apply 后会自动执行验收脚本，失败时自动回滚。所有改动都会限制在 apps/api/stage7_sandbox 下。",
          example: "常用于验证 file-level apply/rollback、workflow proposal bridge，或把现有源码复制成 sandbox 副本后继续推进 code patch proposal 实验，并给单条实验补 acceptance + auto rollback。",
        };
      }
      return {
        title: "risk_policy 模板",
        badge: "policy 变更",
        keyLabel: "target_key 写 policy_key",
        keyHint: "例如 approval_require_for_hidden_files、approval_allowed_http_methods",
        formHint: "payload 直接写 policy_value，支持布尔值、列表或对象。",
        example: "常用于调整风险门槛，例如隐藏文件审批或 HTTP 方法白名单。",
      };
    }

    function buildSandboxFileSourcePatchTemplate(note = "stage7 sandbox_file patch template") {
      return [
        "--- a/scripts/assistant_cli.py",
        "+++ b/scripts/assistant_cli.py",
        "@@ -1,4 +1,6 @@",
        " #!/usr/bin/env python3",
        " \"\"\"Minimal CLI for interacting with the AI Assistant API.\"\"\"",
        " ",
        `+# ${note}`,
        "+",
        " from __future__ import annotations"
      ].join("\n");
    }

    function buildChangePayloadTemplate(targetType) {
      if (targetType === "risk_policy") {
        return {
          targetKey: "approval_require_for_hidden_files",
          payload: {
            policy_value: false
          },
          rationale: "调整隐藏文件审批策略"
        };
      }
      if (targetType === "tool_registry") {
        return {
          targetKey: "web_search",
          payload: {
            enabled: false,
            provider_type: "builtin",
            transport: "local",
            server_name: "",
            provider_config: {},
            risk_level: "low",
            approval_required: false,
            description: "临时禁用联网搜索"
          },
          rationale: "收紧工具执行范围"
        };
      }
      if (targetType === "model_route") {
        return {
          targetKey: "planner",
          payload: {
            provider: "deepseek_default",
            enabled: true,
            model_name: "deepseek-chat",
            temperature: 0.2,
            max_tokens: 1500,
            description: "任务规划模型"
          },
          rationale: "调整规划模型路由"
        };
      }
      if (targetType === "model_provider") {
        return {
          targetKey: "deepseek_default",
          payload: {
            driver: "openai_compatible",
            base_url: "https://api.deepseek.com",
            api_key_env: "DEEPSEEK_API_KEY",
            enabled: true,
            description: "默认 DeepSeek provider"
          },
          rationale: "维护默认 provider 配置"
        };
      }
      if (targetType === "access_quota") {
        return {
          targetKey: "local_operator",
          payload: {
            daily_task_limit: 30,
            active_task_limit: 10,
            daily_token_limit: 300000,
            max_parallel_agents: 16
          },
          rationale: "调整 operator 配额"
        };
      }
      if (targetType === "sandbox_file") {
        return {
          targetKey: "smoke/web_console_assistant_cli_patch.py",
          payload: {
            source_path: "scripts/assistant_cli.py",
            patch: buildSandboxFileSourcePatchTemplate("stage7 sandbox_file patch example"),
            acceptance: {
              script_path: "scripts/stage7_sandbox_file_acceptance_probe.sh",
              timeout_seconds: 20,
              env: {
                STAGE7_EXPECT_CONTAINS: "stage7 sandbox_file patch example"
              }
            }
          },
          rationale: "创建 sandbox_file source-patch 实验变更"
        };
      }
      return {
        targetKey: "change_bot",
        payload: {
          role: "viewer",
          description: "变更管理 smoke actor",
          tenant_key: "default",
          permission_overrides: []
        },
        rationale: "创建只读 actor"
      };
    }

    function fillChangePayloadTemplate(force = true, overrides = {}) {
      const targetTypeEl = document.getElementById("changeTargetType");
      const targetKeyEl = document.getElementById("changeTargetKey");
      const payloadEl = document.getElementById("changePayload");
      const rationaleEl = document.getElementById("changeRationale");
      const guidanceEl = document.getElementById("changeTargetGuidance");
      const previewEl = document.getElementById("changeTemplatePreview");
      const template = buildChangePayloadTemplate(targetTypeEl.value);
      const meta = getChangeTargetMeta(targetTypeEl.value);
      const targetKey = overrides.targetKey || template.targetKey;
      const payload = overrides.payload || template.payload;
      const rationale = overrides.rationale || template.rationale;

      if (force || !targetKeyEl.value.trim()) {
        targetKeyEl.value = targetKey;
      }
      if (force || !payloadEl.value.trim()) {
        payloadEl.value = JSON.stringify(payload, null, 2);
      }
      if (force || !rationaleEl.value.trim()) {
        rationaleEl.value = rationale;
      }
      payloadEl.placeholder = JSON.stringify(payload);
      targetKeyEl.placeholder = meta.keyHint;

      if (guidanceEl) {
        guidanceEl.innerHTML = `
          <div class="governance-help-title">${escapeHtml(meta.title)}</div>
          <div class="governance-help-line"><span class="label">${escapeHtml(meta.keyLabel)}：</span>${escapeHtml(meta.keyHint)}</div>
          <div class="governance-help-line">${escapeHtml(meta.formHint)}</div>
          <div class="governance-help-line">${escapeHtml(meta.example)}</div>
        `;
      }

      if (previewEl) {
        previewEl.innerHTML = `
          <div class="governance-template-badge">${escapeHtml(meta.badge)}</div>
          <div class="governance-template-card">
            <div class="governance-template-card-title">${escapeHtml(meta.title)}</div>
            <div class="governance-template-card-text"><span class="label">target_key：</span>${escapeHtml(targetKey)}</div>
            <div class="governance-template-card-text"><span class="label">payload：</span><pre>${escapeHtml(JSON.stringify(payload, null, 2))}</pre></div>
            <div class="governance-template-card-text"><span class="label">rationale：</span>${escapeHtml(rationale)}</div>
          </div>
        `;
      }
    }

    function jumpToChangeTemplate(targetType, targetKey = "", payload = null, rationale = "") {
      const targetTypeEl = document.getElementById("changeTargetType");
      targetTypeEl.value = targetType;
      fillChangePayloadTemplate(true, {
        targetKey,
        payload,
        rationale,
      });
    }

    function openChangeRequestTemplate(targetType, targetKey, payload = null, rationale = "") {
      jumpToChangeTemplate(targetType, targetKey, payload, rationale);
      setAppTab("governance");
      document.getElementById("changeTargetType").scrollIntoView({ behavior: "smooth", block: "start" });
    }

    function setAppTab(tabName) {
      const validTabs = new Set(["home", "composer", "tasks", "workspace", "sessions", "governance", "monitor", "settings"]);
      const nextTab = validTabs.has(tabName) ? tabName : "home";
      const tabMeta = appTabMeta[nextTab] || appTabMeta.home;
      currentAppTab = nextTab;
      window.localStorage.setItem("ai-assistant-tab", nextTab);

      document.body.classList.remove("mode-home", "mode-tasks", "mode-workspace", "mode-sessions", "mode-governance", "mode-monitor", "mode-settings");
      document.body.classList.add(`mode-${nextTab}`);

      document.querySelectorAll(".app-tab").forEach((el) => {
        const active = el.id === `app-tab-${nextTab}`;
        el.classList.toggle("active", active);
        el.setAttribute("aria-selected", active ? "true" : "false");
        el.setAttribute("tabindex", active ? "0" : "-1");
      });

      document.querySelectorAll(".tab-pane").forEach((el) => {
        const active = el.dataset.tabPane === nextTab;
        el.classList.toggle("active", active);
        el.setAttribute("aria-hidden", active ? "false" : "true");
        if (active) {
          el.setAttribute("tabindex", "-1");
        }
      });

      const contextEl = document.getElementById("appTabContext");
      if (contextEl) {
        contextEl.innerHTML = `
          <div>
            <div class="app-tab-context-label">当前视图</div>
            <div class="app-tab-context-title">${escapeHtml(tabMeta.title)}</div>
            <p class="app-tab-context-text">${escapeHtml(tabMeta.description)}</p>
          </div>
        `;
      }

      if (nextTab === "sessions") {
        void loadSessions();
      }
      if (nextTab === "home") {
        renderHomeOverview();
      }
      if (nextTab === "composer") {
        renderTaskDialogueList();
        renderCurrentTaskDialogue();
      }
      if (nextTab === "settings") {
        renderSettingsView();
      }
    }

    function setWorkspaceTab(tabName) {
      const validTabs = new Set(["overview", "steps", "traces", "approvals", "agents", "session"]);
      const nextTab = validTabs.has(tabName) ? tabName : "overview";
      currentWorkspaceTab = nextTab;
      window.localStorage.setItem("ai-assistant-workspace-tab", nextTab);

      document.querySelectorAll(".subtab").forEach((el) => {
        const active = el.id === `workspace-tab-${nextTab}`;
        el.classList.toggle("active", active);
        el.setAttribute("aria-selected", active ? "true" : "false");
        el.setAttribute("tabindex", active ? "0" : "-1");
      });

      document.querySelectorAll("[data-workspace-pane]").forEach((el) => {
        const active = el.dataset.workspacePane === nextTab;
        el.classList.toggle("active", active);
        el.setAttribute("aria-hidden", active ? "false" : "true");
        if (active) {
          el.setAttribute("tabindex", "-1");
        }
      });
    }

    function renderTraceMetaRows(trace = {}) {
      const rows = [];
      if (trace.status) {
        rows.push(`<div class="info-row"><span class="label">状态：</span><span class="status-badge ${statusClass(trace.status)}">${escapeHtml(trace.status)}</span></div>`);
      }
      if (trace.trace_id) {
        rows.push(`<div class="info-row"><span class="label">trace_id：</span>${escapeHtml(trace.trace_id)}</div>`);
      }
      if (trace.plan_source) {
        rows.push(`<div class="info-row"><span class="label">plan_source：</span>${escapeHtml(trace.plan_source)}</div>`);
      }
      if (trace.route_name) {
        rows.push(`<div class="info-row"><span class="label">route_name：</span>${escapeHtml(trace.route_name)}</div>`);
      }
      if (trace.tool_name) {
        rows.push(`<div class="info-row"><span class="label">tool_name：</span>${escapeHtml(trace.tool_name)}</div>`);
      }
      if (trace.skill_id) {
        rows.push(`<div class="info-row"><span class="label">skill_id：</span>${escapeHtml(trace.skill_id)}</div>`);
      }
      if (trace.skill_version) {
        rows.push(`<div class="info-row"><span class="label">skill_version：</span>${escapeHtml(trace.skill_version)}</div>`);
      }
      if (trace.retrieval_scope) {
        rows.push(`<div class="info-row"><span class="label">retrieval_scope：</span>${escapeHtml(trace.retrieval_scope)}</div>`);
      }
      if (trace.model_name) {
        rows.push(`<div class="info-row"><span class="label">model_name：</span>${escapeHtml(trace.model_name)}</div>`);
      }
      if (trace.provider) {
        rows.push(`<div class="info-row"><span class="label">provider：</span>${escapeHtml(trace.provider)}</div>`);
      }
      if (trace.task_step_id) {
        rows.push(`<div class="info-row"><span class="label">task_step_id：</span>#${escapeHtml(trace.task_step_id)}</div>`);
      }
      if (trace.step_trace_id) {
        rows.push(`<div class="info-row"><span class="label">step_trace_id：</span>#${escapeHtml(trace.step_trace_id)}</div>`);
      }
      if (trace.started_at || trace.ended_at) {
        rows.push(`<div class="info-row"><span class="label">时间：</span>${escapeHtml(trace.started_at || "-")} → ${escapeHtml(trace.ended_at || "-")}</div>`);
      }
      if (trace.input_summary) {
        rows.push(`<div class="info-row"><span class="label">input_summary：</span><pre>${escapeHtml(trace.input_summary)}</pre></div>`);
      }
      if (trace.request_excerpt) {
        rows.push(`<div class="info-row"><span class="label">request_excerpt：</span><pre>${escapeHtml(trace.request_excerpt)}</pre></div>`);
      }
      if (trace.response_excerpt) {
        rows.push(`<div class="info-row"><span class="label">response_excerpt：</span><pre>${escapeHtml(trace.response_excerpt)}</pre></div>`);
      }
      if (trace.metadata_json) {
        rows.push(`<div class="info-row"><span class="label">metadata：</span><pre>${escapeHtml(JSON.stringify(trace.metadata_json, null, 2))}</pre></div>`);
      }
      if (trace.output_snapshot) {
        rows.push(`<div class="info-row"><span class="label">output_snapshot：</span><pre>${escapeHtml(JSON.stringify(trace.output_snapshot, null, 2))}</pre></div>`);
      }
      if (trace.error_summary) {
        rows.push(`<div class="info-row"><span class="label">错误：</span>${escapeHtml(trace.error_summary)}</div>`);
      }
      return rows.join("");
    }

    function renderTraceCardList(title, items, buildTitle) {
      if (!items.length) {
        return `
          <div class="panel">
            <div class="panel-title">${escapeHtml(title)}</div>
            <div class="empty">暂无数据</div>
          </div>
        `;
      }
      return `
        <div class="panel">
          <div class="panel-title">${escapeHtml(title)}</div>
          ${items.map((item, index) => `
            <div class="step-card">
              <div class="step-title">${buildTitle(item, index)}</div>
              ${renderTraceMetaRows(item)}
              <div class="info-row"><span class="label">原始记录：</span><pre>${escapeHtml(JSON.stringify(item || {}, null, 2))}</pre></div>
            </div>
          `).join("")}
        </div>
      `;
    }

    function renderTraceSummary(tracePayload = {}) {
      const cards = [
        { label: "Task", value: tracePayload.task_trace ? 1 : 0 },
        { label: "Steps", value: Array.isArray(tracePayload.step_traces) ? tracePayload.step_traces.length : 0 },
        { label: "Models", value: Array.isArray(tracePayload.model_traces) ? tracePayload.model_traces.length : 0 },
        { label: "Tools", value: Array.isArray(tracePayload.tool_traces) ? tracePayload.tool_traces.length : 0 },
        { label: "Skills", value: Array.isArray(tracePayload.skill_traces) ? tracePayload.skill_traces.length : 0 },
        { label: "Retrieval", value: Array.isArray(tracePayload.retrieval_traces) ? tracePayload.retrieval_traces.length : 0 }
      ];
      return `
        <div class="task-summary-grid">
          ${cards.map((item) => `
            <div class="task-summary-card">
              <div class="task-summary-label">${escapeHtml(item.label)}</div>
              <div class="task-summary-value">${escapeHtml(String(item.value))}</div>
            </div>
          `).join("")}
        </div>
      `;
    }

    function renderTaskReplay(replayPayload = null) {
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
              <div class="task-summary-value">${escapeHtml(summary.plan_source || "-")}</div>
            </div>
            <div class="task-summary-card">
              <div class="task-summary-label">Steps</div>
              <div class="task-summary-value">${escapeHtml(String(summary.step_count || 0))}</div>
            </div>
            <div class="task-summary-card">
              <div class="task-summary-label">Traces</div>
              <div class="task-summary-value">${escapeHtml(String((summary.model_trace_count || 0) + (summary.tool_trace_count || 0) + (summary.skill_trace_count || 0) + (summary.retrieval_trace_count || 0)))}</div>
            </div>
            <div class="task-summary-card">
              <div class="task-summary-label">Skill</div>
              <div class="task-summary-value">${skillInvocation ? escapeHtml(`${skillInvocation.skill_id || "-"}@${skillInvocation.skill_version || "-"}`) : "默认 planner"}</div>
            </div>
          </div>
          ${replayPayload.steps.map((step) => `
            <div class="step-card">
              <div class="step-title">步骤 ${escapeHtml(step.step_order || "-")}：${escapeHtml(step.step_name || "-")}</div>
              <div class="info-row"><span class="label">状态：</span><span class="status-badge ${statusClass(step.status)}">${escapeHtml(step.status || "-")}</span></div>
              <div class="info-row"><span class="label">工具：</span>${escapeHtml(step.tool_name || "-")}</div>
              <div class="info-row"><span class="label">重试：</span>${escapeHtml(String(step.retry_count || 0))} / ${escapeHtml(String(step.max_retries || 0))}</div>
              <div class="info-row"><span class="label">条件：</span>run_if=${escapeHtml(JSON.stringify(step.run_if ?? null))} · skip_if=${escapeHtml(JSON.stringify(step.skip_if ?? null))}</div>
              <div class="info-row"><span class="label">输入：</span><pre>${escapeHtml(JSON.stringify(step.input_payload ?? null, null, 2))}</pre></div>
              <div class="info-row"><span class="label">输出摘要：</span><pre>${escapeHtml(step.output_payload || "暂无输出")}</pre></div>
              <div class="info-row"><span class="label">输出结构：</span><pre>${escapeHtml(JSON.stringify(step.output_data ?? null, null, 2))}</pre></div>
              <div class="info-row"><span class="label">Replay Hints：</span><pre>${escapeHtml(JSON.stringify(step.replay_hints || {}, null, 2))}</pre></div>
              <div class="info-row"><span class="label">Trace Counts：</span>step=${escapeHtml(String((step.trace_counts || {}).step || 0))} · model=${escapeHtml(String((step.trace_counts || {}).model || 0))} · tool=${escapeHtml(String((step.trace_counts || {}).tool || 0))} · skill=${escapeHtml(String((step.trace_counts || {}).skill || 0))} · retrieval=${escapeHtml(String((step.trace_counts || {}).retrieval || 0))}</div>
              <div class="info-row"><span class="label">Approvals：</span><pre>${escapeHtml(JSON.stringify(step.approvals || [], null, 2))}</pre></div>
            </div>
          `).join("")}
        </div>
      `;
    }

    function renderTaskTraces(tracePayload = {}, replayPayload = null) {
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
              <div class="step-title">task_trace #${escapeHtml(taskTrace.id || "-")}</div>
              ${renderTraceMetaRows(taskTrace)}
              <div class="info-row"><span class="label">原始记录：</span><pre>${escapeHtml(JSON.stringify(taskTrace || {}, null, 2))}</pre></div>
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
        ${renderTaskReplay(replayPayload)}
        ${renderTraceSummary(tracePayload)}
        ${taskTracePanel}
        ${renderTraceCardList("Step Traces", stepTraces, (item, index) => `step_trace #${escapeHtml(item.id || "-")} · 步骤 ${escapeHtml(item.step_order || index + 1)}`)}
        ${renderTraceCardList("Model Traces", modelTraces, (item, index) => `model_trace #${escapeHtml(item.id || "-")} · ${escapeHtml(item.route_name || `调用 ${index + 1}`)}`)}
        ${renderTraceCardList("Tool Traces", toolTraces, (item, index) => `tool_trace #${escapeHtml(item.id || "-")} · ${escapeHtml(item.tool_name || `工具 ${index + 1}`)}`)}
        ${renderTraceCardList("Skill Traces", skillTraces, (item, index) => `skill_trace #${escapeHtml(item.id || "-")} · ${escapeHtml(item.skill_id || `skill ${index + 1}`)}`)}
        ${renderTraceCardList("Retrieval Traces", retrievalTraces, (item, index) => `retrieval_trace #${escapeHtml(item.id || "-")} · ${escapeHtml(item.retrieval_scope || `检索 ${index + 1}`)}`)}
      `;
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
      const matchedActor = accessActors.find(item => item.actor_name === actorName);
      if (matchedActor && matchedActor.role) {
        return matchedActor.role;
      }
      return DEFAULT_ACTOR_ROLE_MAP[actorName] || "viewer";
    }

    function actorHasPermission(actorName, permission) {
      const role = getActorRole(actorName);
      const permissions = ACTOR_ROLE_PERMISSIONS[role] || [];
      return permissions.includes(permission);
    }

    function getActorOperateHint(actorName) {
      const role = getActorRole(actorName);
      if (actorHasPermission(actorName, "operate")) {
        return {
          text: `当前 actor: ${actorName}（${role}，可提交任务与执行操作）`,
          isError: false
        };
      }
      return {
        text: `当前 actor: ${actorName}（${role}，只读；请切换到 local_operator 或 local_admin 后再提交任务）`,
        isError: true
      };
    }

    function renderAppVisibility() {
      const role = getActorRole(currentActorName);
      const visibilityRules = {
        "app-tab-governance": role === "admin",
        "app-tab-monitor": role !== "viewer",
      };

      Object.entries(visibilityRules).forEach(([id, visible]) => {
        const tab = document.getElementById(id);
        if (tab) {
          tab.hidden = !visible;
        }
      });

      if ((role === "viewer" && (currentAppTab === "monitor" || currentAppTab === "governance")) || (role !== "admin" && currentAppTab === "governance")) {
        setAppTab("home");
      }
    }

    function renderGlobalStatusBar() {
      const container = document.getElementById("globalStatusBar");
      if (!container) {
        return;
      }
      const running = allTasks.filter((item) => item.status === "running").length;
      const waitingClarification = allTasks.filter((item) => item.status === "waiting_clarification").length;
      const waitingApproval = allTasks.filter((item) => item.status === "waiting_approval").length;
      const failed = allTasks.filter((item) => item.status === "failed").length;
      const actionCount = allTasks.filter((item) => getTaskActionCategory(item) === "attention").length;
      const plannerRoute = modelRoutes.find((item) => item.route_name === "planner") || {};
      container.innerHTML = `
        <div class="status-chip status-chip-connection">
          <div class="status-chip-label">API</div>
          <div class="status-chip-value">${escapeHtml(monitorOverview ? "已连接" : "待验证")}</div>
          <div class="status-chip-meta">${escapeHtml(API_BASE)}</div>
        </div>
        <div class="status-chip">
          <div class="status-chip-label">Actor</div>
          <div class="status-chip-value">${escapeHtml(currentActorName)}</div>
          <div class="status-chip-meta">${escapeHtml(getActorRole(currentActorName))}</div>
        </div>
        <div class="status-chip">
          <div class="status-chip-label">Planner</div>
          <div class="status-chip-value">${escapeHtml(plannerRoute.provider || "-")}</div>
          <div class="status-chip-meta">${escapeHtml(plannerRoute.model_name || "-")}</div>
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
          <div class="status-chip-value">${frontendPrefs.autoRefresh ? "开启" : "关闭"}</div>
          <div class="status-chip-meta">${escapeHtml(String(frontendPrefs.refreshIntervalSeconds || 15))}s</div>
        </div>
      `;
    }

    function renderHomeOverview() {
      const heroEl = document.getElementById("homeHeroMetrics");
      const actionEl = document.getElementById("homeActionCenter");
      const pendingEl = document.getElementById("homePendingList");
      const deliverableEl = document.getElementById("homeRecentDeliverables");
      if (!heroEl || !actionEl || !pendingEl || !deliverableEl) {
        return;
      }

      const runningTasks = allTasks.filter((item) => item.status === "running");
      const attentionTasks = allTasks.filter((item) => getTaskActionCategory(item) === "attention");
      const completedTasks = allTasks.filter((item) => item.status === "completed");
      const latestTask = allTasks[0] || null;

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
          <div class="hero-metric-meta">${escapeHtml(latestTask ? summarizeTaskStatus(latestTask) : "暂无任务")}</div>
        </div>
        <div class="hero-metric-card">
          <div class="hero-metric-label">环境状态</div>
          <div class="hero-metric-value">${monitorOverview ? "健康" : "待检测"}</div>
          <div class="hero-metric-meta">${escapeHtml(monitorOverview?.generated_at ? formatDateTime(monitorOverview.generated_at) : "点击设置页可测试")}</div>
        </div>
      `;

      const nextActions = [];
      if (!allTasks.length) {
        nextActions.push("先输入一个任务并生成系统理解卡片。");
      }
      if (attentionTasks.length) {
        nextActions.push(`有 ${attentionTasks.length} 个任务需要人工处理，建议先打开最急任务。`);
      }
      if (runningTasks.length) {
        nextActions.push(`有 ${runningTasks.length} 个任务正在运行，建议持续观察当前步骤和输出。`);
      }
      if (!monitorOverview) {
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
            <button class="ghost-btn" onclick="setAppTab('${actorHasPermission(currentActorName, "operate") ? "monitor" : "settings"}')">${actorHasPermission(currentActorName, "operate") ? "查看监控" : "查看设置"}</button>
          </div>
        </div>
        <div class="action-recommendations">
          ${(nextActions.length ? nextActions : ["当前没有明显阻塞，可以继续创建新任务或回看最近交付。"])
            .map((text) => `<div class="action-recommendation">${escapeHtml(text)}</div>`).join("")}
        </div>
      `;

      pendingEl.innerHTML = attentionTasks.length
        ? attentionTasks.slice(0, 5).map((task) => `
          <button type="button" class="pending-item pending-${getTaskAttentionLevel(task)}" onclick="selectTask(${task.id}, { focusWorkspace: true })">
            <div class="pending-item-title">#${task.id} ${escapeHtml(task.display_user_input || task.user_input || "未命名任务")}</div>
            <div class="pending-item-meta">${escapeHtml(describeNextAction(task, task.validation_report || {}, task.recovery_action || {}))}</div>
          </button>
        `).join("")
        : `<div class="empty">当前没有待澄清、待审批或待恢复任务。</div>`;

      deliverableEl.innerHTML = completedTasks.length
        ? completedTasks.slice(0, 3).map((task) => `
          <button type="button" class="deliverable-item" onclick="selectTask(${task.id}, { focusWorkspace: true })">
            <div class="deliverable-item-title">#${task.id} ${escapeHtml(task.display_user_input || task.user_input || "")}</div>
            <div class="deliverable-item-meta">${escapeHtml((task.result || "").slice(0, 120) || "已完成但暂无可见交付")}</div>
          </button>
        `).join("")
        : `<div class="empty">暂无最近交付。</div>`;
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
      const select = document.getElementById("actorSelect");
      if (select) {
        select.value = currentActorName;
      }
      const hint = getActorOperateHint(currentActorName);
      setActorContextMessage(hint.text, hint.isError);
      renderTaskSubmissionState();
      const settingsMessage = document.getElementById("settingsConnectionMessage");
      if (settingsMessage) {
        settingsMessage.textContent = `${hint.text}；当前 API Base: ${API_BASE}`;
        settingsMessage.style.color = hint.isError ? "#b91c1c" : "#0f172a";
      }
    }

    async function changeActorContext() {
      const select = document.getElementById("actorSelect");
      currentActorName = select.value;
      window.localStorage.setItem("ai-assistant-actor", currentActorName);
      renderActorContext();
      await reloadGovernanceData();
      await loadTasks();
      if (selectedTaskId !== null) {
        await selectTask(selectedTaskId);
      }
      setAppTab("settings");
      showToast(`已切换为 ${currentActorName}`, "success");
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

    function buildWorkflowProposalSandboxFileTemplate(proposal = {}) {
      const proposalId = Number(proposal.id || 0);
      const actionKey = String(proposal.action_key || "unknown").trim() || "unknown";
      return {
        targetType: "sandbox_file",
        targetKey: `bridge/proposal_${proposalId || "latest"}_assistant_cli_patch.py`,
        payload: {
          source_path: "scripts/assistant_cli.py",
          patch: buildSandboxFileSourcePatchTemplate(`workflow proposal #${proposalId || "-"} ${actionKey} bridge`),
          acceptance: {
            script_path: "scripts/stage7_sandbox_file_acceptance_probe.sh",
            timeout_seconds: 20,
            env: {
              STAGE7_EXPECT_CONTAINS: `workflow proposal #${proposalId || "-"} ${actionKey} bridge`
            }
          }
        },
        rationale: `workflow proposal #${proposalId || "-"} sandbox_file source-patch experiment (${actionKey})`
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
          description: `workflow proposal #${proposalId || "-"} planner route template`
        },
        rationale: `workflow proposal #${proposalId || "-"} planner route bridge template`
      };
    }

    function renderWorkflowProposalTemplateActions(proposal = {}) {
      const proposalId = Number(proposal.id || 0);
      if (!proposalId) {
        return "";
      }

      const actionKey = String(proposal.action_key || "").trim();
      const templates = [buildWorkflowProposalSandboxFileTemplate(proposal)];
      if (actionKey === "expand_specialist_scope") {
        templates.unshift(buildWorkflowProposalModelRouteTemplate(proposal));
      }

      const buttons = templates.map((template) => {
        const encodedTargetKey = encodeURIComponent(String(template.targetKey || ""));
        const encodedPayload = encodeURIComponent(JSON.stringify(template.payload || {}));
        const encodedRationale = encodeURIComponent(String(template.rationale || ""));
        const label = template.targetType === "sandbox_file"
          ? "打开 sandbox_file source-patch 模板"
          : "打开 model_route 模板";
        return `<button class="ghost-btn" onclick="openChangeRequestTemplate('${escapeHtml(template.targetType)}', decodeURIComponent('${encodedTargetKey}'), JSON.parse(decodeURIComponent('${encodedPayload}')), decodeURIComponent('${encodedRationale}'))">${escapeHtml(label)}</button>`;
      }).join("");

      return buttons ? `<div class="top-actions">${buttons}</div>` : "";
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
