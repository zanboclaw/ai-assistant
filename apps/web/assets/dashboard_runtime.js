(function attachDashboardRuntime(global) {
  const DEFAULT_API_BASE = `${window.location.protocol}//${window.location.hostname}:8000`;
  const FRONTEND_PREFS_STORAGE_KEY = "ai-assistant-frontend-prefs";
  const TASK_DIALOGUE_STORAGE_KEY = "ai-assistant-task-dialogues";
  const DEFAULT_FRONTEND_PREFS = {
    autoRefresh: true,
    refreshIntervalSeconds: 15,
    compactTaskCards: false,
    showAdvancedComposer: false,
  };

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

    const apiBaseCandidates = resolveApiBaseCandidates();
    const matchedBase = apiBaseCandidates.find((base) => raw === base || raw.startsWith(`${base}/`) || raw.startsWith(`${base}?`));
    if (!matchedBase) {
      return [raw];
    }

    const suffix = raw.slice(matchedBase.length);
    const candidates = [];
    apiBaseCandidates.forEach((base) => {
      const candidate = `${base}${suffix}`;
      if (!candidates.includes(candidate)) {
        candidates.push(candidate);
      }
    });
    return candidates;
  }

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

  function persistFrontendPrefs(frontendPrefs) {
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

  function persistTaskDialogues(taskDialogues, currentTaskDialogueId) {
    window.localStorage.setItem(TASK_DIALOGUE_STORAGE_KEY, JSON.stringify(taskDialogues));
    if (currentTaskDialogueId) {
      window.localStorage.setItem("ai-assistant-current-task-dialogue", currentTaskDialogueId);
    } else {
      window.localStorage.removeItem("ai-assistant-current-task-dialogue");
    }
  }

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

  const apiBaseCandidates = resolveApiBaseCandidates();

  global.DashboardRuntime = {
    API_BASE_CANDIDATES: apiBaseCandidates,
    API_BASE: apiBaseCandidates[0],
    DEFAULT_FRONTEND_PREFS,
    appTabMeta,
    buildApiRequestCandidates,
    loadFrontendPrefs,
    loadTaskDialogues,
    normalizeApiBase,
    persistFrontendPrefs,
    persistTaskDialogues,
    resolveApiBaseCandidates,
  };
})(window);
