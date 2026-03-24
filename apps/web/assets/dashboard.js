    const DEFAULT_API_BASE = `${window.location.protocol}//${window.location.hostname}:8000`;

    function normalizeApiBase(value) {
      const raw = String(value || "").trim();
      if (!raw) {
        return "";
      }
      try {
        return new URL(raw, window.location.origin).href.replace(/\/$/, "");
      } catch (_error) {
        return "";
      }
    }

    function resolveApiBaseCandidates() {
      const params = new URLSearchParams(window.location.search);
      const queryBase = params.get("api_base");
      const runtimeBase = typeof window.__AI_ASSISTANT_API_BASE__ === "string" ? window.__AI_ASSISTANT_API_BASE__ : "";
      const metaBase = document.querySelector('meta[name="ai-assistant-api-base"]')?.content || "";
      const storedBase = window.localStorage.getItem("ai-assistant-api-base") || "";
      const candidates = [];

      [queryBase, runtimeBase, metaBase, storedBase, DEFAULT_API_BASE, window.location.origin].forEach((value) => {
        const normalized = normalizeApiBase(value);
        if (normalized && !candidates.includes(normalized)) {
          candidates.push(normalized);
        }
      });

      return candidates.length ? candidates : [DEFAULT_API_BASE];
    }

    function buildApiRequestCandidates(url) {
      const raw = String(url || "").trim();
      if (!raw.startsWith("http://") && !raw.startsWith("https://")) {
        return [raw];
      }

      const matchedBase = API_BASE_CANDIDATES.find((base) => raw === base || raw.startsWith(`${base}/`) || raw.startsWith(`${base}?`));
      if (!matchedBase) {
        return [raw];
      }

      const suffix = raw.slice(matchedBase.length);
      const candidates = [];
      API_BASE_CANDIDATES.forEach((base) => {
        const candidate = `${base}${suffix}`;
        if (!candidates.includes(candidate)) {
          candidates.push(candidate);
        }
      });
      return candidates;
    }

    const API_BASE_CANDIDATES = resolveApiBaseCandidates();
    const API_BASE = API_BASE_CANDIDATES[0];
    const FRONTEND_PREFS_STORAGE_KEY = "ai-assistant-frontend-prefs";
    const TASK_DIALOGUE_STORAGE_KEY = "ai-assistant-task-dialogues";
    const DEFAULT_FRONTEND_PREFS = {
      autoRefresh: true,
      refreshIntervalSeconds: 15,
      compactTaskCards: false,
      showAdvancedComposer: false,
    };

    function loadFrontendPrefs() {
      try {
        const raw = window.localStorage.getItem(FRONTEND_PREFS_STORAGE_KEY) || "";
        if (!raw) {
          return { ...DEFAULT_FRONTEND_PREFS };
        }
        const parsed = JSON.parse(raw);
        return {
          ...DEFAULT_FRONTEND_PREFS,
          ...(parsed || {}),
        };
      } catch (_error) {
        return { ...DEFAULT_FRONTEND_PREFS };
      }
    }

    function persistFrontendPrefs() {
      window.localStorage.setItem(FRONTEND_PREFS_STORAGE_KEY, JSON.stringify(frontendPrefs));
    }

    function loadTaskDialogues() {
      try {
        const raw = window.localStorage.getItem(TASK_DIALOGUE_STORAGE_KEY) || "";
        if (!raw) {
          return [];
        }
        const parsed = JSON.parse(raw);
        return Array.isArray(parsed) ? parsed : [];
      } catch (_error) {
        return [];
      }
    }

    function persistTaskDialogues() {
      window.localStorage.setItem(TASK_DIALOGUE_STORAGE_KEY, JSON.stringify(taskDialogues));
      if (currentTaskDialogueId) {
        window.localStorage.setItem("ai-assistant-current-task-dialogue", currentTaskDialogueId);
      } else {
        window.localStorage.removeItem("ai-assistant-current-task-dialogue");
      }
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
    const appTabMeta = {
      home: {
        title: "工作台",
        description: "先看待办、运行状态和任务入口，再决定进入任务、工作区还是治理监控。"
      },
      composer: {
        title: "任务起草器",
        description: "围绕单个任务主题做多轮对话，持续补充上下文，再决定 fast path 或创建正式任务。"
      },
      tasks: {
        title: "任务",
        description: "按状态、动作和风险筛选任务，把需要人工介入的项优先挑出来处理。"
      },
      workspace: {
        title: "工作区",
        description: "聚焦单个任务的状态、卡点、下一步动作、时间线和 session 上下文。"
      },
      sessions: {
        title: "Sessions",
        description: "围绕上下文、review 和记忆浏览 session，而不是只能从任务详情反向进入。"
      },
      governance: {
        title: "治理",
        description: "集中处理 actor、quota、变更单、工具和模型治理，不和任务执行信息混在一起。"
      },
      monitor: {
        title: "监控",
        description: "集中看运行概览、巡检指标、失败恢复和系统健康信号，用于持续运营。"
      },
      settings: {
        title: "设置",
        description: "显式展示 API Base、Actor、自动刷新和模型路由快照，降低运行态排障成本。"
      }
    };
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

    function safeArray(value) {
      return Array.isArray(value) ? value : [];
    }

    function formatDateTime(value) {
      const raw = String(value || "").trim();
      if (!raw) {
        return "-";
      }
      const date = new Date(raw);
      if (Number.isNaN(date.getTime())) {
        return raw;
      }
      return date.toLocaleString("zh-CN", {
        hour12: false,
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      });
    }

    function summarizeTaskStatus(task = {}) {
      const status = String(task.status || "").trim();
      if (status === "waiting_approval") {
        return "待审批";
      }
      if (status === "failed") {
        return "失败待恢复";
      }
      if (status === "running") {
        return "运行中";
      }
      if (status === "completed") {
        return "已完成";
      }
      return status || "未知";
    }

    function getTaskAttentionLevel(task = {}) {
      const recoveryAction = task.recovery_action || {};
      const validationReport = task.validation_report || {};
      if (task.status === "waiting_approval") {
        return "high";
      }
      if (task.status === "failed") {
        return "high";
      }
      if (recoveryAction.action && recoveryAction.action !== "none") {
        return "high";
      }
      if (validationReport.passed === false) {
        return "medium";
      }
      if (task.status === "running") {
        return "medium";
      }
      return "low";
    }

    function getTaskActionCategory(task = {}) {
      const recoveryAction = task.recovery_action || {};
      if (task.status === "waiting_approval" || task.status === "failed" || (recoveryAction.action && recoveryAction.action !== "none")) {
        return "attention";
      }
      if (task.status === "running") {
        return "running";
      }
      return "completed";
    }

    function getTaskSearchableText(task = {}) {
      return [
        task.display_user_input,
        task.user_input,
        task.result,
        task.error_message,
        task.status,
      ].join(" ").toLowerCase();
    }

    function newDialogueId() {
      return `dialogue_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
    }

    function getCurrentTaskDialogue() {
      return taskDialogues.find((item) => item.id === currentTaskDialogueId) || null;
    }

    function summarizeDialogueThread(thread = {}) {
      const lastUserTurn = safeArray(thread.turns).filter((item) => item.role === "user").slice(-1)[0];
      return lastUserTurn?.text || thread.title || "未命名任务对话";
    }

    function upsertTaskDialogue(thread) {
      const nextThread = {
        ...thread,
        updatedAt: new Date().toISOString(),
      };
      const index = taskDialogues.findIndex((item) => item.id === nextThread.id);
      if (index >= 0) {
        taskDialogues[index] = nextThread;
      } else {
        taskDialogues.unshift(nextThread);
      }
      taskDialogues.sort((a, b) => String(b.updatedAt || "").localeCompare(String(a.updatedAt || "")));
      persistTaskDialogues();
      renderTaskDialogueList();
      renderHomeDialogueSummary();
      return nextThread;
    }

    function updateCurrentTaskDialogue(mutator) {
      const current = getCurrentTaskDialogue();
      if (!current) {
        return null;
      }
      const updated = mutator({ ...current, turns: safeArray(current.turns).slice() });
      return upsertTaskDialogue(updated);
    }

    function addTaskDialogueTurn(turn) {
      return updateCurrentTaskDialogue((thread) => ({
        ...thread,
        title: thread.title || (turn.role === "user" ? String(turn.text || "").slice(0, 40) : thread.title),
        turns: [...safeArray(thread.turns), { id: `turn_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`, createdAt: new Date().toISOString(), ...turn }],
      }));
    }

    async function ensureTaskDialogueSession(thread) {
      if (!thread) {
        throw new Error("请先创建一个任务对话");
      }
      if (thread.sessionId) {
        return thread;
      }
      if (!actorHasPermission(currentActorName, "operate")) {
        return thread;
      }
      const baseTitle = thread.title || `任务对话 ${formatDateTime(new Date().toISOString())}`;
      const session = await fetchJson(`${API_BASE}/sessions`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          name: baseTitle.slice(0, 60),
          description: "由 Web 任务起草器自动创建，用于承接多轮任务对话上下文。"
        })
      });
      const updated = upsertTaskDialogue({
        ...thread,
        sessionId: session.id,
        title: thread.title || session.name || baseTitle,
      });
      currentTaskDialogueId = updated.id;
      persistTaskDialogues();
      return updated;
    }

    function buildDialogueContextInput(rawInput, thread = null) {
      const text = String(rawInput || "").trim();
      const dialogue = thread || getCurrentTaskDialogue();
      const turns = safeArray(dialogue?.turns).slice(-6);
      if (!turns.length) {
        return text;
      }
      const contextLines = turns.map((item) => {
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
      }).filter(Boolean);
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

    function applyTaskTemplate(text) {
      const input = document.getElementById("taskInput");
      if (!input) {
        return;
      }
      if (currentAppTab !== "composer") {
        setAppTab("composer");
      }
      input.value = text;
      input.focus();
    }

    function renderSettingsView() {
      const runtimeSummary = document.getElementById("settingsRuntimeSummary");
      if (runtimeSummary) {
        runtimeSummary.innerHTML = `
          <div class="settings-kv"><span class="label">当前 API Base：</span>${escapeHtml(API_BASE)}</div>
          <div class="settings-kv"><span class="label">候选地址：</span>${escapeHtml(API_BASE_CANDIDATES.join(" / "))}</div>
          <div class="settings-kv"><span class="label">当前 Actor：</span>${escapeHtml(currentActorName)} / ${escapeHtml(getActorRole(currentActorName))}</div>
          <div class="settings-kv"><span class="label">可用权限：</span>${escapeHtml((ACTOR_ROLE_PERMISSIONS[getActorRole(currentActorName)] || []).join(", ") || "无")}</div>
          <div class="settings-kv"><span class="label">自动刷新：</span>${frontendPrefs.autoRefresh ? `开启 / ${frontendPrefs.refreshIntervalSeconds}s` : "关闭"}</div>
        `;
      }

      const modelSummary = document.getElementById("settingsModelSummary");
      if (modelSummary) {
        const providerRows = modelProviders.slice(0, 6).map((item) => `${item.provider_name || item.name || "-"} => ${item.base_url || item.driver || "-"}`);
        const routeRows = modelRoutes.slice(0, 8).map((item) => `${item.route_name || "-"} => ${(item.provider || "-")}/${(item.model_name || "-")}`);
        modelSummary.innerHTML = `
          <div class="settings-kv"><span class="label">Providers：</span><pre>${escapeHtml(providerRows.join("\n") || "暂无 provider 数据")}</pre></div>
          <div class="settings-kv"><span class="label">Routes：</span><pre>${escapeHtml(routeRows.join("\n") || "暂无 route 数据")}</pre></div>
        `;
      }

      const autoRefreshEl = document.getElementById("settingsAutoRefresh");
      const refreshSecondsEl = document.getElementById("settingsRefreshSeconds");
      const compactEl = document.getElementById("settingsCompactCards");
      const advancedEl = document.getElementById("settingsAdvancedComposer");
      if (autoRefreshEl) autoRefreshEl.checked = Boolean(frontendPrefs.autoRefresh);
      if (refreshSecondsEl) refreshSecondsEl.value = String(frontendPrefs.refreshIntervalSeconds || 15);
      if (compactEl) compactEl.checked = Boolean(frontendPrefs.compactTaskCards);
      if (advancedEl) advancedEl.checked = Boolean(frontendPrefs.showAdvancedComposer);
      const composerAdvanced = document.getElementById("taskComposerAdvanced");
      if (composerAdvanced) {
        composerAdvanced.open = Boolean(frontendPrefs.showAdvancedComposer);
      }
      document.body.classList.toggle("compact-task-cards", Boolean(frontendPrefs.compactTaskCards));
    }

    function updateFrontendPreference(key, value) {
      frontendPrefs[key] = value;
      persistFrontendPrefs();
      renderSettingsView();
      restartAutoRefreshLoop();
      setTaskSkillMessage("任务起草器配置已更新。");
      const settingsMessage = document.getElementById("settingsPreferenceMessage");
      if (settingsMessage) {
        settingsMessage.textContent = "偏好已保存并立即生效。";
      }
      showToast("界面偏好已更新", "success");
    }

    function updateRefreshInterval() {
      const input = document.getElementById("settingsRefreshSeconds");
      const value = Math.max(5, Math.min(120, parseInt(input?.value || "", 10) || 15));
      frontendPrefs.refreshIntervalSeconds = value;
      persistFrontendPrefs();
      renderSettingsView();
      restartAutoRefreshLoop();
      showToast(`自动刷新间隔已调整为 ${value} 秒`, "success");
    }

    async function testApiConnection() {
      const messageEl = document.getElementById("settingsConnectionMessage");
      if (messageEl) {
        messageEl.textContent = "正在测试 API 连通性…";
      }
      try {
        await fetchJson(`${API_BASE}/monitor/overview`);
        if (messageEl) {
          messageEl.textContent = `连接正常：${API_BASE}`;
          messageEl.style.color = "#0f5132";
        }
        renderGlobalStatusBar();
        showToast("API 连接测试通过", "success");
      } catch (err) {
        if (messageEl) {
          messageEl.textContent = `连接失败：${err.message}`;
          messageEl.style.color = "#b91c1c";
        }
        showToast("API 连接失败", "error");
      }
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
      if (recoveryAction?.action === "clarify") {
        return "先补充 Clarification，再重新规划任务。";
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
          <div class="status-chip-meta">审批 / 恢复 / 失败</div>
        </div>
        <div class="status-chip">
          <div class="status-chip-label">运行中</div>
          <div class="status-chip-value">${running}</div>
          <div class="status-chip-meta">审批 ${waitingApproval} / 失败 ${failed}</div>
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
          <div class="hero-metric-meta">优先处理审批、恢复和失败任务</div>
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
        : `<div class="empty">当前没有待审批或待恢复任务。</div>`;

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
      const container = document.getElementById("homeDialogueSummary");
      if (!container) {
        return;
      }
      if (!taskDialogues.length) {
        container.innerHTML = `<div class="empty">最近任务对话会显示在这里。</div>`;
        return;
      }
      container.innerHTML = taskDialogues.slice(0, 3).map((thread) => `
        <button type="button" class="deliverable-item" onclick="selectTaskDialogue('${escapeHtml(thread.id)}', true)">
          <div class="deliverable-item-title">${escapeHtml(thread.title || "未命名任务对话")}</div>
          <div class="deliverable-item-meta">Session ${escapeHtml(thread.sessionId ? `#${thread.sessionId}` : "未绑定")} · ${escapeHtml(formatDateTime(thread.updatedAt))}</div>
        </button>
      `).join("");
    }

    function renderTaskDialogueList() {
      const container = document.getElementById("taskDialogueList");
      if (!container) {
        return;
      }
      if (!taskDialogues.length) {
        container.innerHTML = `<div class="empty">还没有任务对话，点击“开始新任务对话”即可。</div>`;
        return;
      }
      if (!getCurrentTaskDialogue()) {
        currentTaskDialogueId = taskDialogues[0].id;
        persistTaskDialogues();
      }
      container.innerHTML = taskDialogues.map((thread) => `
        <button type="button" class="task-card task-dialogue-card ${thread.id === currentTaskDialogueId ? "active" : ""}" onclick="selectTaskDialogue('${escapeHtml(thread.id)}', true)">
          <div class="task-title">${escapeHtml(thread.title || "未命名任务对话")}</div>
          <div class="task-meta">Session：${escapeHtml(thread.sessionId ? `#${thread.sessionId}` : "未绑定")}</div>
          <div class="task-meta">轮次：${escapeHtml(String(safeArray(thread.turns).filter((item) => item.role === "user").length))} / 更新时间：${escapeHtml(formatDateTime(thread.updatedAt))}</div>
        </button>
      `).join("");
    }

    function renderCurrentTaskDialogue() {
      const metaEl = document.getElementById("taskDialogueMeta");
      const timelineEl = document.getElementById("taskDialogueTimeline");
      if (!metaEl || !timelineEl) {
        return;
      }
      const thread = getCurrentTaskDialogue();
      if (!thread) {
        metaEl.innerHTML = `<div class="empty">请选择或创建一个任务对话。</div>`;
        timelineEl.innerHTML = `<div class="empty">任务对话会显示在这里。</div>`;
        renderTaskDraft(null);
        return;
      }

      metaEl.innerHTML = `
        <div class="composer-thread-summary">
          <div class="composer-thread-title">${escapeHtml(thread.title || "未命名任务对话")}</div>
          <div class="composer-thread-summary-meta">Session：${escapeHtml(thread.sessionId ? `#${thread.sessionId}` : "未绑定")} · 创建于 ${escapeHtml(formatDateTime(thread.createdAt))} · 更新于 ${escapeHtml(formatDateTime(thread.updatedAt))}</div>
        </div>
      `;

      const turns = safeArray(thread.turns);
      timelineEl.innerHTML = turns.length
        ? turns.map((item) => {
          if (item.role === "user") {
            return `
              <div class="dialogue-turn dialogue-user">
                <div class="dialogue-turn-role">用户</div>
                <div class="dialogue-turn-body">${escapeHtml(item.text || "")}</div>
              </div>
            `;
          }
          if (item.type === "draft") {
            const preview = (item.draft || {}).draft_preview || {};
            return `
              <div class="dialogue-turn dialogue-assistant">
                <div class="dialogue-turn-role">系统理解</div>
                <div class="dialogue-turn-body">
                  <div class="dialogue-card-title">${escapeHtml((item.draft || {}).route_mode || "draft_task")}</div>
                  <div class="dialogue-card-text">goal：${escapeHtml(preview.goal_summary || "-")}</div>
                  <div class="dialogue-card-text">deliverable：${escapeHtml(preview.deliverable_type || "-")}</div>
                  <div class="dialogue-card-text">acceptance：${escapeHtml((preview.acceptance_hints || []).join(" / ") || "暂无")}</div>
                </div>
              </div>
            `;
          }
          if (item.type === "fast_path") {
            return `
              <div class="dialogue-turn dialogue-assistant">
                <div class="dialogue-turn-role">Fast Path</div>
                <div class="dialogue-turn-body"><pre>${escapeHtml((item.response || {}).answer || "")}</pre></div>
              </div>
            `;
          }
          if (item.type === "task_created") {
            return `
              <div class="dialogue-turn dialogue-system">
                <div class="dialogue-turn-role">正式任务</div>
                <div class="dialogue-turn-body">
                  <div class="dialogue-card-title">已创建任务 #${escapeHtml(String(item.taskId || "-"))}</div>
                  <div class="dialogue-card-text">${escapeHtml(item.summary || "可进入任务工作区继续查看。")}</div>
                  ${item.taskId ? `<div class="top-actions"><button class="ghost-btn" onclick="selectTask(${Number(item.taskId)}, { focusWorkspace: true })">打开任务工作区</button></div>` : ""}
                </div>
              </div>
            `;
          }
          return `
            <div class="dialogue-turn dialogue-system">
              <div class="dialogue-turn-role">系统</div>
              <div class="dialogue-turn-body">${escapeHtml(item.text || item.summary || "")}</div>
            </div>
          `;
        }).join("")
        : `<div class="empty">这个任务对话还没有内容，先输入一条任务消息吧。</div>`;
    }

    function selectTaskDialogue(dialogueId, focusComposer = false) {
      currentTaskDialogueId = dialogueId;
      persistTaskDialogues();
      renderTaskDialogueList();
      renderCurrentTaskDialogue();
      const thread = getCurrentTaskDialogue();
      if (thread && thread.latestDraft) {
        currentTaskDraft = thread.latestDraft;
        renderTaskDraft(thread.latestDraft);
      } else {
        currentTaskDraft = null;
        renderTaskDraft(null);
      }
      if (thread && thread.latestFastPath) {
        currentFastPathAnswer = thread.latestFastPath;
        renderFastPathAnswer(thread.latestFastPath);
      } else {
        currentFastPathAnswer = null;
        renderFastPathAnswer(null);
      }
      if (focusComposer) {
        setAppTab("composer");
      }
    }

    async function startNewTaskDialogue() {
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
      if (actorHasPermission(currentActorName, "operate")) {
        try {
          thread = await ensureTaskDialogueSession(thread);
        } catch (err) {
          showToast(`创建任务对话 Session 失败：${err.message}`, "error");
        }
      }
      upsertTaskDialogue(thread);
      currentTaskDialogueId = thread.id;
      persistTaskDialogues();
      renderTaskDialogueList();
      renderCurrentTaskDialogue();
      renderTaskDraft(null);
      renderFastPathAnswer(null);
      const input = document.getElementById("taskInput");
      if (input) {
        input.value = "";
        input.focus();
      }
      setAppTab("composer");
      showToast("已开始新的任务对话", "success");
    }

    async function openComposerAndStartDialogue() {
      await startNewTaskDialogue();
    }

    function renderTasksView() {
      const taskList = document.getElementById("taskList");
      const queueSummary = document.getElementById("taskQueueSummary");
      if (!taskList || !queueSummary) {
        return;
      }
      const searchKeyword = String(document.getElementById("taskSearchInput")?.value || "").trim().toLowerCase();
      const statusFilter = document.getElementById("taskStatusFilter")?.value || "";
      const actionFilter = document.getElementById("taskActionFilter")?.value || "";
      const filteredTasks = allTasks.filter((task) => {
        if (searchKeyword && !getTaskSearchableText(task).includes(searchKeyword)) {
          return false;
        }
        if (statusFilter && task.status !== statusFilter) {
          return false;
        }
        if (actionFilter && getTaskActionCategory(task) !== actionFilter) {
          return false;
        }
        return true;
      });

      const runningCount = allTasks.filter((task) => task.status === "running").length;
      const blockedCount = allTasks.filter((task) => task.status === "waiting_approval").length;
      const actionCount = allTasks.filter((task) => getTaskActionCategory(task) === "attention").length;

      queueSummary.innerHTML = `
        <div class="queue-chip">
          <div class="queue-chip-label">Total</div>
          <div class="queue-chip-value">${allTasks.length}</div>
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

      taskList.innerHTML = filteredTasks.map((task) => {
        const recoveryAction = task.recovery_action || {};
        const validationReport = task.validation_report || {};
        const skillInvocation = ((task.runtime_overrides || {}).skill_invocation) || null;
        const stage5 = task.stage5 || {};
        return `
          <button type="button" class="task-card task-card-operational ${task.id === selectedTaskId ? "active" : ""}" data-testid="task-card" onclick="selectTask(${task.id}, { focusWorkspace: true })">
            <div class="task-card-topline">
              <div class="task-title">#${task.id} ${escapeHtml(task.display_user_input || task.user_input || "未命名任务")}</div>
              <span class="status-badge ${statusClass(task.status)}">${escapeHtml(task.status || "-")}</span>
            </div>
            <div class="task-meta task-meta-strong">${escapeHtml(describeNextAction(task, validationReport, recoveryAction))}</div>
            <div class="task-meta">阶段：${escapeHtml(describeTaskStage(task, validationReport, recoveryAction))}</div>
            <div class="task-meta">更新时间：${escapeHtml(formatDateTime(task.updated_at || task.created_at))}</div>
            <div class="task-meta">Skill：${skillInvocation ? `${escapeHtml(skillInvocation.skill_id || "-")}@${escapeHtml(skillInvocation.skill_version || "-")}` : "默认 planner"}</div>
            <div class="task-chip-row">
              <span class="task-mini-chip task-mini-chip-${getTaskAttentionLevel(task)}">${escapeHtml(getTaskActionCategory(task))}</span>
              ${recoveryAction.action && recoveryAction.action !== "none" ? `<span class="task-mini-chip task-mini-chip-high">recovery:${escapeHtml(recoveryAction.action)}</span>` : ""}
              ${validationReport.passed === false ? `<span class="task-mini-chip task-mini-chip-medium">validation failed</span>` : ""}
              ${stage5.recommended_action ? `<span class="task-mini-chip">${escapeHtml(stage5.recommended_action)}</span>` : ""}
            </div>
            ${renderStage5TaskChips(stage5)}
          </button>
        `;
      }).join("");
    }

    function renderTaskTimeline(steps = []) {
      if (!steps.length) {
        return `<div class="empty">暂无步骤。可能仍在规划中，也可能在更早阶段失败，建议先看概览中的恢复动作。</div>`;
      }
      return steps.map((step) => `
        <div class="timeline-card">
          <div class="timeline-rail">
            <div class="timeline-dot ${statusClass(step.status)}"></div>
            <div class="timeline-line"></div>
          </div>
          <div class="timeline-body">
            <div class="timeline-head">
              <div class="step-title">步骤 ${step.step_order}：${escapeHtml(step.step_name || "未命名步骤")}</div>
              <span class="status-badge ${statusClass(step.status)}">${escapeHtml(step.status || "-")}</span>
            </div>
            <div class="timeline-meta-row">
              <span>工具：${escapeHtml(step.tool_name || "-")}</span>
              <span>重试：${escapeHtml(String(step.retry_count || 0))} / ${escapeHtml(String(step.max_retries || 0))}</span>
            </div>
            ${step.error_message ? `<div class="timeline-alert">失败原因：${escapeHtml(step.error_message)}</div>` : ""}
            <details>
              <summary>查看输入 / 输出细节</summary>
              <div class="info-row"><span class="label">输入：</span><pre>${escapeHtml(step.input_payload || "无")}</pre></div>
              <div class="info-row"><span class="label">输出：</span><pre>${escapeHtml(step.output_payload || "暂无输出")}</pre></div>
            </details>
          </div>
        </div>
      `).join("");
    }

    function renderTraceHighlights(tracePayload = {}, replayPayload = null) {
      const taskTrace = tracePayload.task_trace || {};
      const stepTraces = safeArray(tracePayload.step_traces);
      const modelTraces = safeArray(tracePayload.model_traces);
      const toolTraces = safeArray(tracePayload.tool_traces);
      const skillTraces = safeArray(tracePayload.skill_traces);
      const retrievalTraces = safeArray(tracePayload.retrieval_traces);
      const replaySummary = replayPayload?.summary || {};
      return `
        <div class="task-summary-grid">
          <div class="task-summary-card">
            <div class="task-summary-label">Task Trace</div>
            <div class="task-summary-value">${escapeHtml(taskTrace.status || "-")}</div>
          </div>
          <div class="task-summary-card">
            <div class="task-summary-label">Replay Step Count</div>
            <div class="task-summary-value">${escapeHtml(String(replaySummary.step_count || 0))}</div>
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
        <div class="info-row"><span class="label">Task Trace 摘要：</span>${escapeHtml(taskTrace.trace_id || "-")} / ${escapeHtml(taskTrace.plan_source || replaySummary.plan_source || "-")}</div>
        <details style="margin-top: 12px;">
          <summary>查看完整追踪与 Replay</summary>
          ${renderTaskTraces(tracePayload, replayPayload)}
        </details>
      `;
    }

    function renderTaskSubmissionState() {
      const button = document.getElementById("taskSubmitButton");
      const hint = getActorOperateHint(currentActorName);
      const canRead = actorHasPermission(currentActorName, "read");
      const canOperate = actorHasPermission(currentActorName, "operate");
      if (button) {
        button.disabled = !canRead;
        button.title = canRead ? "分析输入并生成草稿" : "当前 actor 无法读取输入路由";
      }
      setTaskSubmitMessage(
        canOperate
          ? `草稿确认后可创建任务：${hint.text}`
          : `当前 actor 可分析输入，但不能直接创建任务：${hint.text}`,
        !canRead
      );
      renderTaskDraft(currentTaskDraft);
      renderAppVisibility();
      renderSettingsView();
      renderGlobalStatusBar();
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
      const select = document.getElementById("taskSkillSelect");
      if (!select) {
        return;
      }
      const previousValue = select.value;
      const activeSkills = skillRegistry.filter(item => item.status === "active");
      select.innerHTML = [
        `<option value="">直接按自然语言执行（不显式指定 skill）</option>`,
        ...activeSkills.map(item => `<option value="${escapeHtml(item.skill_id)}">${escapeHtml(item.display_name || item.skill_id)} · ${escapeHtml(item.skill_id)}@${escapeHtml(item.latest_version || "-")}</option>`)
      ].join("");
      select.value = activeSkills.some(item => item.skill_id === previousValue) ? previousValue : "";
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
      const select = document.getElementById("taskSkillSelect");
      const versionInput = document.getElementById("taskSkillVersion");
      const argsInput = document.getElementById("taskSkillArgs");
      if (!select || !versionInput || !argsInput) {
        return;
      }

      const skillId = select.value;
      if (!skillId) {
        taskSkillDetail = null;
        versionInput.value = "";
        if (!argsInput.value.trim()) {
          argsInput.value = "";
        }
        setTaskSkillMessage("当前未显式指定 skill，任务会走默认 planner。");
        return;
      }

      setTaskSkillMessage(`正在加载 skill ${skillId} …`);
      try {
        const detail = await loadSkillDetail(skillId);
        taskSkillDetail = detail;
        const versionInfo = detail.version || {};
        const packageBody = versionInfo.package_body || {};
        const argKeys = extractSkillArgKeysFromPackage(packageBody);
        versionInput.value = versionInfo.version || "";
        if (!argsInput.value.trim()) {
          argsInput.value = JSON.stringify(buildSkillDefaultArgs(argKeys), null, 2);
        }
        setTaskSkillMessage(
          `已选择 skill：${(detail.skill || {}).display_name || skillId} @ ${versionInfo.version || "-"}；建议 args：${argKeys.length ? argKeys.join(", ") : "无显式占位参数"}`
        );
      } catch (err) {
        taskSkillDetail = null;
        versionInput.value = "";
        setTaskSkillMessage(`读取 skill 详情失败：${err.message}`, true);
      }
    }

    async function changeTaskSkillSelection() {
      await syncTaskSkillSelection();
    }

    async function applySkillToTask(skillId) {
      const select = document.getElementById("taskSkillSelect");
      if (!select) {
        return;
      }
      select.value = skillId;
      await syncTaskSkillSelection();
      setAppTab("tasks");
      select.scrollIntoView({ behavior: "smooth", block: "center" });
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
      try {
        riskPolicies = await fetchJson(`${API_BASE}/risk-policies`);
        renderRiskPolicies();
        setRiskMessage("策略已同步");
      } catch (err) {
        document.getElementById("riskPolicyList").innerHTML = `<div class="empty">${escapeHtml(err.message)}</div>`;
        setRiskMessage("策略加载失败", true);
      }
    }

    async function loadMonitorOverview() {
      try {
        monitorOverview = await fetchJson(`${API_BASE}/monitor/overview`);
        renderMonitorOverview();
        renderGlobalStatusBar();
        renderHomeOverview();
        renderSettingsView();
      } catch (err) {
        document.getElementById("monitorOverview").innerHTML = `<div class="empty">${escapeHtml(err.message)}</div>`;
        renderGlobalStatusBar();
      }
    }

    async function loadChangeRequests() {
      try {
        const status = document.getElementById("changeFilterStatus")?.value || "";
        const targetType = document.getElementById("changeFilterTargetType")?.value || "";
        const proposalKind = document.getElementById("changeFilterProposalKind")?.value || "";
        const params = new URLSearchParams();
        if (status) {
          params.set("status", status);
        }
        if (targetType) {
          params.set("target_type", targetType);
        }
        if (proposalKind) {
          params.set("proposal_kind", proposalKind);
        }
        const query = params.toString();
        changeRequests = await fetchJson(`${API_BASE}/change-requests${query ? `?${query}` : ""}`);
        renderChangeRequests();
        setChangeRequestMessage("变更单已同步");
      } catch (err) {
        document.getElementById("changeRequestList").innerHTML = `<div class="empty">${escapeHtml(err.message)}</div>`;
        setChangeRequestMessage("变更单加载失败", true);
      }
    }

    async function loadAccessQuotaUsage() {
      try {
        accessQuotaUsage = await fetchJson(`${API_BASE}/access/quota-usage`);
        renderAccessQuotaUsage();
      } catch (err) {
        document.getElementById("accessQuotaList").innerHTML = `<div class="empty">${escapeHtml(err.message)}</div>`;
      }
    }

    async function loadAccessActors() {
      try {
        accessActors = await fetchJson(`${API_BASE}/access/actors`);
        renderAccessActors();
        renderActorContext();
      } catch (err) {
        document.getElementById("accessActorList").innerHTML = `<div class="empty">${escapeHtml(err.message)}</div>`;
        renderActorContext();
      }
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
      try {
        toolRegistry = await fetchJson(`${API_BASE}/tools`);
        renderToolRegistry();
      } catch (err) {
        document.getElementById("toolRegistryList").innerHTML = `<div class="empty">${escapeHtml(err.message)}</div>`;
      }
    }

    async function loadModelRegistry() {
      try {
        const [routes, providers] = await Promise.all([
          fetchJson(`${API_BASE}/model-routes`),
          fetchJson(`${API_BASE}/model-providers`)
        ]);
        modelRoutes = routes;
        modelProviders = providers;
        renderModelRegistry();
        renderGlobalStatusBar();
        renderSettingsView();
      } catch (err) {
        document.getElementById("modelRegistryList").innerHTML = `<div class="empty">${escapeHtml(err.message)}</div>`;
        renderSettingsView();
      }
    }

    function renderMonitorOverview() {
      const container = document.getElementById("monitorOverview");
      if (!monitorOverview) {
        container.innerHTML = `<div class="empty">暂无监控数据</div>`;
        return;
      }

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
      const stage5FinalizeCount = stage5SummaryValues.filter((item) => item.recommended_action === "finalize" || item.recommended_action === "finalize_retry").length;
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
          <div class="summary-pill">
            <div class="summary-pill-label">待审批阻塞</div>
            <div class="summary-pill-value">${approvalMetrics.pending_approvals || 0}</div>
          </div>
          <div class="summary-pill">
            <div class="summary-pill-label">今日 Daily Reviews</div>
            <div class="summary-pill-value">${reviewMetrics.daily_reviews_today || 0}</div>
          </div>
          <div class="summary-pill">
            <div class="summary-pill-label">强制门禁目标</div>
            <div class="summary-pill-value">${changeMetrics.enforced_target_count || 0}</div>
          </div>
          <div class="summary-pill">
            <div class="summary-pill-label">执行协议版本</div>
            <div class="summary-pill-value">${escapeHtml(runtimeMetadata.step_request_protocol_version || "-")}</div>
          </div>
          <div class="summary-pill">
            <div class="summary-pill-label">Agent 协议版本</div>
            <div class="summary-pill-value">${escapeHtml(runtimeMetadata.multi_agent_protocol_version || "-")}</div>
          </div>
          <div class="summary-pill">
            <div class="summary-pill-label">待 Execute</div>
            <div class="summary-pill-value">${agentMetrics.tasks_requiring_execute || 0}</div>
          </div>
          <div class="summary-pill">
            <div class="summary-pill-label">待 Retry</div>
            <div class="summary-pill-value">${agentMetrics.tasks_requiring_retry || 0}</div>
          </div>
          <div class="summary-pill">
            <div class="summary-pill-label">Stage 3 就绪度</div>
            <div class="summary-pill-value">${escapeHtml(formatRatio(stage3Readiness.readiness_ratio))}</div>
          </div>
          <div class="summary-pill">
            <div class="summary-pill-label">Stage 5 完成度</div>
            <div class="summary-pill-value">${escapeHtml(formatRatio(stage5Readiness.completion_ratio))}</div>
          </div>
          <div class="summary-pill">
            <div class="summary-pill-label">Stage 6 完成度</div>
            <div class="summary-pill-value">${escapeHtml(formatRatio(stage6Readiness.completion_ratio))}</div>
          </div>
          <div class="summary-pill">
            <div class="summary-pill-label">Stage 7 Groundwork</div>
            <div class="summary-pill-value">${escapeHtml(formatRatio(stage7Readiness.groundwork_ratio))}</div>
          </div>
          <div class="summary-pill">
            <div class="summary-pill-label">Stage 5 待执行</div>
            <div class="summary-pill-value">${stage5ExecuteCount}</div>
          </div>
          <div class="summary-pill">
            <div class="summary-pill-label">Stage 5 待汇总</div>
            <div class="summary-pill-value">${stage5FinalizeCount}</div>
          </div>
          <div class="summary-pill">
            <div class="summary-pill-label">Stage 5 待重跑</div>
            <div class="summary-pill-value">${stage5RetryCount}</div>
          </div>
          <div class="summary-pill">
            <div class="summary-pill-label">Stage 5 需接管</div>
            <div class="summary-pill-value">${stage5EscalationCount}</div>
          </div>
          <div class="summary-pill">
            <div class="summary-pill-label">实现状态(postrun)</div>
            <div class="summary-pill-value">${stage5MainlineCount}</div>
          </div>
          <div class="summary-pill">
            <div class="summary-pill-label">Evaluator 来源(postrun)</div>
            <div class="summary-pill-value">${stage5PostrunEvaluatorCount}</div>
          </div>
          <div class="summary-pill">
            <div class="summary-pill-label">Workflow Proposal 可见任务</div>
            <div class="summary-pill-value">${stage5WorkflowProposalVisibleCount}</div>
          </div>
          <div class="summary-pill">
            <div class="summary-pill-label">Validation Failed</div>
            <div class="summary-pill-value">${validationFailedCount}</div>
          </div>
          <div class="summary-pill">
            <div class="summary-pill-label">Recovery Actionable</div>
            <div class="summary-pill-value">${recoveryActionableCount}</div>
          </div>
        </div>

        <div class="monitor-group">
          <div class="monitor-section-title">任务运行</div>
          <div class="monitor-grid">
            <div class="metric-card">
              <div class="metric-label">任务总数</div>
              <div class="metric-value">${taskMetrics.total_tasks || 0}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">待审批</div>
              <div class="metric-value">${approvalMetrics.pending_approvals || 0}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">队列深度</div>
              <div class="metric-value">${queueMetrics.queue_depth || 0}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">活跃 Claim</div>
              <div class="metric-value">${queueMetrics.active_claims || 0}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">Checkpoint 任务</div>
              <div class="metric-value">${taskMetrics.checkpointed_tasks || 0}</div>
            </div>
          </div>
        </div>

        <div class="monitor-group">
          <div class="monitor-section-title">Session / Review</div>
          <div class="monitor-grid">
            <div class="metric-card">
              <div class="metric-label">Sessions</div>
              <div class="metric-value">${sessionMetrics.total_sessions || 0}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">Memories</div>
              <div class="metric-value">${sessionMetrics.total_memories || 0}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">Session States</div>
              <div class="metric-value">${sessionMetrics.total_session_states || 0}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">Session Reviews</div>
              <div class="metric-value">${sessionMetrics.total_session_reviews || 0}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">今日 Daily Reviews</div>
              <div class="metric-value">${reviewMetrics.daily_reviews_today || 0}</div>
            </div>
          </div>
        </div>

        <div class="monitor-group">
          <div class="monitor-section-title">Stage Readiness</div>
          <div class="monitor-grid">
            <div class="metric-card">
              <div class="metric-label">Stage 3 就绪度</div>
              <div class="metric-value">${formatRatio(stage3Readiness.readiness_ratio)}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">缺 State 的 Sessions</div>
              <div class="metric-value">${stage3Readiness.sessions_missing_state || 0}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">缺 Review 的 Sessions</div>
              <div class="metric-value">${stage3Readiness.sessions_missing_review || 0}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">需补 Daily Review</div>
              <div class="metric-value">${stage3Readiness.sessions_needing_review || 0}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">重复记忆 Sessions</div>
              <div class="metric-value">${stage3Readiness.sessions_with_duplicate_memories || 0}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">Stage 4 门禁覆盖</div>
              <div class="metric-value">${formatRatio(stage4Readiness.change_gate_coverage_ratio)}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">已应用变更单</div>
              <div class="metric-value">${stage4Readiness.change_request_applied_count || 0}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">变更闭环率</div>
              <div class="metric-value">${formatRatio(stage4Readiness.change_request_closure_ratio)}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">Actor / Quota 对齐</div>
              <div class="metric-value">${stage4Readiness.actor_quota_alignment_ok ? "OK" : "待补"}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">配额压力</div>
              <div class="metric-value">${stage4Readiness.quota_pressure_count || 0}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">Stage 5 Runtime Fanout</div>
              <div class="metric-value">${formatRatio(stage5Readiness.runtime_fanout_ratio)}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">Stage 5 角色骨架</div>
              <div class="metric-value">${formatRatio(stage5Readiness.role_skeleton_ratio)}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">Stage 5 终态收口</div>
              <div class="metric-value">${formatRatio(stage5Readiness.terminal_readiness_ratio)}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">Stage 5 Missing Postrun</div>
              <div class="metric-value">${stage5Readiness.terminal_tasks_missing_postrun || 0}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">Stage 5 非只读 Specialist</div>
              <div class="metric-value">${stage5Readiness.non_readonly_specialist_task_count || 0}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">Stage 5 Completion Gaps</div>
              <div class="metric-value">${(stage5Readiness.missing_completion_gates || []).length}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">Stage 6 Proposal 覆盖</div>
              <div class="metric-value">${formatRatio(stage6Readiness.workflow_proposal_coverage_ratio)}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">Stage 6 Auto Mapping</div>
              <div class="metric-value">${stage6Readiness.auto_mapped_proposal_count || 0}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">Stage 6 Bridge 激活</div>
              <div class="metric-value">${formatRatio(stage6Readiness.bridge_activation_ratio)}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">Stage 6 Bridged CR</div>
              <div class="metric-value">${stage6Readiness.mainline_bridged_change_request_count || 0}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">Stage 6 Failure Taxonomy</div>
              <div class="metric-value">${stage6Readiness.failure_taxonomy_count || 0}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">Stage 6 Shadow Validation</div>
              <div class="metric-value">${stage6Readiness.shadow_validation_count || 0}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">Stage 6 Completion Gaps</div>
              <div class="metric-value">${(stage6Readiness.missing_completion_gates || []).length}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">Stage 7 Groundwork</div>
              <div class="metric-value">${formatRatio(stage7Readiness.groundwork_ratio)}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">Stage 7 Workflow CR</div>
              <div class="metric-value">${stage7Readiness.workflow_improvement_change_request_count || 0}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">Stage 7 Shadow 完成</div>
              <div class="metric-value">${stage7Readiness.shadow_completed_change_request_count || 0}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">Stage 7 Candidate Overlay</div>
              <div class="metric-value">${stage7Readiness.candidate_overlay_validation_count || 0}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">Stage 7 Payload Hash Match</div>
              <div class="metric-value">${stage7Readiness.candidate_match_change_request_count || 0}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">Stage 7 Rollback Ready</div>
              <div class="metric-value">${stage7Readiness.rollback_ready_count || 0}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">Stage 7 Rollback Applied</div>
              <div class="metric-value">${stage7Readiness.rollback_applied_count || 0}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">Stage 7 Sandbox File</div>
              <div class="metric-value">${stage7Readiness.sandbox_file_applied_count || 0}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">Stage 7 Source Copy</div>
              <div class="metric-value">${stage7Readiness.sandbox_source_copy_applied_count || 0}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">Stage 7 Source Patch</div>
              <div class="metric-value">${stage7Readiness.sandbox_source_patch_applied_count || 0}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">Stage 7 Acceptance Pass</div>
              <div class="metric-value">${stage7Readiness.sandbox_acceptance_passed_count || 0}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">Stage 7 Acceptance Fail</div>
              <div class="metric-value">${stage7Readiness.sandbox_acceptance_failed_count || 0}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">Stage 7 Auto Rollback</div>
              <div class="metric-value">${stage7Readiness.sandbox_auto_rollback_applied_count || 0}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">Stage 7 Operational</div>
              <div class="metric-value">${stage7Readiness.operational ? "OK" : "待补"}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">Stage 7 Groundwork Gaps</div>
              <div class="metric-value">${(stage7Readiness.missing_groundwork_gates || []).length}</div>
            </div>
          </div>
        </div>

        <div class="monitor-group">
          <div class="monitor-section-title">治理控制面</div>
          <div class="monitor-grid">
            <div class="metric-card">
              <div class="metric-label">风险策略数</div>
              <div class="metric-value">${riskMetrics.risk_policy_count || 0}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">注册工具数</div>
              <div class="metric-value">${toolMetrics.tool_registry_count || 0}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">禁用工具数</div>
              <div class="metric-value">${toolMetrics.disabled_tool_count || 0}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">模型 Provider 数</div>
              <div class="metric-value">${modelMetrics.model_provider_count || 0}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">禁用 Provider</div>
              <div class="metric-value">${modelMetrics.disabled_model_provider_count || 0}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">模型路由数</div>
              <div class="metric-value">${modelMetrics.model_route_count || 0}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">禁用模型路由</div>
              <div class="metric-value">${modelMetrics.disabled_model_route_count || 0}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">变更单总数</div>
              <div class="metric-value">${changeMetrics.total_change_requests || 0}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">待处理变更单</div>
              <div class="metric-value">${changeMetrics.pending_change_requests || 0}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">强制门禁目标</div>
              <div class="metric-value">${changeMetrics.enforced_target_count || 0}</div>
            </div>
          </div>
        </div>

        <div class="monitor-group">
          <div class="monitor-section-title">Stage 5 基础观测</div>
          <div class="monitor-grid">
            <div class="metric-card">
              <div class="metric-label">Agent Runs</div>
              <div class="metric-value">${agentMetrics.total_agent_runs || 0}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">Running Agents</div>
              <div class="metric-value">${agentMetrics.running_agent_runs || 0}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">Blocked Agents</div>
              <div class="metric-value">${agentMetrics.blocked_agent_runs || 0}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">待 Finalize Tasks</div>
              <div class="metric-value">${agentMetrics.tasks_requiring_finalize || 0}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">待 Operator 接管</div>
              <div class="metric-value">${agentMetrics.tasks_requiring_operator_escalation || 0}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">Agent Messages</div>
              <div class="metric-value">${agentMetrics.total_agent_messages || 0}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">Agent Artifacts</div>
              <div class="metric-value">${agentMetrics.total_agent_artifacts || 0}</div>
            </div>
          </div>
        </div>

        <div class="monitor-group">
          <div class="monitor-section-title">Stage 6 Evaluator</div>
          <div class="monitor-grid">
            <div class="metric-card">
              <div class="metric-label">Evaluator Runs</div>
              <div class="metric-value">${evaluatorMetrics.total_evaluator_runs || 0}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">平均评分</div>
              <div class="metric-value">${escapeHtml(evaluatorMetrics.avg_score == null ? "-" : Number(evaluatorMetrics.avg_score).toFixed(1))}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">Approved</div>
              <div class="metric-value">${(evaluatorMetrics.runs_by_decision || {}).approved || 0}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">Rework</div>
              <div class="metric-value">${(evaluatorMetrics.runs_by_decision || {}).rework_required || 0}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">Rejected</div>
              <div class="metric-value">${(evaluatorMetrics.runs_by_decision || {}).rejected || 0}</div>
            </div>
          </div>
        </div>

        <div class="monitor-group">
          <div class="monitor-section-title">访问控制</div>
          <div class="monitor-grid">
            <div class="metric-card">
              <div class="metric-label">Actors</div>
              <div class="metric-value">${accessMetrics.actor_count || 0}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">Quotas</div>
              <div class="metric-value">${accessMetrics.quota_count || 0}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">配额压力</div>
              <div class="metric-value">${accessMetrics.quota_pressure_count || 0}</div>
            </div>
          </div>
        </div>

        <div class="info-row">
          <span class="label">状态分布：</span>
          ${escapeHtml(
            Object.entries(tasksByStatus)
              .map(([status, count]) => `${status}=${count}`)
              .join(" / ") || "暂无"
          )}
        </div>
        <div class="info-row">
          <span class="label">生成时间：</span>${escapeHtml(monitorOverview.generated_at || "-")}
        </div>
        <div class="info-row">
          <span class="label">最近 Daily Review：</span>${escapeHtml(reviewMetrics.last_daily_review_at || "-")}
        </div>
        <div class="info-row">
          <span class="label">Step Request 协议：</span>${escapeHtml(runtimeMetadata.step_request_protocol_version || "-")}
        </div>
        <div class="info-row">
          <span class="label">Multi-Agent 协议：</span>${escapeHtml(runtimeMetadata.multi_agent_protocol_version || "-")}
        </div>
        <div class="info-row">
          <span class="label">角色分布：</span>${escapeHtml(
            Object.entries(accessMetrics.actors_by_role || {})
              .map(([role, count]) => `${role}=${count}`)
              .join(" / ") || "暂无"
          )}
        </div>
        <div class="info-row">
          <span class="label">Agent 状态分布：</span>${escapeHtml(
            Object.entries(agentMetrics.agent_runs_by_status || {})
              .map(([status, count]) => `${status}=${count}`)
              .join(" / ") || "暂无"
          )}
        </div>
        <div class="info-row">
          <span class="label">Agent 角色分布：</span>${escapeHtml(
            Object.entries(agentMetrics.agent_runs_by_role || {})
              .map(([role, count]) => `${role}=${count}`)
              .join(" / ") || "暂无"
          )}
        </div>

        <div class="monitor-section-title">最近任务</div>
        <div class="monitor-list">
          ${recentTasks.length ? recentTasks.map(item => `
            <div class="monitor-item">
              <div class="monitor-item-title">#${item.id} ${escapeHtml(item.status || "")}</div>
              <div class="monitor-item-meta">${escapeHtml(item.display_user_input || item.user_input || "")}</div>
              <div class="monitor-item-meta">更新时间：${escapeHtml(item.updated_at || "-")}</div>
            </div>
          `).join("") : `<div class="empty">暂无最近任务</div>`}
        </div>

        <div class="monitor-section-title">最近审计事件</div>
        <div class="monitor-list">
          ${recentAuditLogs.length ? recentAuditLogs.map(item => `
            <div class="monitor-item">
              <div class="monitor-item-title">${escapeHtml(item.event_type || "")}</div>
              <div class="monitor-item-meta">actor=${escapeHtml(item.actor || "")} / task_id=${escapeHtml(item.task_id ?? "-")}</div>
              <div class="monitor-item-meta">details=${escapeHtml(JSON.stringify(item.details || {}))}</div>
            </div>
          `).join("") : `<div class="empty">暂无审计事件</div>`}
        </div>

        <div class="monitor-section-title">最近 Reviews</div>
        <div class="monitor-list">
          ${recentReviews.length ? recentReviews.map(item => `
            <div class="monitor-item">
              <div class="monitor-item-title">session=${escapeHtml(item.session_id ?? "-")} / ${escapeHtml(item.review_kind || "")}</div>
              <div class="monitor-item-meta">${escapeHtml(item.summary_text || "")}</div>
              <div class="monitor-item-meta">open_loops=${escapeHtml(String((item.open_loops || []).length))} / created_at=${escapeHtml(item.created_at || "-")}</div>
            </div>
          `).join("") : `<div class="empty">暂无 review</div>`}
        </div>

        <div class="monitor-section-title">最近 Agent Runs</div>
        <div class="monitor-list">
          ${recentAgentRuns.length ? recentAgentRuns.map(item => `
            <div class="monitor-item">
              <div class="monitor-item-title">#${item.id} / task=${escapeHtml(item.task_run_id ?? "-")} / ${escapeHtml(item.role || "")} / ${escapeHtml(item.status || "")}</div>
              <div class="monitor-item-meta">attempt=${escapeHtml(String(item.attempt || 1))} / model=${escapeHtml(item.assigned_model || "-")} / profile=${escapeHtml(item.assigned_tool_profile || "-")}</div>
              <div class="monitor-item-meta">updated_at=${escapeHtml(item.updated_at || "-")}</div>
            </div>
          `).join("") : `<div class="empty">暂无 agent run</div>`}
        </div>

        <div class="monitor-section-title">最近 Evaluator Runs</div>
        <div class="monitor-list">
          ${recentEvaluatorRuns.length ? recentEvaluatorRuns.map(item => `
            <div class="monitor-item">
              <div class="monitor-item-title">#${item.id} / task=${escapeHtml(item.task_run_id ?? "-")} / ${escapeHtml(item.decision || "")}</div>
              <div class="monitor-item-meta">score=${escapeHtml(String(item.score ?? "-"))} / recommendation=${escapeHtml(item.recommendation || "-")}</div>
              <div class="monitor-item-meta">source=${escapeHtml(item.source || "-")} / created_at=${escapeHtml(item.created_at || "-")}</div>
            </div>
          `).join("") : `<div class="empty">暂无 evaluator run</div>`}
        </div>
      `;
    }

    function renderChangeRequests() {
      const container = document.getElementById("changeRequestList");
      if (!changeRequests.length) {
        container.innerHTML = `<div class="empty">暂无变更单</div>`;
        return;
      }

      const latestRollbackBySource = new Map();
      changeRequests.forEach((item) => {
        if (item.proposal_kind === "rollback" && item.source_change_request_id) {
          const sourceId = Number(item.source_change_request_id);
          const current = latestRollbackBySource.get(sourceId);
          if (!current || Number(item.id || 0) > Number(current.id || 0)) {
            latestRollbackBySource.set(sourceId, item);
          }
        }
      });

      const previewJson = (value, maxLines = 8) => {
        const text = JSON.stringify(value || {}, null, 2);
        const lines = text.split("\n");
        if (lines.length <= maxLines) {
          return text;
        }
        return `${lines.slice(0, maxLines).join("\n")}\n... (${lines.length - maxLines} more lines)`;
      };

      container.innerHTML = changeRequests.slice(0, 12).map((item) => {
        const patchSummary = String(item.patch_summary || "").trim();
        const payloadPatch = item.payload_patch || {};
        const baselinePayload = item.baseline_payload || {};
        const changedKeyCount = Number(payloadPatch.changed_key_count || 0);
        const hasPatchPreview = changedKeyCount > 0;
        const hasBaselinePreview = Object.keys(baselinePayload).length > 0;
        const rollbackItem = item.status === "applied" ? latestRollbackBySource.get(Number(item.id || 0)) : null;
        const shadowValidationStatus = String(item.shadow_validation_status || "not_required");
        const shadowValidationReady = Boolean(item.shadow_validation_ready_to_apply);
        const shadowValidationReport = item.shadow_validation_report || {};
        const shadowValidationDetails = shadowValidationReport.validation || {};
        const shadowValidationResult = String(shadowValidationDetails.validation_result || "-");
        const shadowValidationMode = String(shadowValidationDetails.validation_mode || "-");
        const shadowValidationTaskId = shadowValidationDetails.shadow_task_id || "-";
        const shadowValidationAuditId = shadowValidationReport.audit_log_id || "-";
        const proposedPayloadHash = String(item.proposed_payload_hash || "-");
        const candidateMatch = String(item.shadow_validation_candidate_match);
        const acceptanceStatus = String(item.acceptance_status || "not_configured");
        const autoRollbackId = item.auto_rollback_change_request_id || "-";
        return `
        <div class="governance-card" data-testid="access-quota-card">
          <div class="governance-card-title">#${item.id} / ${escapeHtml(item.target_type)} / ${escapeHtml(item.target_key)}</div>
          <div class="governance-card-meta">
            status=${escapeHtml(item.status)} · proposal_kind=${escapeHtml(item.proposal_kind || "manual_change")} · requested_by=${escapeHtml(item.requested_by_actor || "-")} · reviewed_by=${escapeHtml(item.reviewed_by_actor || "-")}
          </div>
          ${item.source_change_request_id ? `<div class="info-row"><span class="label">Source CR：</span>#${escapeHtml(String(item.source_change_request_id))}</div>` : ""}
          ${item.source_workflow_proposal_id ? `<div class="info-row"><span class="label">Source Proposal：</span>#${escapeHtml(String(item.source_workflow_proposal_id))}</div>` : ""}
          <div class="info-row"><span class="label">Rationale：</span>${escapeHtml(item.rationale || "无")}</div>
          <div class="info-row"><span class="label">Patch：</span>${escapeHtml(patchSummary || "无")} · changed_keys=${escapeHtml(String(changedKeyCount || 0))} · payload_hash=${escapeHtml(proposedPayloadHash)}</div>
          <div class="info-row"><span class="label">Payload：</span><pre>${escapeHtml(previewJson(item.proposed_payload || {}, 8))}</pre></div>
          ${hasPatchPreview ? `<div class="info-row"><span class="label">Patch Preview：</span><pre>${escapeHtml(previewJson(payloadPatch, 8))}</pre></div>` : ""}
          ${hasBaselinePreview ? `<div class="info-row"><span class="label">Baseline Preview：</span><pre>${escapeHtml(previewJson(baselinePayload, 8))}</pre></div>` : ""}
          <div class="info-row"><span class="label">Shadow Validation：</span>status=${escapeHtml(shadowValidationStatus)} · ready_to_apply=${escapeHtml(String(shadowValidationReady))} · result=${escapeHtml(shadowValidationResult)} · mode=${escapeHtml(shadowValidationMode)} · candidate_match=${escapeHtml(candidateMatch)}</div>
          ${item.requires_shadow_validation ? `<div class="info-row"><span class="label">Shadow Context：</span>proposal=#${escapeHtml(String(item.source_workflow_proposal_id || "-"))} · shadow_task=#${escapeHtml(String(shadowValidationTaskId))} · audit=#${escapeHtml(String(shadowValidationAuditId))}</div>` : ""}
          <div class="info-row"><span class="label">Acceptance：</span>status=${escapeHtml(acceptanceStatus)} · auto_rollback=${escapeHtml(String(Boolean(item.auto_rollback_applied)))} · rollback_cr=#${escapeHtml(String(autoRollbackId))}</div>
          <div class="info-row"><span class="label">Rollback：</span>ready=${escapeHtml(String(Boolean(item.rollback_ready)))} · note=${escapeHtml(item.rollback_note || "无")}</div>
          ${rollbackItem
            ? `<div class="info-row"><span class="label">Rollback 单：</span>#${escapeHtml(String(rollbackItem.id || "-"))} · status=${escapeHtml(rollbackItem.status || "-")}</div>`
            : ""}
          <div class="top-actions">
            ${item.status === "pending" ? `<button onclick="decideChangeRequest(${item.id}, true)">批准</button><button class="secondary-btn" onclick="decideChangeRequest(${item.id}, false)">拒绝</button>` : ""}
            ${item.requires_shadow_validation && item.source_workflow_proposal_id && !shadowValidationReady && (item.status === "pending" || item.status === "approved")
              ? `<button class="secondary-btn" onclick="runChangeRequestShadowValidation(${item.id})">跑 Shadow Validation</button>`
              : ""}
            ${item.requires_shadow_validation && item.source_workflow_proposal_id
              ? `<button class="ghost-btn" onclick="showChangeRequestShadowValidation(${item.id})">查看 Shadow 状态</button>`
              : ""}
            ${item.status === "approved" && shadowValidationReady ? `<button onclick="applyChangeRequest(${item.id})">应用</button>` : ""}
            ${item.status === "approved" && !item.requires_shadow_validation ? `<button onclick="applyChangeRequest(${item.id})">应用</button>` : ""}
            ${item.status === "applied" && item.can_create_rollback ? `<button class="ghost-btn" onclick="createRollbackChangeRequest(${item.id})">创建回滚单</button>` : ""}
          </div>
        </div>
      `;
      }).join("");
    }

    function renderAccessQuotaUsage() {
      const container = document.getElementById("accessQuotaList");
      if (!accessQuotaUsage.length) {
        container.innerHTML = `<div class="empty">暂无配额使用数据</div>`;
        return;
      }

      container.innerHTML = accessQuotaUsage.map(item => `
        <div class="governance-card">
          <div class="governance-card-title">${escapeHtml(item.actor_name)} / ${escapeHtml(item.role)}</div>
          <div class="governance-card-meta">
            daily ${escapeHtml(String(item.daily_task_count))}/${escapeHtml(String(item.daily_task_limit))} ·
            active ${escapeHtml(String(item.active_task_count))}/${escapeHtml(String(item.active_task_limit))} ·
            tokens ${escapeHtml(String(item.daily_token_count || 0))}/${escapeHtml(String(item.daily_token_limit || 0))}
          </div>
          <div class="info-row"><span class="label">今日剩余额度：</span>${escapeHtml(String(item.daily_remaining))}</div>
          <div class="info-row"><span class="label">活跃剩余额度：</span>${escapeHtml(String(item.active_remaining))}</div>
          <div class="info-row"><span class="label">Token 剩余额度：</span>${escapeHtml(String(item.daily_token_remaining || 0))}</div>
          <div class="info-row"><span class="label">并行 Agent 上限：</span>${escapeHtml(String(item.max_parallel_agents || 0))}</div>
          <div class="governance-card-actions">
            <button class="ghost-btn" onclick="openChangeRequestTemplate('access_quota', '${escapeHtml(item.actor_name)}', JSON.parse(decodeURIComponent('${encodeURIComponent(JSON.stringify({
              daily_task_limit: item.daily_task_limit,
              active_task_limit: item.active_task_limit,
              daily_token_limit: item.daily_token_limit || 0,
              max_parallel_agents: item.max_parallel_agents || 0
            }))}')), '调整 actor 配额')">发起配额变更</button>
            <button class="ghost-btn" onclick="openChangeRequestTemplate('access_actor', '${escapeHtml(item.actor_name)}', JSON.parse(decodeURIComponent('${encodeURIComponent(JSON.stringify({
              role: item.role,
              description: `当前 ${item.actor_name} 配置`
            }))}')), '调整 actor 角色')">发起角色变更</button>
          </div>
        </div>
      `).join("");
    }

    function renderAccessActors() {
      const container = document.getElementById("accessActorList");
      if (!accessActors.length) {
        container.innerHTML = `<div class="empty">暂无 actor 数据</div>`;
        return;
      }

      container.innerHTML = accessActors.map(item => `
        <div class="governance-card">
          <div class="governance-card-title">${escapeHtml(item.actor_name)}</div>
          <div class="governance-card-meta">role=${escapeHtml(item.role || "-")} · tenant=${escapeHtml(item.tenant_key || "default")}</div>
          <div class="info-row"><span class="label">描述：</span>${escapeHtml(item.description || "无")}</div>
          <div class="info-row"><span class="label">权限覆盖：</span>${escapeHtml((item.permission_overrides || []).join(", ") || "无")}</div>
          <div class="info-row"><span class="label">生效权限：</span>${escapeHtml((item.permissions || []).join(", ") || "无")}</div>
          <div class="governance-card-actions">
            <button class="ghost-btn" onclick="openChangeRequestTemplate('access_actor', '${escapeHtml(item.actor_name)}', JSON.parse(decodeURIComponent('${encodeURIComponent(JSON.stringify({
              role: item.role,
              description: item.description || "",
              tenant_key: item.tenant_key || "default",
              permission_overrides: item.permission_overrides || []
            }))}')), '更新 actor 角色或描述')">发起角色变更</button>
            <button class="ghost-btn" onclick="openChangeRequestTemplate('access_quota', '${escapeHtml(item.actor_name)}', JSON.parse(decodeURIComponent('${encodeURIComponent(JSON.stringify({
              daily_task_limit: 30,
              active_task_limit: 10,
              daily_token_limit: 300000,
              max_parallel_agents: 16
            }))}')), '更新 actor 配额')">发起配额变更</button>
          </div>
        </div>
      `).join("");
    }

    function renderToolRegistry() {
      const container = document.getElementById("toolRegistryList");
      if (!toolRegistry.length) {
        container.innerHTML = `<div class="empty">暂无工具注册数据</div>`;
        return;
      }

      container.innerHTML = toolRegistry.map(item => `
        <div class="governance-card">
          <div class="governance-card-title">${escapeHtml(item.tool_name)}</div>
          <div class="governance-card-meta">
            enabled=${escapeHtml(String(item.enabled))} · provider=${escapeHtml(item.provider_type || "-")} · risk=${escapeHtml(item.risk_level || "-")}
          </div>
          <div class="info-row"><span class="label">Transport：</span>${escapeHtml(item.transport || "-")}</div>
          <div class="info-row"><span class="label">Server：</span>${escapeHtml(item.server_name || "-")}</div>
          <div class="info-row"><span class="label">审批：</span>${item.approval_required ? "需要" : "否"}</div>
          <div class="info-row"><span class="label">Provider Config：</span><pre>${escapeHtml(JSON.stringify(item.provider_config || {}, null, 2))}</pre></div>
          <div class="info-row"><span class="label">说明：</span>${escapeHtml(item.description || "无")}</div>
        </div>
      `).join("");
    }

    function renderModelRegistry() {
      const container = document.getElementById("modelRegistryList");
      const providerHtml = modelProviders.map(item => `
        <div class="governance-card">
          <div class="governance-card-title">Provider / ${escapeHtml(item.provider_name)}</div>
          <div class="governance-card-meta">
            enabled=${escapeHtml(String(item.enabled))} · driver=${escapeHtml(item.driver || "-")}
          </div>
          <div class="info-row"><span class="label">Base URL：</span><span class="inline-code">${escapeHtml(item.base_url || "-")}</span></div>
          <div class="info-row"><span class="label">API Key Env：</span><span class="inline-code">${escapeHtml(item.api_key_env || "-")}</span></div>
        </div>
      `).join("");
      const routeHtml = modelRoutes.map(item => `
        <div class="governance-card">
          <div class="governance-card-title">Route / ${escapeHtml(item.route_name)}</div>
          <div class="governance-card-meta">
            enabled=${escapeHtml(String(item.enabled))} · provider=${escapeHtml(item.provider || "-")}
          </div>
          <div class="info-row"><span class="label">Model：</span>${escapeHtml(item.model_name || "-")}</div>
          <div class="info-row"><span class="label">Temperature：</span>${escapeHtml(String(item.temperature ?? "-"))}</div>
          <div class="info-row"><span class="label">Max Tokens：</span>${escapeHtml(String(item.max_tokens ?? "-"))}</div>
        </div>
      `).join("");

      container.innerHTML = providerHtml || routeHtml ? `${providerHtml}${routeHtml}` : `<div class="empty">暂无模型治理数据</div>`;
    }

    async function runDailyReviews() {
      const note = window.prompt("请输入 daily review 备注（可留空）", "") ?? "";
      try {
        setAppTab("monitor");
        const result = await fetchJson(`${API_BASE}/reviews/daily-run`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json"
          },
          body: JSON.stringify({
            review_kind: "daily",
            note,
            session_limit: 20,
            active_within_hours: 24,
            force: false
          })
        });
        await loadMonitorOverview();
        if (selectedTaskId !== null) {
          await selectTask(selectedTaskId);
        }
        if (selectedSessionId !== null) {
          await refreshSelectedSessionBrowser(selectedSessionId);
        }
        alert(`Daily review 已触发。created=${(result.created || []).length}, skipped=${(result.skipped || []).length}`);
      } catch (err) {
        alert(err.message);
      }
    }

    function renderRiskPolicies() {
      const container = document.getElementById("riskPolicyList");
      if (!riskPolicies.length) {
        container.innerHTML = `<div class="empty">暂无策略</div>`;
        return;
      }

      container.innerHTML = riskPolicies
        .map(policy => {
          const editing = riskEditorKey === policy.policy_key;
          const sanitizedKey = sanitizePolicyKey(policy.policy_key);
          const displayValue =
            policy.value_type === "bool"
              ? policy.policy_value ? "true" : "false"
              : Array.isArray(policy.policy_value)
                ? JSON.stringify(policy.policy_value)
                : `${policy.policy_value}`;
          const editor =
            editing
              ? policy.value_type === "bool"
                ? `
                  <div class="risk-editor">
                    <label class="risk-meta">当前值：${escapeHtml(displayValue)}</label>
                    <select id="risk-input-${sanitizedKey}">
                      <option value="true" ${policy.policy_value ? "selected" : ""}>true</option>
                      <option value="false" ${policy.policy_value ? "" : "selected"}>false</option>
                    </select>
                    <div class="top-actions">
                      <button onclick="saveRiskPolicy('${policy.policy_key}', 'bool')">保存</button>
                      <button class="secondary-btn" onclick="cancelRiskEdit()">取消</button>
                    </div>
                  </div>
                `
                : `
                  <div class="risk-editor">
                    <label class="risk-meta">请以 JSON 数组填写字符串列表，例如 ["GET","POST"]</label>
                    <textarea id="risk-input-${sanitizedKey}" rows="3">${escapeHtml(
                      JSON.stringify(policy.policy_value || [], null, 2)
                    )}</textarea>
                    <div class="top-actions">
                      <button onclick="saveRiskPolicy('${policy.policy_key}', 'json')">保存</button>
                      <button class="secondary-btn" onclick="cancelRiskEdit()">取消</button>
                    </div>
                  </div>
                `
              : "";

          return `
            <div class="risk-card">
              <div class="policy-key">${escapeHtml(policy.policy_key)}</div>
              <div class="risk-meta">${escapeHtml(policy.description)}</div>
              <div class="risk-meta"><span class="label">类型：</span>${escapeHtml(policy.value_type)}</div>
              <div class="risk-value">${escapeHtml(displayValue)}</div>
              <div class="top-actions">
                <button onclick="toggleRiskEditor('${policy.policy_key}')">${editing ? "关闭编辑" : "编辑"}</button>
              </div>
              ${editing ? editor : ""}
            </div>
          `;
        })
        .join("");
    }

    function toggleRiskEditor(policyKey) {
      riskEditorKey = riskEditorKey === policyKey ? "" : policyKey;
      renderRiskPolicies();
    }

    function cancelRiskEdit() {
      riskEditorKey = "";
      renderRiskPolicies();
    }

    async function saveRiskPolicy(policyKey, valueType) {
      const sanitizedKey = sanitizePolicyKey(policyKey);
      let payloadValue;
      if (valueType === "bool") {
        const select = document.getElementById(`risk-input-${sanitizedKey}`);
        payloadValue = select.value === "true";
      } else {
        const input = document.getElementById(`risk-input-${sanitizedKey}`);
        try {
          payloadValue = JSON.parse(input.value);
          if (!Array.isArray(payloadValue)) {
            throw new Error("需要提供 JSON 数组");
          }
        } catch (err) {
          setRiskMessage(`解析失败：${err.message}`, true);
          return;
        }
      }

      try {
        await fetchJson(`${API_BASE}/risk-policies/${encodeURIComponent(policyKey)}`, {
          method: "PUT",
          headers: {
            "Content-Type": "application/json"
          },
          body: JSON.stringify({ policy_value: payloadValue })
        });
        riskEditorKey = "";
        setRiskMessage(`策略 ${policyKey} 保存成功`);
        await loadRiskPolicies();
      } catch (err) {
        setRiskMessage(err.message, true);
      }
    }

    async function loadTasks() {
      try {
        const tasks = await fetchJson(`${API_BASE}/tasks?include_stage5_summary=true&limit=40`);
        allTasks = Array.isArray(tasks) ? tasks : [];
        taskAgentSummaries = new Map(
          allTasks
            .map((task) => [task.id, task.stage5 || null])
            .filter(([, summary]) => Boolean(summary))
        );
        renderTasksView();
        renderHomeOverview();
        renderGlobalStatusBar();
        renderSettingsView();
        if (monitorOverview) {
          renderMonitorOverview();
        }
      } catch (err) {
        document.getElementById("taskList").innerHTML = `<div class="empty">${escapeHtml(err.message)}</div>`;
        const homePending = document.getElementById("homePendingList");
        if (homePending) {
          homePending.innerHTML = `<div class="empty">${escapeHtml(err.message)}</div>`;
        }
      }
    }

    function renderSessionsList() {
      const sessionList = document.getElementById("sessionList");
      if (!sessionList) {
        return;
      }

      if (!sessions.length) {
        sessionList.innerHTML = `<div class="empty">暂无 sessions</div>`;
        const detail = document.getElementById("sessionBrowserDetail");
        if (detail) {
          detail.innerHTML = `<div class="empty">当前没有可查看的 session</div>`;
        }
        sessionBrowserSnapshot = null;
        return;
      }

      sessionList.innerHTML = sessions.map((session) => `
        <div class="task-card ${session.id === selectedSessionId ? "active" : ""}" onclick="selectSession(${session.id})">
          <div class="task-title">#${session.id} ${escapeHtml(session.name || "未命名 session")}</div>
          <div class="task-meta">${escapeHtml(session.description || "无描述")}</div>
          <div class="task-meta">更新时间：${escapeHtml(session.updated_at || "-")}</div>
        </div>
      `).join("");
    }

    async function loadSessions(options = {}) {
      const reloadDetail = options.reloadDetail !== false;
      try {
        sessions = await fetchJson(`${API_BASE}/sessions`);
        renderSessionsList();

        if (!sessions.length) {
          selectedSessionId = null;
          window.localStorage.removeItem("ai-assistant-session-browser");
          return;
        }

        if (selectedSessionId === null || !sessions.some((item) => item.id === selectedSessionId)) {
          selectedSessionId = sessions[0].id;
          window.localStorage.setItem("ai-assistant-session-browser", String(selectedSessionId));
        }

        if (reloadDetail) {
          await loadSessionBrowserDetail(selectedSessionId);
        }
      } catch (err) {
        const sessionList = document.getElementById("sessionList");
        if (sessionList) {
          sessionList.innerHTML = `<div class="empty">${escapeHtml(err.message)}</div>`;
        }
      }
    }

    function selectSession(sessionId, focusTab = false) {
      selectedSessionId = sessionId;
      window.localStorage.setItem("ai-assistant-session-browser", String(sessionId));
      renderSessionsList();

      if (focusTab) {
        setAppTab("sessions");
      }

      void loadSessionBrowserDetail(sessionId);
    }

    function openSessionBrowser(sessionId) {
      selectSession(sessionId, true);
    }

    async function loadSessionBrowserDetail(sessionId) {
      const detailEl = document.getElementById("sessionBrowserDetail");
      if (!detailEl) {
        return;
      }

      const token = ++sessionBrowserRequestToken;
      detailEl.innerHTML = `<div class="empty">正在加载 session #${sessionId}…</div>`;

      try {
        const [summary, reviews] = await Promise.all([
          fetchJson(`${API_BASE}/sessions/${sessionId}/summary`),
          fetchJson(`${API_BASE}/sessions/${sessionId}/reviews?limit=5`)
        ]);
        if (token !== sessionBrowserRequestToken) {
          return;
        }

        const session = summary.session || { id: sessionId };
        const health = summary.health || {};
        const state = summary.session_state || {};
        const recentTasks = summary.recent_tasks || [];
        const recommendedActions = health.recommended_actions || [];
        const latestTask = recentTasks[0];
        sessionBrowserSnapshot = {
          sessionId,
          session,
          summary,
          reviews,
        };

        detailEl.innerHTML = `
          <div class="session-detail-stack">
            <div class="session-detail-head">
              <div>
                <div class="panel-title">#${session.id} ${escapeHtml(session.name || "未命名 session")}</div>
                <div class="panel-subtitle">${escapeHtml(session.description || "无描述")} · 创建于 ${escapeHtml(session.created_at || "-")} · 更新于 ${escapeHtml(session.updated_at || "-")}</div>
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
                <div class="task-summary-value">${escapeHtml(String(summary.task_metrics?.total_tasks || 0))}</div>
              </div>
              <div class="task-summary-card">
                <div class="task-summary-label">Memories</div>
                <div class="task-summary-value">${escapeHtml(String(summary.memory_metrics?.total_memories || 0))}</div>
              </div>
              <div class="task-summary-card">
                <div class="task-summary-label">Pending Approvals</div>
                <div class="task-summary-value">${escapeHtml(String(summary.approval_metrics?.pending_approvals || 0))}</div>
              </div>
              <div class="task-summary-card">
                <div class="task-summary-label">Recent Task</div>
                <div class="task-summary-value">${latestTask ? `#${latestTask.id}` : "无"}</div>
              </div>
            </div>

            <div class="session-health-grid">
              <div class="session-health-card">
                <div class="session-health-label">Active Tasks</div>
                <div class="session-health-value">${escapeHtml(String(health.active_task_count || 0))}</div>
              </div>
              <div class="session-health-card">
                <div class="session-health-label">Reviews</div>
                <div class="session-health-value">${escapeHtml(String(health.total_reviews || 0))}</div>
              </div>
              <div class="session-health-card">
                <div class="session-health-label">Open Loops</div>
                <div class="session-health-value">${escapeHtml(String(health.open_loop_count || 0))}</div>
              </div>
              <div class="session-health-card">
                <div class="session-health-label">State Stale</div>
                <div class="session-health-value">${health.state_is_stale ? "是" : "否"}</div>
              </div>
            </div>
            ${renderSessionRecommendedActions(sessionId, recommendedActions)}

            <div class="session-detail-grid">
              <div class="panel" style="margin-bottom: 0;">
                <div class="panel-title">Summary</div>
                <div class="panel-subtitle">任务、记忆和 review 汇总。</div>
                <div class="info-row"><span class="label">任务分布：</span>${escapeHtml(
                  Object.entries(summary.task_metrics?.tasks_by_status || {})
                    .map(([status, count]) => `${status}=${count}`)
                    .join(" / ") || "暂无"
                )}</div>
                <div class="info-row"><span class="label">记忆分布：</span>${escapeHtml(
                  Object.entries(summary.memory_metrics?.by_category || {})
                    .map(([category, count]) => `${category}=${count}`)
                    .join(" / ") || "暂无"
                )}</div>
                <div class="info-row"><span class="label">State 摘要：</span>${escapeHtml(state.summary_text || "暂无")}</div>
                <div class="info-row"><span class="label">推荐动作：</span><pre>${escapeHtml(
                  recommendedActions.length
                    ? recommendedActions.map((item) => `${item.action}: ${item.reason}`).join("\n")
                    : "当前没有明显阻塞"
                )}</pre></div>
                <div class="info-row"><span class="label">最近任务：</span>
                  <pre>${escapeHtml(
                    recentTasks.length
                      ? recentTasks.map((item) => `#${item.id} ${item.status || ""} | ${item.display_user_input || item.user_input || ""}`).join("\n")
                      : "暂无任务"
                  )}</pre>
                </div>
              </div>

              <div class="panel" style="margin-bottom: 0;">
                <div class="panel-title">Health / State</div>
                <div class="panel-subtitle">查看 working memory、健康信号和今日 review 覆盖。</div>
                <div class="info-row"><span class="label">Health：</span>${escapeHtml(
                  `active=${health.active_task_count || 0} / reviews=${health.total_reviews || 0} / stale=${health.state_is_stale ? "yes" : "no"} / open_loops=${health.open_loop_count || 0}`
                )}</div>
                <div class="info-row"><span class="label">今日 Daily Review：</span>${health.daily_review_today ? "已覆盖" : "未覆盖"}</div>
                <div class="info-row"><span class="label">Preferences：</span><pre>${escapeHtml((state.preferences || []).join("\n") || "暂无")}</pre></div>
                <div class="info-row"><span class="label">Open Loops：</span><pre>${escapeHtml((state.open_loops || []).join("\n") || "暂无")}</pre></div>
              </div>
            </div>

            <div class="panel" style="margin-bottom: 0;">
              <div class="panel-title">Reviews</div>
              <div class="panel-subtitle">最近的 session reviews。</div>
              ${
                reviews.length
                  ? reviews.map((item) => `
                    <div class="step-card">
                      <div class="step-title">Review #${item.id} / ${escapeHtml(item.review_kind || "")}</div>
                      <div class="info-row"><span class="label">摘要：</span>${escapeHtml(item.summary_text || "无")}</div>
                      <div class="info-row"><span class="label">Open Loops：</span>${escapeHtml(String((item.open_loops || []).length))}</div>
                      <div class="info-row"><span class="label">创建时间：</span>${escapeHtml(item.created_at || "-")}</div>
                      <div class="info-row"><span class="label">Highlights：</span><pre>${escapeHtml((item.highlights || []).join("\n") || "暂无")}</pre></div>
                    </div>
                  `).join("")
                  : `<div class="empty">暂无 reviews</div>`
              }
            </div>
          </div>
        `;
      } catch (err) {
        if (token !== sessionBrowserRequestToken) {
          return;
        }
        detailEl.innerHTML = `<div class="empty">${escapeHtml(err.message)}</div>`;
      }
    }

    async function refreshSelectedSessionBrowser(sessionId) {
      if (selectedSessionId !== sessionId) {
        return;
      }
      await loadSessionBrowserDetail(sessionId);
      await loadSessions({ reloadDetail: false });
    }

    function renderSessionRecommendedActions(sessionId, recommendedActions = []) {
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
          const title = item.reason ? ` title="${escapeHtml(item.reason)}"` : "";
          return `<button type="button" class="session-action-chip ghost-btn" onclick="${meta.handler}"${title}>${escapeHtml(meta.label)}</button>`;
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

    function renderTaskAgentRuns(taskId, agentRuns = [], agentDetails = {}) {
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
          <div class="info-row"><span class="label">Brief 子任务：</span>${escapeHtml(briefExecutionRequest.subtask_type || "-")}</div>
          <div class="info-row"><span class="label">执行模式：</span>${escapeHtml(subtask.execution_mode || executionResult.execution_mode || "-")}</div>
          <div class="info-row"><span class="label">子任务类型：</span>${escapeHtml(subtask.type || executionResult.subtask_type || "-")}</div>
          <div class="info-row"><span class="label">步骤覆盖：</span>${escapeHtml((assignedOrders.length ? assignedOrders.join(", ") : "fallback").toString())}</div>
          <div class="info-row"><span class="label">建议后续：</span>${escapeHtml((followups.length ? followups.join("；") : "无").toString())}</div>
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
            <div class="info-row"><span class="label">实现状态：</span>${escapeHtml(summary.implementation_status || "-")}</div>
            <div class="info-row"><span class="label">推荐动作：</span>${escapeHtml(summary.recommended_action || "none")}</div>
            <div class="info-row"><span class="label">等待角色：</span>${escapeHtml(summary.awaiting_role || "-")}</div>
            <div class="info-row"><span class="label">阻塞原因：</span>${escapeHtml(summary.blocking_reason || "-")}</div>
            <div class="info-row"><span class="label">执行后端：</span>${escapeHtml(summary.execution_backend || "none")}</div>
            <div class="info-row"><span class="label">执行模式：</span>${escapeHtml((summary.specialist_execution_modes || []).join(" / ") || "-")}</div>
            <div class="info-row"><span class="label">Manager 状态：</span>${escapeHtml(summary.manager?.status || "-")}</div>
            <div class="info-row"><span class="label">Reviewer 决策：</span>${escapeHtml(summary.latest_reviewer_decision || "-")}</div>
            <div class="info-row"><span class="label">决策来源：</span>${escapeHtml(summary.latest_decision_source || "-")}</div>
            <div class="info-row"><span class="label">Next Strategy：</span>${escapeHtml(summary.latest_next_strategy || "-")}</div>
            <div class="info-row"><span class="label">Final 版本：</span>${escapeHtml(String(latestFinal?.version || 0))}</div>
            <div class="info-row"><span class="label">Review 版本：</span>${escapeHtml(String(latestReview?.version || 0))}</div>
            <div class="info-row"><span class="label">Quality Score：</span>${escapeHtml(String(latestFinal?.quality_score ?? latestReview?.quality_score ?? "-"))}</div>
            <div class="info-row"><span class="label">Evaluator 决策：</span>${escapeHtml(latestEvaluator?.decision || "-")}</div>
            <div class="info-row"><span class="label">Evaluator Score：</span>${escapeHtml(String(latestEvaluator?.score ?? "-"))}</div>
            <div class="info-row"><span class="label">Evaluator 来源：</span>${escapeHtml(latestEvaluator?.source || "-")}</div>
            <div class="info-row"><span class="label">Validation：</span>${escapeHtml(summary.validation_passed === true ? "passed" : summary.validation_passed === false ? "failed" : "-")}</div>
            <div class="info-row"><span class="label">Validation 摘要：</span>${escapeHtml(summary.validation_summary || latestValidation.summary || "-")}</div>
            <div class="info-row"><span class="label">Recovery：</span>${escapeHtml(summary.recovery_action_key || latestRecoveryAction.action || "-")}</div>
            <div class="info-row"><span class="label">Recovery 摘要：</span>${escapeHtml(summary.recovery_summary || latestRecoveryAction.summary || "-")}</div>
            <div class="info-row"><span class="label">Workflow Proposal：</span>${escapeHtml(workflowProposalLabel)}</div>
            ${renderWorkflowProposalTemplateActions(latestWorkflowProposal)}
            <div class="info-row"><span class="label">Evaluator 建议：</span>${escapeHtml(latestEvaluator?.recommendation || "-")}</div>
            <div class="info-row"><span class="label">可执行动作：</span>${escapeHtml([
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
        <div class="info-row"><span class="label">角色分布：</span>${escapeHtml(roleSummary || "暂无")}</div>
        ${agentRuns.map(item => `
          <div class="step-card">
            <div class="step-title">Agent #${item.id} / ${escapeHtml(item.role || "")} / ${escapeHtml(item.status || "")}</div>
            <div class="info-row"><span class="label">attempt：</span>${escapeHtml(String(item.attempt || 1))}</div>
            <div class="info-row"><span class="label">父 Agent：</span>${escapeHtml(item.parent_agent_run_id ?? "-")}</div>
            <div class="info-row"><span class="label">brief artifact：</span>${escapeHtml(item.brief_artifact_id ?? "-")}</div>
            <div class="info-row"><span class="label">output artifact：</span>${escapeHtml(item.output_artifact_id ?? "-")}</div>
            <div class="info-row"><span class="label">review artifact：</span>${escapeHtml(item.review_artifact_id ?? "-")}</div>
            <div class="info-row"><span class="label">model：</span>${escapeHtml(item.assigned_model || "-")}</div>
            <div class="info-row"><span class="label">tool profile：</span>${escapeHtml(item.assigned_tool_profile || "-")}</div>
            <div class="info-row"><span class="label">错误：</span>${escapeHtml(item.error_summary || "无")}</div>
            <div class="info-row"><span class="label">更新时间：</span>${escapeHtml(item.updated_at || "-")}</div>
            ${renderAgentExecutionSnapshot(agentDetails[item.id] || {})}
            <details style="margin-top: 10px;">
              <summary>消息与工件明细</summary>
              <div class="info-row"><span class="label">Messages：</span>${escapeHtml(String((agentDetails[item.id]?.messages || []).length))}</div>
              <div class="info-row"><span class="label">Artifacts：</span>${escapeHtml(String((agentDetails[item.id]?.artifacts || []).length))}</div>
              <div class="info-row"><span class="label">Messages：</span><pre>${escapeHtml(((agentDetails[item.id]?.messages || []).map(msg => `${msg.message_type} ${msg.sender_role}->${msg.recipient_role} ${JSON.stringify(msg.payload || {})}`).join("\n\n")) || "暂无")}</pre></div>
              <div class="info-row"><span class="label">Artifacts：</span><pre>${escapeHtml(((agentDetails[item.id]?.artifacts || []).map(art => `${art.artifact_type}#${art.id} ${art.summary || ""}\n${JSON.stringify(art.content || {}, null, 2)}`).join("\n\n")) || "暂无")}</pre></div>
            </details>
          </div>
        `).join("")}
      `;
    }

    function renderStage5TaskChips(summary) {
      if (!summary) {
        return "";
      }
      const chips = [];
      const latestEvaluator = summary.latest_evaluator || {};
      const latestWorkflowProposal = summary.latest_workflow_proposal || {};
      if (summary.recommended_action) {
        chips.push(`<span class="stage5-chip">Stage 5: ${escapeHtml(summary.recommended_action)}</span>`);
      }
      if (summary.latest_reviewer_decision) {
        const decisionClass = summary.latest_reviewer_decision === "rejected"
          ? "stage5-chip-danger"
          : summary.latest_reviewer_decision === "rework_required"
            ? "stage5-chip-warn"
            : "stage5-chip";
        chips.push(`<span class="stage5-chip ${decisionClass}">review: ${escapeHtml(summary.latest_reviewer_decision)}</span>`);
      }
      if (summary.latest_decision_source) {
        chips.push(`<span class="stage5-chip stage5-chip-muted">${escapeHtml(summary.latest_decision_source)}</span>`);
      }
      if (summary.validation_passed === true) {
        chips.push(`<span class="stage5-chip">validation: passed</span>`);
      } else if (summary.validation_passed === false) {
        chips.push(`<span class="stage5-chip stage5-chip-warn">validation: failed</span>`);
      }
      if (summary.recovery_action_key && summary.recovery_action_key !== "none") {
        chips.push(`<span class="stage5-chip stage5-chip-warn">recovery: ${escapeHtml(summary.recovery_action_key)}</span>`);
      }
      if (summary.execution_backend) {
        chips.push(`<span class="stage5-chip stage5-chip-muted">backend: ${escapeHtml(summary.execution_backend)}</span>`);
      }
      if (summary.implementation_status) {
        chips.push(`<span class="stage5-chip stage5-chip-muted">impl: ${escapeHtml(summary.implementation_status)}</span>`);
      }
      if (latestEvaluator.source) {
        chips.push(`<span class="stage5-chip stage5-chip-muted">evaluator: ${escapeHtml(latestEvaluator.source)}</span>`);
      }
      if (latestWorkflowProposal.action_key || latestWorkflowProposal.priority) {
        chips.push(`<span class="stage5-chip stage5-chip-muted">proposal: ${escapeHtml(formatWorkflowProposalLabel(latestWorkflowProposal))}</span>`);
      }
      if (summary.latest_final_artifact?.version) {
        chips.push(`<span class="stage5-chip stage5-chip-muted">final v${escapeHtml(String(summary.latest_final_artifact.version))}</span>`);
      }
      if (summary.latest_final_artifact?.quality_score !== undefined && summary.latest_final_artifact?.quality_score !== null) {
        chips.push(`<span class="stage5-chip stage5-chip-muted">score ${escapeHtml(String(summary.latest_final_artifact.quality_score))}</span>`);
      }
      return chips.length ? `<div class="task-stage5-row">${chips.join("")}</div>` : "";
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
      selectedTaskId = taskId;
      if (options.focusWorkspace) {
        setAppTab("workspace");
        setWorkspaceTab(options.workspaceTab || "overview");
      }
      await loadTasks();

      try {
        const [task, steps, approvals, agentRuns, agentSummary, tracePayload, replayPayload] = await Promise.all([
          fetchJson(`${API_BASE}/tasks/${taskId}`),
          fetchJson(`${API_BASE}/tasks/${taskId}/steps`),
          fetchJson(`${API_BASE}/tasks/${taskId}/approvals`),
          fetchJson(`${API_BASE}/tasks/${taskId}/agent-runs`),
          fetchJson(`${API_BASE}/tasks/${taskId}/agent-runs/summary`),
          fetchJson(`${API_BASE}/tasks/${taskId}/traces`),
          fetchJson(`${API_BASE}/tasks/${taskId}/replay`),
        ]);
        currentTaskSnapshot = task;
        window.currentTaskAgentSummary = agentSummary;
        taskAgentSummaries.set(taskId, agentSummary);
        if (monitorOverview) {
          renderMonitorOverview();
        }
        const agentDetailsEntries = await Promise.all(
          agentRuns.map(async (agentRun) => {
            const [messages, artifacts] = await Promise.all([
              fetchJson(`${API_BASE}/agent-runs/${agentRun.id}/messages?limit=20`),
              fetchJson(`${API_BASE}/agent-runs/${agentRun.id}/artifacts?limit=20`),
            ]);
            return [agentRun.id, { messages, artifacts }];
          })
        );
        const agentDetails = Object.fromEntries(agentDetailsEntries);
        const sessionSummary = task.session_id
          ? await fetchJson(`${API_BASE}/sessions/${task.session_id}/summary`)
          : null;
        const sessionReviews = task.session_id
          ? await fetchJson(`${API_BASE}/sessions/${task.session_id}/reviews?limit=5`)
          : [];
        const sessionState = sessionSummary?.session_state || null;
        const sessionHealth = sessionSummary?.health || null;

        document.getElementById("workspaceHero").innerHTML = `
          <div class="workspace-hero-card">
            <div class="workspace-hero-label">当前任务</div>
            <div class="workspace-hero-value">#${task.id}</div>
          </div>
          <div class="workspace-hero-card">
            <div class="workspace-hero-label">状态</div>
            <div class="workspace-hero-value">${escapeHtml(task.status || "-")}</div>
          </div>
          <div class="workspace-hero-card">
            <div class="workspace-hero-label">下一步</div>
            <div class="workspace-hero-value">${escapeHtml(describeNextAction(task, task.validation_report || {}, task.recovery_action || {}))}</div>
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
        const taskStageExplanation = describeTaskStage(task, validationReport, recoveryAction);
        const taskNextAction = describeNextAction(task, validationReport, recoveryAction);
        const validationChecks = Array.isArray(validationReport.checks) ? validationReport.checks : [];
        const failedChecks = validationChecks.filter(item => item && item.passed === false);
        const clarifyQuestions = (((deliverableSpec || {}).clarify || {}).questions) || [];

        document.getElementById("taskDetail").innerHTML = `
          <div class="top-actions">
            <button class="ghost-btn" onclick="setAppTab('tasks')">回到任务列表</button>
            ${task.session_id ? `<button class="ghost-btn" onclick="openSessionBrowser(${task.session_id})">打开 Session</button>` : ""}
            ${
              recoveryAction && recoveryAction.action && recoveryAction.action !== "none"
                ? (
                    recoveryAction.action === "clarify"
                      ? `<button class="secondary-btn" onclick="clarifyTask(${task.id})">补充 Clarification</button>`
                      : `<button onclick="applyRecoveryAction(${task.id})">应用 Recovery Action</button>`
                  )
                : ""
            }
          </div>
          <div class="task-summary-grid">
            <div class="task-summary-card">
              <div class="task-summary-label">当前说明</div>
              <div class="task-summary-value">${escapeHtml(taskStageExplanation)}</div>
            </div>
            <div class="task-summary-card">
              <div class="task-summary-label">下一步动作</div>
              <div class="task-summary-value">${escapeHtml(taskNextAction)}</div>
            </div>
            <div class="task-summary-card">
              <div class="task-summary-label">验收状态</div>
              <div class="task-summary-value">${validationReport.passed === true ? "已通过" : validationReport.passed === false ? "未通过" : "待校验"}</div>
            </div>
            <div class="task-summary-card">
              <div class="task-summary-label">恢复动作</div>
              <div class="task-summary-value">${escapeHtml(recoveryAction.action || "none")}</div>
            </div>
          </div>
          <div class="task-summary-grid">
            <div class="task-summary-card">
              <div class="task-summary-label">任务 ID</div>
              <div class="task-summary-value">#${task.id}</div>
            </div>
            <div class="task-summary-card">
              <div class="task-summary-label">当前状态</div>
              <div class="task-summary-value"><span class="status-badge ${statusClass(task.status)}">${task.status}</span></div>
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
              <div class="task-summary-value">${validationReport.passed === true ? "已通过" : validationReport.passed === false ? "未通过" : "待校验"}</div>
            </div>
            <div class="task-summary-card">
              <div class="task-summary-label">恢复动作</div>
              <div class="task-summary-value">${escapeHtml(recoveryAction.action || "none")}</div>
            </div>
          </div>
          <div class="info-row"><span class="label">任务内容：</span>${escapeHtml(task.display_user_input || task.user_input)}</div>
          ${task.clarification_count ? `<div class="info-row"><span class="label">原始任务：</span>${escapeHtml(task.original_user_input || task.user_input || "")}</div>` : ""}
          <div class="info-row">
            <span class="label">最终交付：</span>
            <pre data-testid="task-final-deliverable">${escapeHtml(task.result || "尚未形成最终交付；如果任务仍在运行，可先查看步骤与 traces。")}</pre>
          </div>
          <div class="info-row"><span class="label">验收摘要：</span>${escapeHtml(validationReport.summary || "暂无校验摘要")}</div>
          <div class="info-row"><span class="label">恢复建议：</span>${escapeHtml(recoveryAction.summary || "当前没有恢复动作")}</div>
          <div class="info-row"><span class="label">失败检查：</span><pre>${escapeHtml(
            failedChecks.length
              ? failedChecks.map(item => `${item.name}: expected=${JSON.stringify(item.expected)} / actual=${JSON.stringify(item.actual)}`).join("\n")
              : "当前没有失败检查"
          )}</pre></div>
          <div class="info-row"><span class="label">Clarify Questions：</span><pre>${escapeHtml((clarifyQuestions || []).join("\n") || "暂无")}</pre></div>
          <details style="margin-top: 12px;">
            <summary>高级视图：Task Intent / Deliverable / Validation / Runtime</summary>
            <div class="info-row"><span class="label">Task Intent：</span><pre>${escapeHtml(JSON.stringify(taskIntent, null, 2))}</pre></div>
            <div class="info-row"><span class="label">Deliverable Spec：</span><pre>${escapeHtml(JSON.stringify(deliverableSpec, null, 2))}</pre></div>
            <div class="info-row"><span class="label">Validation Report：</span><pre>${escapeHtml(JSON.stringify(validationReport, null, 2))}</pre></div>
            <div class="info-row"><span class="label">Recovery Action：</span><pre>${escapeHtml(JSON.stringify(recoveryAction, null, 2))}</pre></div>
            <div class="info-row"><span class="label">Skill Invocation：</span><pre>${escapeHtml(JSON.stringify((task.runtime_overrides || {}).skill_invocation || { mode: "default_planner" }, null, 2))}</pre></div>
            <div class="info-row"><span class="label">长期记忆：</span><pre>${escapeHtml(JSON.stringify(((task.runtime_overrides || {}).memory_context || {}).retrieved_memories || [], null, 2))}</pre></div>
            <div class="info-row"><span class="label">创建时间：</span>${task.created_at || "-"}</div>
            <div class="info-row"><span class="label">错误信息：</span>${task.error_message ? escapeHtml(task.error_message) : "无"}</div>
          </details>
        `;

        document.getElementById("stepsDetail").innerHTML = renderTaskTimeline(steps);

        document.getElementById("traceDetail").innerHTML = renderTraceHighlights(tracePayload, replayPayload);

        const pendingApprovals = approvals.filter(item => item.status === "pending");
        if (!pendingApprovals.length) {
          document.getElementById("approvalDetail").innerHTML = `<div class="empty">暂无待审批项。当前任务没有被高风险步骤阻塞。</div>`;
        } else {
          document.getElementById("approvalDetail").innerHTML = pendingApprovals.map(item => `
            <div class="approval-card">
              <div class="step-title">审批 #${item.id} / 步骤 ${item.step_order}：${escapeHtml(item.step_name)}</div>
              <div class="info-row"><span class="label">工具：</span>${escapeHtml(item.tool_name)}</div>
              <div class="info-row"><span class="label">原因：</span>${escapeHtml(item.reason)}</div>
              <div class="info-row"><span class="label">输入：</span><pre>${escapeHtml(item.input_payload || "无")}</pre></div>
              <div class="top-actions">
                <button onclick="decideApproval(${item.id}, true)">批准</button>
                <button class="secondary-btn" onclick="decideApproval(${item.id}, false)">拒绝</button>
              </div>
            </div>
          `).join("");
        }

        document.getElementById("taskAgentsDetail").innerHTML = renderTaskAgentRuns(taskId, agentRuns, agentDetails);

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
            ${sessionReviews.map(item => `
            <div class="step-card">
              <div class="step-title">Review #${item.id} / ${escapeHtml(item.review_kind || "")}</div>
              <div class="info-row"><span class="label">摘要：</span>${escapeHtml(item.summary_text || "无")}</div>
              <div class="info-row"><span class="label">Open Loops：</span>${escapeHtml(String((item.open_loops || []).length))}</div>
              <div class="info-row"><span class="label">创建时间：</span>${escapeHtml(item.created_at || "-")}</div>
              <div class="info-row"><span class="label">Highlights：</span><pre>${escapeHtml((item.highlights || []).join("\n"))}</pre></div>
            </div>
          `).join("")}
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
              <div class="info-row"><span class="label">摘要：</span>${escapeHtml(sessionState.summary_text || "无")}</div>
              <div class="info-row"><span class="label">偏好数：</span>${escapeHtml(String((sessionState.preferences || []).length))}</div>
              <div class="info-row"><span class="label">Open Loops 数：</span>${escapeHtml(String((sessionState.open_loops || []).length))}</div>
              <div class="info-row"><span class="label">更新时间：</span>${escapeHtml(sessionState.updated_at || "-")}</div>
              <div class="info-row"><span class="label">Preferences：</span><pre>${escapeHtml((sessionState.preferences || []).join("\n") || "暂无")}</pre></div>
              <div class="info-row"><span class="label">Open Loops：</span><pre>${escapeHtml((sessionState.open_loops || []).join("\n") || "暂无")}</pre></div>
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
              <div class="info-row"><span class="label">活跃任务：</span>${escapeHtml(String(sessionHealth.active_task_count || 0))}</div>
              <div class="info-row"><span class="label">高重要记忆：</span>${escapeHtml(String(sessionHealth.high_importance_memory_count || 0))}</div>
              <div class="info-row"><span class="label">重复记忆：</span>${escapeHtml(String(sessionHealth.duplicate_memory_count || 0))}</div>
              <div class="info-row"><span class="label">Open Loops：</span>${escapeHtml(String(sessionHealth.open_loop_count || 0))}</div>
              <div class="info-row"><span class="label">Reviews：</span>${escapeHtml(String(sessionHealth.total_reviews || 0))}</div>
              <div class="info-row"><span class="label">State 是否过期：</span>${sessionHealth.state_is_stale ? "是" : "否"}</div>
              <div class="info-row"><span class="label">今日 Daily Review：</span>${sessionHealth.daily_review_today ? "已覆盖" : "未覆盖"}</div>
              ${renderSessionRecommendedActions(task.session_id, recommendedActions)}
            </div>
          `;
        }
      } catch (err) {
        currentTaskSnapshot = null;
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
        document.getElementById("taskDetail").innerHTML = `<div class="empty">${escapeHtml(err.message)}</div>`;
        document.getElementById("stepsDetail").innerHTML = `<div class="empty">读取步骤失败</div>`;
        document.getElementById("traceDetail").innerHTML = `<div class="empty">读取 traces 失败</div>`;
        document.getElementById("approvalDetail").innerHTML = `<div class="empty">读取审批失败</div>`;
        document.getElementById("taskAgentsDetail").innerHTML = `<div class="empty">读取 agent runs 失败</div>`;
        document.getElementById("sessionReviewDetail").innerHTML = `<div class="empty">读取 session reviews 失败</div>`;
        document.getElementById("sessionStateDetail").innerHTML = `<div class="empty">读取 session state 失败</div>`;
        document.getElementById("sessionHealthDetail").innerHTML = `<div class="empty">读取 session health 失败</div>`;
      }
    }

    async function applyRecoveryAction(taskId) {
      const note = window.prompt("请输入恢复备注（可留空）", "") ?? "";
      try {
        await fetchJson(`${API_BASE}/tasks/${taskId}/apply-recovery-action`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json"
          },
          body: JSON.stringify({ note })
        });
        await selectTask(taskId, { focusWorkspace: true, workspaceTab: "overview" });
        await loadTasks();
        await loadMonitorOverview();
        showToast(`任务 #${taskId} 已触发恢复动作`, "success");
      } catch (err) {
        showToast("恢复动作执行失败", "error");
        alert(err.message);
      }
    }

    async function clarifyTask(taskId) {
      const clarification = window.prompt("请输入补充说明（必填）", "") ?? "";
      if (!clarification.trim()) {
        alert("补充说明不能为空");
        return;
      }
      const note = window.prompt("请输入 clarification 备注（可留空）", "") ?? "";
      try {
        await fetchJson(`${API_BASE}/tasks/${taskId}/clarify`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json"
          },
          body: JSON.stringify({ clarification, note })
        });
        await selectTask(taskId, { focusWorkspace: true, workspaceTab: "overview" });
        await loadTasks();
        await loadMonitorOverview();
        showToast(`任务 #${taskId} 已提交 Clarification`, "success");
      } catch (err) {
        showToast("Clarification 提交失败", "error");
        alert(err.message);
      }
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
      const container = document.getElementById("taskDraftDetail");
      if (!container) {
        return;
      }
      currentTaskDraft = draft || null;
      renderFastPathAnswer(null);
      if (!draft) {
        container.innerHTML = `<div class="empty">输入后先在这里看系统理解，再决定是否创建正式任务。</div>`;
        return;
      }

      const preview = draft.draft_preview || {};
      const memoryContext = draft.memory_context || {};
      const retrievedMemories = Array.isArray(memoryContext.retrieved_memories) ? memoryContext.retrieved_memories : [];
      const canOperate = actorHasPermission(currentActorName, "operate");
      const confirmLabel = draft.route_mode === "fast_path"
        ? "按快速路径创建任务"
        : draft.route_mode === "clarify_first"
          ? "创建任务并进入 Clarify"
          : "确认创建正式任务";

      container.innerHTML = `
        <div class="step-card" data-testid="task-draft-card">
          <div class="step-title" data-testid="task-draft-route">${escapeHtml(getRouteModeLabel(draft.route_mode || "draft_task"))}</div>
          <div class="task-summary-grid">
            <div class="task-summary-card">
              <div class="task-summary-label">route_reason</div>
              <div class="task-summary-value">${escapeHtml(draft.route_reason || "无")}</div>
            </div>
            <div class="task-summary-card">
              <div class="task-summary-label">goal_summary</div>
              <div class="task-summary-value">${escapeHtml(preview.goal_summary || "-")}</div>
            </div>
            <div class="task-summary-card">
              <div class="task-summary-label">task_type</div>
              <div class="task-summary-value">${escapeHtml(preview.task_type || "-")}</div>
            </div>
            <div class="task-summary-card">
              <div class="task-summary-label">deliverable_type</div>
              <div class="task-summary-value">${escapeHtml(preview.deliverable_type || "-")}</div>
            </div>
          </div>
          <div class="info-row"><span class="label">needs_clarification：</span>${preview.needs_clarification ? "是" : "否"}</div>
          <div class="info-row"><span class="label">acceptance_hints：</span><pre>${escapeHtml((preview.acceptance_hints || []).join("\n") || "暂无")}</pre></div>
          <div class="info-row"><span class="label">clarify_questions：</span><pre>${escapeHtml((preview.clarification_questions || []).join("\n") || "暂无")}</pre></div>
          <div class="info-row"><span class="label">Task Intent：</span><pre>${escapeHtml(JSON.stringify(draft.task_intent || {}, null, 2))}</pre></div>
          <div class="info-row"><span class="label">Deliverable Spec：</span><pre>${escapeHtml(JSON.stringify(draft.deliverable_spec || {}, null, 2))}</pre></div>
          <div class="info-row"><span class="label">长期记忆召回：</span><pre>${escapeHtml(
            retrievedMemories.length
              ? retrievedMemories.map((item, index) => `${index + 1}. [${item.memory_kind || "memory"}] ${item.title || ""}\n${item.content || ""}`).join("\n\n")
              : "暂无可复用长期记忆"
          )}</pre></div>
          <div class="top-actions">
            ${draft.route_mode === "fast_path" ? `<button class="ghost-btn" data-testid="fast-path-answer-button" onclick="runFastPathAnswer()">先直接回答</button>` : ""}
            <button data-testid="task-confirm-button" onclick="confirmTaskDraft()" ${canOperate ? "" : "disabled"}>${escapeHtml(confirmLabel)}</button>
            <button class="ghost-btn" onclick="renderTaskDraft(null)">清空草稿</button>
          </div>
        </div>
      `;
    }

    function renderFastPathAnswer(response = null) {
      const container = document.getElementById("fastPathAnswerDetail");
      currentFastPathAnswer = response || null;
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
          <div class="info-row"><span class="label">回答：</span><pre>${escapeHtml(response.answer || "")}</pre></div>
          <div class="info-row"><span class="label">召回记忆：</span><pre>${escapeHtml(
            retrievedMemories.length
              ? retrievedMemories.map((item, index) => `${index + 1}. ${item.title || ""}\n${(item.metadata || {}).match_explanation || ""}`).join("\n\n")
              : "暂无"
          )}</pre></div>
          <div class="info-row"><span class="label">升级建议：</span>${escapeHtml(((response.promote_to_task || {}).reason) || "需要正式留痕时再升级为任务")}</div>
        </div>
      `;
    }

    async function runFastPathAnswer() {
      try {
        if (!currentTaskDraft) {
          throw new Error("请先分析输入并生成草稿");
        }
        const requestPayload = currentTaskDraft._request_payload || {};
        const payload = {
          user_input: requestPayload.contextual_user_input || requestPayload.raw_user_input || "",
          session_id: requestPayload.session_id || undefined,
          skill_id: requestPayload.skill_id || undefined,
          skill_version: requestPayload.skill_version || undefined,
          skill_args: requestPayload.skill_args || undefined,
        };
        const response = await fetchJson(`${API_BASE}/chat/fast-path`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json"
          },
          body: JSON.stringify(payload)
        });
        updateCurrentTaskDialogue((thread) => ({
          ...thread,
          latestFastPath: response,
          turns: [
            ...safeArray(thread.turns),
            {
              id: `turn_${Date.now()}_fastpath`,
              role: "assistant",
              type: "fast_path",
              createdAt: new Date().toISOString(),
              response,
            }
          ],
        }));
        renderFastPathAnswer(response);
        renderCurrentTaskDialogue();
        setTaskSubmitMessage("已生成 fast_path 轻量回答；如需留痕与回放，再创建正式任务。");
        showToast("已生成 Fast Path 回答", "success");
      } catch (err) {
        renderFastPathAnswer(null);
        setTaskSubmitMessage(`fast_path 回答失败：${err.message}`, true);
        showToast("Fast Path 回答失败", "error");
      }
    }

    function renderMemorySearchResults(query, rows = []) {
      const container = document.getElementById("memorySearchResult");
      if (!container) {
        return;
      }
      lastMemorySearchQuery = query || "";
      if (!rows.length) {
        container.innerHTML = query
          ? `<div class="empty">未找到与“${escapeHtml(query)}”相关的长期记忆。</div>`
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
            <div class="step-title">${index + 1}. ${escapeHtml(item.title || "未命名记忆")}</div>
            <div class="info-row"><span class="label">类型：</span>${escapeHtml(item.memory_kind || "memory")}</div>
            <div class="info-row"><span class="label">命中原因：</span>${escapeHtml(explanation || "关键词与内容相关")}</div>
            <div class="info-row"><span class="label">匹配关键词：</span>${escapeHtml(matchedKeywords.join(", ") || "未返回")}</div>
            <div class="info-row"><span class="label">引用建议：</span>${escapeHtml(citationHint)}</div>
            <div class="info-row"><span class="label">内容：</span><pre>${escapeHtml(item.content || "")}</pre></div>
          </div>
        `;
      }).join("");
    }

    async function searchLongTermMemories(options = {}) {
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
        renderMemorySearchResults("", []);
        setMemorySearchMessage("请输入检索词，或先选择一个任务后再用当前任务搜索。", true);
        return;
      }

      try {
        setMemorySearchMessage(`正在检索“${query}”相关的长期记忆…`);
        const params = new URLSearchParams({ query, limit: "5" });
        const rows = await fetchJson(`${API_BASE}/memories/search?${params.toString()}`);
        renderMemorySearchResults(query, Array.isArray(rows) ? rows : []);
        setMemorySearchMessage(`已完成长期记忆检索：${query}`);
      } catch (err) {
        renderMemorySearchResults(query, []);
        setMemorySearchMessage(`长期记忆检索失败：${err.message}`, true);
      }
    }

    function parseTaskDraftPayload(options = {}) {
      const input = document.getElementById("taskInput");
      const taskSkillSelect = document.getElementById("taskSkillSelect");
      const taskSkillVersion = document.getElementById("taskSkillVersion");
      const taskSkillArgs = document.getElementById("taskSkillArgs");
      const rawUserInput = String(options.rawUserInput || input.value || "").trim();
      if (!rawUserInput) {
        throw new Error("请输入任务内容");
      }

      const thread = options.thread || getCurrentTaskDialogue();
      const payload = { user_input: buildDialogueContextInput(rawUserInput, thread) };
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

    async function analyzeTaskInput() {
      try {
        if (!getCurrentTaskDialogue()) {
          await startNewTaskDialogue();
        }
        let thread = getCurrentTaskDialogue();
        thread = await ensureTaskDialogueSession(thread);
        const payload = parseTaskDraftPayload({ thread });
        addTaskDialogueTurn({
          role: "user",
          type: "input",
          text: payload._raw_user_input,
        });
        const draft = await fetchJson(`${API_BASE}/intake/route`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json"
          },
          body: JSON.stringify({
            ...payload,
            user_input: payload.user_input,
          })
        });
        draft._request_payload = {
          raw_user_input: payload._raw_user_input,
          contextual_user_input: payload.user_input,
          session_id: thread?.sessionId || null,
          skill_id: payload.skill_id || "",
          skill_version: payload.skill_version || "",
          skill_args: payload.skill_args || {},
        };
        updateCurrentTaskDialogue((currentThread) => ({
          ...currentThread,
          title: currentThread.title === "新任务对话" ? String(payload._raw_user_input || "").slice(0, 40) : currentThread.title,
          latestDraft: draft,
          turns: [
            ...safeArray(currentThread.turns),
            {
              id: `turn_${Date.now()}_draft`,
              role: "assistant",
              type: "draft",
              createdAt: new Date().toISOString(),
              draft,
              rawUserInput: payload._raw_user_input,
              contextualUserInput: payload.user_input,
            }
          ],
        }));
        renderTaskDraft(draft);
        renderCurrentTaskDialogue();
        const memoryInput = document.getElementById("memorySearchInput");
        if (memoryInput && !memoryInput.value.trim()) {
          memoryInput.value = payload._raw_user_input;
        }
        setTaskSubmitMessage(`已生成 ${getRouteModeLabel(draft.route_mode || "draft_task")} 草稿，请确认后再创建任务。`);
        showToast("系统理解卡片已生成", "success");
      } catch (err) {
        setTaskSubmitMessage(`输入分流失败：${err.message}`, true);
        showToast("输入分流失败", "error");
        alert(err.message);
      }
    }

    async function confirmTaskDraft() {
      if (!currentTaskDraft) {
        alert("请先分析输入并生成草稿");
        return;
      }
      if (!actorHasPermission(currentActorName, "operate")) {
        const hint = getActorOperateHint(currentActorName);
        setTaskSubmitMessage(hint.text, true);
        alert(`当前 actor 无法创建任务。\n${hint.text}`);
        return;
      }

      try {
        let thread = getCurrentTaskDialogue();
        thread = await ensureTaskDialogueSession(thread);
        const requestPayload = currentTaskDraft._request_payload || {};
        const payload = {
          user_input: requestPayload.raw_user_input || document.getElementById("taskInput").value.trim(),
          session_id: thread?.sessionId || requestPayload.session_id || undefined,
          skill_id: requestPayload.skill_id || undefined,
          skill_version: requestPayload.skill_version || undefined,
          skill_args: requestPayload.skill_args || undefined,
          route: currentTaskDraft.route_mode || "draft_task",
        };
        const task = await fetchJson(`${API_BASE}/intake/confirm`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json"
          },
          body: JSON.stringify(payload)
        });

        document.getElementById("taskInput").value = "";
        renderTaskDraft(null);
        updateCurrentTaskDialogue((currentThread) => ({
          ...currentThread,
          turns: [
            ...safeArray(currentThread.turns),
            {
              id: `turn_${Date.now()}_task`,
              role: "system",
              type: "task_created",
              createdAt: new Date().toISOString(),
              taskId: task.id,
              summary: task.display_user_input || task.user_input || "",
            }
          ],
        }));
        renderCurrentTaskDialogue();
        setTaskSubmitMessage(`已按 ${getRouteModeLabel(payload.route)} 创建任务 #${task.id}`);
        await loadTasks();
        await selectTask(task.id, { focusWorkspace: true });
        showToast(`任务 #${task.id} 已创建`, "success");
      } catch (err) {
        showToast("任务创建失败", "error");
        alert(err.message);
      }
    }

    async function createSessionReview(sessionId) {
      const note = window.prompt("请输入 review 备注（可留空）", "") ?? "";
      try {
        await fetchJson(`${API_BASE}/sessions/${sessionId}/reviews`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json"
          },
          body: JSON.stringify({ review_kind: "manual", note })
        });
        if (selectedTaskId !== null) {
          await selectTask(selectedTaskId);
        }
        await refreshSelectedSessionBrowser(sessionId);
        await loadMonitorOverview();
        showToast(`Session #${sessionId} Review 已创建`, "success");
      } catch (err) {
        showToast("创建 Session Review 失败", "error");
        alert(err.message);
      }
    }

    async function bootstrapTaskAgentRuns(taskId) {
      const objective = window.prompt("请输入 agent bootstrap 的目标（留空则使用当前任务内容）", "") ?? "";
      const specialistRaw = window.prompt("请输入 specialist 数量（1-4）", "2") ?? "2";
      const specialistCount = Math.max(1, Math.min(4, parseInt(specialistRaw, 10) || 2));
      const includeReviewer = window.confirm("是否同时创建 reviewer 占位？\n选择“确定”会创建 reviewer，“取消”则只创建 manager + specialists。");
      const note = window.prompt("请输入 bootstrap 备注（可留空）", "") ?? "";

      try {
        await fetchJson(`${API_BASE}/tasks/${taskId}/agent-runs/bootstrap-demo`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json"
          },
          body: JSON.stringify({
            objective,
            specialist_count: specialistCount,
            include_reviewer: includeReviewer,
            note
          })
        });
        await selectTask(taskId, { focusWorkspace: true, workspaceTab: "agents" });
        await loadMonitorOverview();
      } catch (err) {
        alert(err.message);
      }
    }

    async function executeTaskAgentRuns(taskId) {
      const note = window.prompt("请输入 execute 备注（可留空）", "") ?? "";

      try {
        await fetchJson(`${API_BASE}/tasks/${taskId}/agent-runs/execute-demo`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json"
          },
          body: JSON.stringify({
            note
          })
        });
        await selectTask(taskId, { focusWorkspace: true, workspaceTab: "agents" });
        await loadMonitorOverview();
      } catch (err) {
        alert(err.message);
      }
    }

    async function executeTaskAgentRunsViaWorker(taskId) {
      const note = window.prompt("请输入 worker execute 备注（可留空）", "") ?? "";

      try {
        await fetchJson(`${API_BASE}/tasks/${taskId}/agent-runs/execute-worker-demo`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json"
          },
          body: JSON.stringify({
            note
          })
        });
        await selectTask(taskId, { focusWorkspace: true, workspaceTab: "agents" });
        await loadMonitorOverview();
      } catch (err) {
        alert(err.message);
      }
    }

    async function rerunTaskAgentRuns(taskId) {
      const note = window.prompt("请输入重跑备注（可留空）", "") ?? "";
      const forceRerun = window.confirm("是否强制重跑 Specialists？\n确定=force_rerun，取消=普通执行。");

      try {
        await fetchJson(`${API_BASE}/tasks/${taskId}/agent-runs/execute-demo`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json"
          },
          body: JSON.stringify({
            note,
            force_rerun: forceRerun
          })
        });
        await selectTask(taskId, { focusWorkspace: true, workspaceTab: "agents" });
        await loadMonitorOverview();
      } catch (err) {
        alert(err.message);
      }
    }

    async function finalizeTaskAgentRuns(taskId) {
      const summary = window.prompt("请输入 final artifact 摘要（留空则使用默认汇总）", "") ?? "";
      const note = window.prompt("请输入 finalize 备注（可留空）", "") ?? "";
      const reviewerDecisionRaw = window.prompt("请输入 reviewer 决策：auto / approved / rework_required / rejected（回车默认 auto）", "auto") ?? "auto";
      const reviewerDecision = ["auto", "approved", "rework_required", "rejected"].includes(reviewerDecisionRaw.trim())
        ? reviewerDecisionRaw.trim()
        : "auto";
      const allowRetry = window.confirm("是否允许 rework_required 后继续重跑 Specialists？");

      try {
        await fetchJson(`${API_BASE}/tasks/${taskId}/agent-runs/finalize-demo`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json"
          },
          body: JSON.stringify({
            summary,
            note,
            reviewer_decision: reviewerDecision,
            allow_retry: allowRetry
          })
        });
        await selectTask(taskId, { focusWorkspace: true, workspaceTab: "agents" });
        await loadMonitorOverview();
      } catch (err) {
        alert(err.message);
      }
    }

    async function editSessionState(sessionId) {
      try {
        const currentState = sessionBrowserSnapshot?.sessionId === sessionId
          ? (sessionBrowserSnapshot.summary?.session_state || {})
          : (await fetchJson(`${API_BASE}/sessions/${sessionId}/summary`)).session_state || {};
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

        await fetchJson(`${API_BASE}/sessions/${sessionId}/state`, {
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

        if (selectedTaskId !== null) {
          await selectTask(selectedTaskId);
        }
        await refreshSelectedSessionBrowser(sessionId);
        await loadMonitorOverview();
      } catch (err) {
        alert(err.message);
      }
    }

    async function rebuildSessionState(sessionId) {
      try {
        await fetchJson(`${API_BASE}/sessions/${sessionId}/state/rebuild`, {
          method: "POST"
        });
        if (selectedTaskId !== null) {
          await selectTask(selectedTaskId);
        }
        await refreshSelectedSessionBrowser(sessionId);
        await loadMonitorOverview();
      } catch (err) {
        alert(err.message);
      }
    }

    async function createTask() {
      await analyzeTaskInput();
    }

    async function createChangeRequest() {
      const targetType = document.getElementById("changeTargetType").value;
      const targetKey = document.getElementById("changeTargetKey").value.trim();
      const payloadText = document.getElementById("changePayload").value.trim();
      const rationale = document.getElementById("changeRationale").value.trim();

      if (!targetKey) {
        alert("target_key 不能为空");
        return;
      }

      let proposedPayload = {};
      try {
        proposedPayload = payloadText ? JSON.parse(payloadText) : {};
      } catch (err) {
        alert(`JSON 解析失败: ${err.message}`);
        return;
      }

      try {
        await fetchJson(`${API_BASE}/change-requests`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json"
          },
          body: JSON.stringify({
            target_type: targetType,
            target_key: targetKey,
            proposed_payload: proposedPayload,
            rationale
          })
        });
        document.getElementById("changeTargetKey").value = "";
        document.getElementById("changePayload").value = "";
        document.getElementById("changeRationale").value = "";
        await loadChangeRequests();
        await loadMonitorOverview();
        showToast("变更单已创建", "success");
      } catch (err) {
        setChangeRequestMessage(err.message, true);
        showToast("创建变更单失败", "error");
        alert(err.message);
      }
    }

    async function decideChangeRequest(changeRequestId, approved) {
      const note = window.prompt(approved ? "请输入批准备注（可留空）" : "请输入拒绝原因", "");
      if (note === null) return;

      const path = approved ? "approve" : "reject";
      try {
        await fetchJson(`${API_BASE}/change-requests/${changeRequestId}/${path}`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json"
          },
          body: JSON.stringify({ note })
        });
        await loadChangeRequests();
        await loadMonitorOverview();
        await loadRiskPolicies();
        await loadToolRegistry();
        await loadModelRegistry();
        showToast(`变更单 #${changeRequestId} 已${approved ? "批准" : "拒绝"}`, "success");
      } catch (err) {
        setChangeRequestMessage(err.message, true);
        showToast("变更单审批失败", "error");
        alert(err.message);
      }
    }

    async function applyChangeRequest(changeRequestId) {
      try {
        await fetchJson(`${API_BASE}/change-requests/${changeRequestId}/apply`, {
          method: "POST"
        });
        await loadChangeRequests();
        await loadMonitorOverview();
        await loadRiskPolicies();
        await loadToolRegistry();
        await loadModelRegistry();
        await loadAccessQuotaUsage();
        showToast(`变更单 #${changeRequestId} 已应用`, "success");
      } catch (err) {
        setChangeRequestMessage(err.message, true);
        showToast("变更单应用失败", "error");
        alert(err.message);
      }
    }

    async function runChangeRequestShadowValidation(changeRequestId) {
      try {
        const result = await fetchJson(`${API_BASE}/change-requests/${changeRequestId}/shadow-validate`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json"
          },
          body: JSON.stringify({
            note: `web governance shadow validation for change request #${changeRequestId}`,
            await_completion: true,
            timeout_seconds: 90,
            poll_interval_seconds: 1.0
          })
        });
        const shadowState = await fetchJson(`${API_BASE}/change-requests/${changeRequestId}/shadow-validation?history_limit=6`);
        const latestValidation = (shadowState || {}).latest_validation || {};
        const latestShadowTask = (shadowState || {}).latest_shadow_task || {};
        const validationResult = ((latestValidation || {}).validation || {}).validation_result || "-";
        const validationMode = ((latestValidation || {}).validation || {}).validation_mode || (result || {}).validation_mode || "-";
        const proposalStatus = shadowState.proposal_shadow_validation_status || "-";
        const gateStatus = ((shadowState || {}).change_request || {}).shadow_validation_status || "-";
        setChangeRequestMessage(
          `Shadow Validation 完成：gate=${gateStatus} proposal_status=${proposalStatus} result=${validationResult} mode=${validationMode} shadow_task=#${latestShadowTask.id || "-"}`
        );
        await loadChangeRequests();
        await loadMonitorOverview();
        showToast(`变更单 #${changeRequestId} Shadow Validation 完成`, "success");
      } catch (err) {
        setChangeRequestMessage(err.message, true);
        showToast("Shadow Validation 失败", "error");
        alert(err.message);
      }
    }

    async function showChangeRequestShadowValidation(changeRequestId) {
      try {
        const result = await fetchJson(`${API_BASE}/change-requests/${changeRequestId}/shadow-validation?history_limit=6`);
        const changeRequest = (result || {}).change_request || {};
        const latestValidation = (result || {}).latest_validation || {};
        const latestShadowTask = (result || {}).latest_shadow_task || {};
        const validationResult = ((latestValidation || {}).validation || {}).validation_result || "-";
        const historyCount = Number(result.history_count || 0);
        const requestCount = Number(result.request_count || 0);
        const validationCount = Number(result.validation_count || 0);
        setChangeRequestMessage(
          `CR #${changeRequestId} shadow：gate=${changeRequest.shadow_validation_status || "-"} ready=${String(Boolean(changeRequest.shadow_validation_ready_to_apply))} proposal_status=${result.proposal_shadow_validation_status || "-"} history=${historyCount} request=${requestCount} validation=${validationCount} latest_result=${validationResult} shadow_task=#${latestShadowTask.id || "-"}`
        );
      } catch (err) {
        setChangeRequestMessage(err.message, true);
        alert(err.message);
      }
    }

    async function createRollbackChangeRequest(changeRequestId) {
      try {
        const result = await fetchJson(`${API_BASE}/change-requests/${changeRequestId}/rollback`, {
          method: "POST"
        });
        const rollbackCr = (result || {}).change_request || {};
        if (result && result.created === false) {
          setChangeRequestMessage(`回滚单已存在：#${rollbackCr.id || "-"}`);
        } else {
          setChangeRequestMessage(`回滚单已创建：#${rollbackCr.id || "-"}`);
        }
        await loadChangeRequests();
        await loadMonitorOverview();
        showToast(`变更单 #${changeRequestId} 回滚单已处理`, "success");
      } catch (err) {
        setChangeRequestMessage(err.message, true);
        showToast("创建回滚单失败", "error");
        alert(err.message);
      }
    }

    async function decideApproval(approvalId, approved) {
      const note = window.prompt(approved ? "请输入批准备注（可留空）" : "请输入拒绝原因", "");
      if (note === null) return;

      const path = approved ? "approve" : "reject";
      try {
        await fetchJson(`${API_BASE}/approvals/${approvalId}/${path}`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json"
          },
          body: JSON.stringify({ note })
        });

        if (selectedTaskId !== null) {
          await selectTask(selectedTaskId);
        } else {
          await loadTasks();
        }
        showToast(`审批 #${approvalId} 已${approved ? "批准" : "拒绝"}`, "success");
      } catch (err) {
        showToast("审批操作失败", "error");
        alert(err.message);
      }
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
