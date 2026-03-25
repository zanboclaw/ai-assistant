(function () {
  function renderSettingsView(ctx) {
    const runtimeSummary = document.getElementById("settingsRuntimeSummary");
    if (runtimeSummary) {
      const runtimeMetadata = ctx.monitorOverview?.runtime_metadata || {};
      runtimeSummary.innerHTML = `
        <div class="settings-kv"><span class="label">当前 API Base：</span>${ctx.escapeHtml(ctx.API_BASE)}</div>
        <div class="settings-kv"><span class="label">候选地址：</span>${ctx.escapeHtml(ctx.API_BASE_CANDIDATES.join(" / "))}</div>
        <div class="settings-kv"><span class="label">当前 Actor：</span>${ctx.escapeHtml(ctx.currentActorName)} / ${ctx.escapeHtml(ctx.getActorRole(ctx.currentActorName))}</div>
        <div class="settings-kv"><span class="label">可用权限：</span>${ctx.escapeHtml((ctx.actorRolePermissions[ctx.getActorRole(ctx.currentActorName)] || []).join(", ") || "无")}</div>
        <div class="settings-kv"><span class="label">自动刷新：</span>${ctx.frontendPrefs.autoRefresh ? `开启 / ${ctx.frontendPrefs.refreshIntervalSeconds}s` : "关闭"}</div>
        <div class="settings-kv"><span class="label">运行版本：</span><pre>${ctx.escapeHtml(ctx.buildRuntimeVersionSummary(runtimeMetadata) || "等待 monitor/overview 返回运行版本指纹")}</pre></div>
      `;
    }

    const modelSummary = document.getElementById("settingsModelSummary");
    if (modelSummary) {
      const providerRows = ctx.modelProviders.slice(0, 6).map((item) => `${item.provider_name || item.name || "-"} => ${item.base_url || item.driver || "-"}`);
      const routeRows = ctx.modelRoutes.slice(0, 8).map((item) => `${item.route_name || "-"} => ${(item.provider || "-")}/${(item.model_name || "-")}`);
      modelSummary.innerHTML = `
        <div class="settings-kv"><span class="label">Providers：</span><pre>${ctx.escapeHtml(providerRows.join("\n") || "暂无 provider 数据")}</pre></div>
        <div class="settings-kv"><span class="label">Routes：</span><pre>${ctx.escapeHtml(routeRows.join("\n") || "暂无 route 数据")}</pre></div>
      `;
    }

    const autoRefreshEl = document.getElementById("settingsAutoRefresh");
    const refreshSecondsEl = document.getElementById("settingsRefreshSeconds");
    const compactEl = document.getElementById("settingsCompactCards");
    const advancedEl = document.getElementById("settingsAdvancedComposer");
    if (autoRefreshEl) autoRefreshEl.checked = Boolean(ctx.frontendPrefs.autoRefresh);
    if (refreshSecondsEl) refreshSecondsEl.value = String(ctx.frontendPrefs.refreshIntervalSeconds || 15);
    if (compactEl) compactEl.checked = Boolean(ctx.frontendPrefs.compactTaskCards);
    if (advancedEl) advancedEl.checked = Boolean(ctx.frontendPrefs.showAdvancedComposer);
    const composerAdvanced = document.getElementById("taskComposerAdvanced");
    if (composerAdvanced) {
      composerAdvanced.open = Boolean(ctx.frontendPrefs.showAdvancedComposer);
    }
    document.body.classList.toggle("compact-task-cards", Boolean(ctx.frontendPrefs.compactTaskCards));
  }

  function updateFrontendPreference(ctx, key, value) {
    ctx.frontendPrefs[key] = value;
    ctx.persistFrontendPrefs();
    renderSettingsView(ctx);
    ctx.restartAutoRefreshLoop();
    ctx.setTaskSkillMessage("任务起草器配置已更新。");
    const settingsMessage = document.getElementById("settingsPreferenceMessage");
    if (settingsMessage) {
      settingsMessage.textContent = "偏好已保存并立即生效。";
    }
    ctx.showToast("界面偏好已更新", "success");
  }

  function updateRefreshInterval(ctx) {
    const input = document.getElementById("settingsRefreshSeconds");
    const value = Math.max(5, Math.min(120, parseInt(input?.value || "", 10) || 15));
    ctx.frontendPrefs.refreshIntervalSeconds = value;
    ctx.persistFrontendPrefs();
    renderSettingsView(ctx);
    ctx.restartAutoRefreshLoop();
    ctx.showToast(`自动刷新间隔已调整为 ${value} 秒`, "success");
  }

  async function testApiConnection(ctx) {
    const messageEl = document.getElementById("settingsConnectionMessage");
    if (messageEl) {
      messageEl.textContent = "正在测试 API 连通性…";
    }
    try {
      await ctx.fetchJson(`${ctx.API_BASE}/monitor/overview`);
      if (messageEl) {
        messageEl.textContent = `连接正常：${ctx.API_BASE}`;
        messageEl.style.color = "#0f5132";
      }
      ctx.renderGlobalStatusBar();
      ctx.showToast("API 连接测试通过", "success");
    } catch (err) {
      if (messageEl) {
        messageEl.textContent = `连接失败：${err.message}`;
        messageEl.style.color = "#b91c1c";
      }
      ctx.showToast("API 连接失败", "error");
    }
  }

  window.DashboardSettings = {
    renderSettingsView,
    updateFrontendPreference,
    updateRefreshInterval,
    testApiConnection,
  };
})();
