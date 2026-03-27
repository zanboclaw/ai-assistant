(function attachDashboardShell(global) {
  function showToast(_ctx, message, variant = "info") {
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

  function restartAutoRefreshLoop(ctx) {
    if (ctx.autoRefreshTimer) {
      window.clearInterval(ctx.autoRefreshTimer);
      ctx.autoRefreshTimer = null;
    }
    if (!ctx.frontendPrefs.autoRefresh) {
      return;
    }
    ctx.autoRefreshTimer = window.setInterval(async () => {
      if (document.hidden) {
        return;
      }
      if (ctx.currentAppTab === "home" || ctx.currentAppTab === "composer" || ctx.currentAppTab === "tasks") {
        await ctx.loadTasks();
        return;
      }
      if (ctx.currentAppTab === "workspace") {
        if (ctx.selectedTaskId !== null) {
          await ctx.selectTask(ctx.selectedTaskId);
        } else {
          await ctx.loadTasks();
        }
        return;
      }
      if (ctx.currentAppTab === "sessions") {
        await ctx.loadSessions();
        return;
      }
      await ctx.reloadGovernanceData();
    }, Math.max(5, Number(ctx.frontendPrefs.refreshIntervalSeconds || 15)) * 1000);
  }

  function setAppTab(ctx, tabName) {
    const validTabs = new Set(["home", "composer", "tasks", "workspace", "sessions", "governance", "monitor", "settings"]);
    const nextTab = validTabs.has(tabName) ? tabName : "home";
    const tabMeta = ctx.appTabMeta[nextTab] || ctx.appTabMeta.home;
    ctx.currentAppTab = nextTab;
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
          <div class="app-tab-context-title">${ctx.escapeHtml(tabMeta.title)}</div>
          <p class="app-tab-context-text">${ctx.escapeHtml(tabMeta.description)}</p>
        </div>
      `;
    }

    if (nextTab === "sessions") {
      void ctx.loadSessions();
    }
    if (nextTab === "home") {
      ctx.renderHomeOverview();
    }
    if (nextTab === "composer") {
      ctx.renderTaskDialogueList();
      ctx.renderCurrentTaskDialogue();
    }
    if (nextTab === "settings") {
      ctx.renderSettingsView();
    }
  }

  function setWorkspaceTab(ctx, tabName) {
    const validTabs = new Set(["overview", "steps", "traces", "approvals", "agents", "session"]);
    const nextTab = validTabs.has(tabName) ? tabName : "overview";
    ctx.currentWorkspaceTab = nextTab;
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

  function getActorRole(ctx, actorName) {
    const matchedActor = ctx.accessActors.find((item) => item.actor_name === actorName);
    if (matchedActor && matchedActor.role) {
      return matchedActor.role;
    }
    return ctx.defaultActorRoleMap[actorName] || "viewer";
  }

  function actorHasPermission(ctx, actorName, permission) {
    const role = getActorRole(ctx, actorName);
    const permissions = ctx.actorRolePermissions[role] || [];
    return permissions.includes(permission);
  }

  function getActorOperateHint(ctx, actorName) {
    const role = getActorRole(ctx, actorName);
    if (actorHasPermission(ctx, actorName, "operate")) {
      return {
        text: `当前 actor: ${actorName}（${role}，可提交任务与执行操作）`,
        isError: false,
      };
    }
    return {
      text: `当前 actor: ${actorName}（${role}，只读；请切换到 local_operator 或 local_admin 后再提交任务）`,
      isError: true,
    };
  }

  function renderAppVisibility(ctx) {
    const role = getActorRole(ctx, ctx.currentActorName);
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

    if ((role === "viewer" && (ctx.currentAppTab === "monitor" || ctx.currentAppTab === "governance")) || (role !== "admin" && ctx.currentAppTab === "governance")) {
      ctx.setAppTab("home");
    }
  }

  function renderActorContext(ctx) {
    const select = document.getElementById("actorSelect");
    if (select) {
      select.value = ctx.currentActorName;
    }
    const hint = getActorOperateHint(ctx, ctx.currentActorName);
    ctx.setActorContextMessage(hint.text, hint.isError);
    ctx.renderTaskSubmissionState();
    const settingsMessage = document.getElementById("settingsConnectionMessage");
    if (settingsMessage) {
      settingsMessage.textContent = `${hint.text}；当前 API Base: ${ctx.API_BASE}`;
      settingsMessage.style.color = hint.isError ? "#b91c1c" : "#0f172a";
    }
  }

  async function changeActorContext(ctx) {
    const select = document.getElementById("actorSelect");
    ctx.currentActorName = select ? select.value : ctx.currentActorName;
    window.localStorage.setItem("ai-assistant-actor", ctx.currentActorName);
    renderActorContext(ctx);
    await ctx.reloadGovernanceData();
    await ctx.loadTasks();
    if (ctx.selectedTaskId !== null) {
      await ctx.selectTask(ctx.selectedTaskId);
    }
    ctx.setAppTab("settings");
    showToast(ctx, `已切换为 ${ctx.currentActorName}`, "success");
  }

  global.DashboardShell = {
    actorHasPermission,
    changeActorContext,
    getActorOperateHint,
    getActorRole,
    renderActorContext,
    renderAppVisibility,
    restartAutoRefreshLoop,
    setAppTab,
    setWorkspaceTab,
    showToast,
  };
})(window);
