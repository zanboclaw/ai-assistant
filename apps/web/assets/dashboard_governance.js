(function () {
  function previewJson(value, maxLines) {
    const text = JSON.stringify(value || {}, null, 2);
    const lines = text.split("\n");
    if (lines.length <= maxLines) {
      return text;
    }
    return `${lines.slice(0, maxLines).join("\n")}\n... (${lines.length - maxLines} more lines)`;
  }

  function renderChangeRequests(ctx) {
    const container = document.getElementById("changeRequestList");
    if (!ctx.changeRequests.length) {
      container.innerHTML = `<div class="empty">暂无变更单</div>`;
      return;
    }

    const latestRollbackBySource = new Map();
    ctx.changeRequests.forEach((item) => {
      if (item.proposal_kind === "rollback" && item.source_change_request_id) {
        const sourceId = Number(item.source_change_request_id);
        const current = latestRollbackBySource.get(sourceId);
        if (!current || Number(item.id || 0) > Number(current.id || 0)) {
          latestRollbackBySource.set(sourceId, item);
        }
      }
    });

    container.innerHTML = ctx.changeRequests.slice(0, 12).map((item) => {
      const patchSummary = String(item.patch_summary || "").trim();
      const payloadPatch = item.payload_patch || {};
      const baselinePayload = item.baseline_payload || {};
      const changedKeyCount = Number(payloadPatch.changed_key_count || 0);
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
        <div class="governance-card">
          <div class="governance-card-title">#${item.id} / ${ctx.escapeHtml(item.target_type)} / ${ctx.escapeHtml(item.target_key)}</div>
          <div class="governance-card-meta">
            status=${ctx.escapeHtml(item.status)} · proposal_kind=${ctx.escapeHtml(item.proposal_kind || "manual_change")} · requested_by=${ctx.escapeHtml(item.requested_by_actor || "-")} · reviewed_by=${ctx.escapeHtml(item.reviewed_by_actor || "-")}
          </div>
          ${item.source_change_request_id ? `<div class="info-row"><span class="label">Source CR：</span>#${ctx.escapeHtml(String(item.source_change_request_id))}</div>` : ""}
          ${item.source_workflow_proposal_id ? `<div class="info-row"><span class="label">Source Proposal：</span>#${ctx.escapeHtml(String(item.source_workflow_proposal_id))}</div>` : ""}
          <div class="info-row"><span class="label">Rationale：</span>${ctx.escapeHtml(item.rationale || "无")}</div>
          <div class="info-row"><span class="label">Patch：</span>${ctx.escapeHtml(patchSummary || "无")} · changed_keys=${ctx.escapeHtml(String(changedKeyCount || 0))} · payload_hash=${ctx.escapeHtml(proposedPayloadHash)}</div>
          <div class="info-row"><span class="label">Payload：</span><pre>${ctx.escapeHtml(previewJson(item.proposed_payload || {}, 8))}</pre></div>
          ${changedKeyCount > 0 ? `<div class="info-row"><span class="label">Patch Preview：</span><pre>${ctx.escapeHtml(previewJson(payloadPatch, 8))}</pre></div>` : ""}
          ${Object.keys(baselinePayload).length > 0 ? `<div class="info-row"><span class="label">Baseline Preview：</span><pre>${ctx.escapeHtml(previewJson(baselinePayload, 8))}</pre></div>` : ""}
          <div class="info-row"><span class="label">Shadow Validation：</span>status=${ctx.escapeHtml(shadowValidationStatus)} · ready_to_apply=${ctx.escapeHtml(String(shadowValidationReady))} · result=${ctx.escapeHtml(shadowValidationResult)} · mode=${ctx.escapeHtml(shadowValidationMode)} · candidate_match=${ctx.escapeHtml(candidateMatch)}</div>
          ${item.requires_shadow_validation ? `<div class="info-row"><span class="label">Shadow Context：</span>proposal=#${ctx.escapeHtml(String(item.source_workflow_proposal_id || "-"))} · shadow_task=#${ctx.escapeHtml(String(shadowValidationTaskId))} · audit=#${ctx.escapeHtml(String(shadowValidationAuditId))}</div>` : ""}
          <div class="info-row"><span class="label">Acceptance：</span>status=${ctx.escapeHtml(acceptanceStatus)} · auto_rollback=${ctx.escapeHtml(String(Boolean(item.auto_rollback_applied)))} · rollback_cr=#${ctx.escapeHtml(String(autoRollbackId))}</div>
          <div class="info-row"><span class="label">Rollback：</span>ready=${ctx.escapeHtml(String(Boolean(item.rollback_ready)))} · note=${ctx.escapeHtml(item.rollback_note || "无")}</div>
          ${rollbackItem ? `<div class="info-row"><span class="label">Rollback 单：</span>#${ctx.escapeHtml(String(rollbackItem.id || "-"))} · status=${ctx.escapeHtml(rollbackItem.status || "-")}</div>` : ""}
          <div class="top-actions">
            ${item.status === "pending" ? `<button onclick="decideChangeRequest(${item.id}, true)">批准</button><button class="secondary-btn" onclick="decideChangeRequest(${item.id}, false)">拒绝</button>` : ""}
            ${item.requires_shadow_validation && item.source_workflow_proposal_id && !shadowValidationReady && (item.status === "pending" || item.status === "approved") ? `<button class="secondary-btn" onclick="runChangeRequestShadowValidation(${item.id})">跑 Shadow Validation</button>` : ""}
            ${item.requires_shadow_validation && item.source_workflow_proposal_id ? `<button class="ghost-btn" onclick="showChangeRequestShadowValidation(${item.id})">查看 Shadow 状态</button>` : ""}
            ${item.status === "approved" && (shadowValidationReady || !item.requires_shadow_validation) ? `<button onclick="applyChangeRequest(${item.id})">应用</button>` : ""}
            ${item.status === "applied" && item.can_create_rollback ? `<button class="ghost-btn" onclick="createRollbackChangeRequest(${item.id})">创建回滚单</button>` : ""}
          </div>
        </div>
      `;
    }).join("");
  }

  function renderAccessQuotaUsage(ctx) {
    const container = document.getElementById("accessQuotaList");
    if (!ctx.accessQuotaUsage.length) {
      container.innerHTML = `<div class="empty">暂无配额使用数据</div>`;
      return;
    }

    container.innerHTML = ctx.accessQuotaUsage.map((item) => `
      <div class="governance-card" data-testid="access-quota-card">
        <div class="governance-card-title">${ctx.escapeHtml(item.actor_name)} / ${ctx.escapeHtml(item.role)}</div>
        <div class="governance-card-meta">
          daily ${ctx.escapeHtml(String(item.daily_task_count))}/${ctx.escapeHtml(String(item.daily_task_limit))} ·
          active ${ctx.escapeHtml(String(item.active_task_count))}/${ctx.escapeHtml(String(item.active_task_limit))} ·
          tokens ${ctx.escapeHtml(String(item.daily_token_count || 0))}/${ctx.escapeHtml(String(item.daily_token_limit || 0))}
        </div>
        <div class="info-row"><span class="label">今日剩余额度：</span>${ctx.escapeHtml(String(item.daily_remaining))}</div>
        <div class="info-row"><span class="label">活跃剩余额度：</span>${ctx.escapeHtml(String(item.active_remaining))}</div>
        <div class="info-row"><span class="label">Token 剩余额度：</span>${ctx.escapeHtml(String(item.daily_token_remaining || 0))}</div>
        <div class="info-row"><span class="label">并行 Agent 上限：</span>${ctx.escapeHtml(String(item.max_parallel_agents || 0))}</div>
        <div class="governance-card-actions">
          <button class="ghost-btn" onclick="openChangeRequestTemplate('access_quota', '${ctx.escapeHtml(item.actor_name)}', JSON.parse(decodeURIComponent('${encodeURIComponent(JSON.stringify({ daily_task_limit: item.daily_task_limit, active_task_limit: item.active_task_limit, daily_token_limit: item.daily_token_limit || 0, max_parallel_agents: item.max_parallel_agents || 0 }))}')), '调整 actor 配额')">发起配额变更</button>
          <button class="ghost-btn" onclick="openChangeRequestTemplate('access_actor', '${ctx.escapeHtml(item.actor_name)}', JSON.parse(decodeURIComponent('${encodeURIComponent(JSON.stringify({ role: item.role, description: `当前 ${item.actor_name} 配置` }))}')), '调整 actor 角色')">发起角色变更</button>
        </div>
      </div>
    `).join("");
  }

  function renderAccessActors(ctx) {
    const container = document.getElementById("accessActorList");
    if (!ctx.accessActors.length) {
      container.innerHTML = `<div class="empty">暂无 actor 数据</div>`;
      return;
    }

    container.innerHTML = ctx.accessActors.map((item) => `
      <div class="governance-card">
        <div class="governance-card-title">${ctx.escapeHtml(item.actor_name)}</div>
        <div class="governance-card-meta">role=${ctx.escapeHtml(item.role || "-")} · tenant=${ctx.escapeHtml(item.tenant_key || "default")}</div>
        <div class="info-row"><span class="label">描述：</span>${ctx.escapeHtml(item.description || "无")}</div>
        <div class="info-row"><span class="label">权限覆盖：</span>${ctx.escapeHtml((item.permission_overrides || []).join(", ") || "无")}</div>
        <div class="info-row"><span class="label">生效权限：</span>${ctx.escapeHtml((item.permissions || []).join(", ") || "无")}</div>
        <div class="governance-card-actions">
          <button class="ghost-btn" onclick="openChangeRequestTemplate('access_actor', '${ctx.escapeHtml(item.actor_name)}', JSON.parse(decodeURIComponent('${encodeURIComponent(JSON.stringify({ role: item.role, description: item.description || "", tenant_key: item.tenant_key || "default", permission_overrides: item.permission_overrides || [] }))}')), '更新 actor 角色或描述')">发起角色变更</button>
          <button class="ghost-btn" onclick="openChangeRequestTemplate('access_quota', '${ctx.escapeHtml(item.actor_name)}', JSON.parse(decodeURIComponent('${encodeURIComponent(JSON.stringify({ daily_task_limit: 30, active_task_limit: 10, daily_token_limit: 300000, max_parallel_agents: 16 }))}')), '更新 actor 配额')">发起配额变更</button>
        </div>
      </div>
    `).join("");
  }

  function renderToolRegistry(ctx) {
    const container = document.getElementById("toolRegistryList");
    if (!ctx.toolRegistry.length) {
      container.innerHTML = `<div class="empty">暂无工具注册数据</div>`;
      return;
    }

    container.innerHTML = ctx.toolRegistry.map((item) => `
      <div class="governance-card">
        <div class="governance-card-title">${ctx.escapeHtml(item.tool_name)}</div>
        <div class="governance-card-meta">
          enabled=${ctx.escapeHtml(String(item.enabled))} · provider=${ctx.escapeHtml(item.provider_type || "-")} · risk=${ctx.escapeHtml(item.risk_level || "-")}
        </div>
        <div class="info-row"><span class="label">Transport：</span>${ctx.escapeHtml(item.transport || "-")}</div>
        <div class="info-row"><span class="label">Server：</span>${ctx.escapeHtml(item.server_name || "-")}</div>
        <div class="info-row"><span class="label">审批：</span>${item.approval_required ? "需要" : "否"}</div>
        <div class="info-row"><span class="label">Provider Config：</span><pre>${ctx.escapeHtml(JSON.stringify(item.provider_config || {}, null, 2))}</pre></div>
        <div class="info-row"><span class="label">说明：</span>${ctx.escapeHtml(item.description || "无")}</div>
      </div>
    `).join("");
  }

  function renderModelRegistry(ctx) {
    const container = document.getElementById("modelRegistryList");
    const providerHtml = ctx.modelProviders.map((item) => `
      <div class="governance-card">
        <div class="governance-card-title">Provider / ${ctx.escapeHtml(item.provider_name)}</div>
        <div class="governance-card-meta">enabled=${ctx.escapeHtml(String(item.enabled))} · driver=${ctx.escapeHtml(item.driver || "-")}</div>
        <div class="info-row"><span class="label">Base URL：</span><span class="inline-code">${ctx.escapeHtml(item.base_url || "-")}</span></div>
        <div class="info-row"><span class="label">API Key Env：</span><span class="inline-code">${ctx.escapeHtml(item.api_key_env || "-")}</span></div>
      </div>
    `).join("");
    const routeHtml = ctx.modelRoutes.map((item) => `
      <div class="governance-card">
        <div class="governance-card-title">Route / ${ctx.escapeHtml(item.route_name)}</div>
        <div class="governance-card-meta">enabled=${ctx.escapeHtml(String(item.enabled))} · provider=${ctx.escapeHtml(item.provider || "-")}</div>
        <div class="info-row"><span class="label">Model：</span>${ctx.escapeHtml(item.model_name || "-")}</div>
        <div class="info-row"><span class="label">Temperature：</span>${ctx.escapeHtml(String(item.temperature ?? "-"))}</div>
        <div class="info-row"><span class="label">Max Tokens：</span>${ctx.escapeHtml(String(item.max_tokens ?? "-"))}</div>
      </div>
    `).join("");
    container.innerHTML = providerHtml || routeHtml ? `${providerHtml}${routeHtml}` : `<div class="empty">暂无模型治理数据</div>`;
  }

  function renderRiskPolicies(ctx) {
    const container = document.getElementById("riskPolicyList");
    if (!ctx.riskPolicies.length) {
      container.innerHTML = `<div class="empty">暂无策略</div>`;
      return;
    }

    container.innerHTML = ctx.riskPolicies.map((policy) => {
      const editing = ctx.riskEditorKey === policy.policy_key;
      const sanitizedKey = ctx.sanitizePolicyKey(policy.policy_key);
      const displayValue =
        policy.value_type === "bool"
          ? policy.policy_value ? "true" : "false"
          : Array.isArray(policy.policy_value)
            ? JSON.stringify(policy.policy_value)
            : `${policy.policy_value}`;
      const editor = editing
        ? policy.value_type === "bool"
          ? `
            <div class="risk-editor">
              <label class="risk-meta">当前值：${ctx.escapeHtml(displayValue)}</label>
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
              <textarea id="risk-input-${sanitizedKey}" rows="3">${ctx.escapeHtml(JSON.stringify(policy.policy_value || [], null, 2))}</textarea>
              <div class="top-actions">
                <button onclick="saveRiskPolicy('${policy.policy_key}', 'json')">保存</button>
                <button class="secondary-btn" onclick="cancelRiskEdit()">取消</button>
              </div>
            </div>
          `
        : "";

      return `
        <div class="risk-card">
          <div class="policy-key">${ctx.escapeHtml(policy.policy_key)}</div>
          <div class="risk-meta">${ctx.escapeHtml(policy.description)}</div>
          <div class="risk-meta"><span class="label">类型：</span>${ctx.escapeHtml(policy.value_type)}</div>
          <div class="risk-value">${ctx.escapeHtml(displayValue)}</div>
          <div class="top-actions">
            <button onclick="toggleRiskEditor('${policy.policy_key}')">${editing ? "关闭编辑" : "编辑"}</button>
          </div>
          ${editor}
        </div>
      `;
    }).join("");
  }

  async function loadRiskPolicies(ctx) {
    try {
      ctx.riskPolicies = await ctx.fetchJson(`${ctx.API_BASE}/risk-policies`);
      renderRiskPolicies(ctx);
      ctx.setRiskMessage("策略已同步");
    } catch (err) {
      document.getElementById("riskPolicyList").innerHTML = `<div class="empty">${ctx.escapeHtml(err.message)}</div>`;
      ctx.setRiskMessage("策略加载失败", true);
    }
  }

  async function loadChangeRequests(ctx) {
    try {
      const status = document.getElementById("changeFilterStatus")?.value || "";
      const targetType = document.getElementById("changeFilterTargetType")?.value || "";
      const proposalKind = document.getElementById("changeFilterProposalKind")?.value || "";
      const params = new URLSearchParams();
      if (status) params.set("status", status);
      if (targetType) params.set("target_type", targetType);
      if (proposalKind) params.set("proposal_kind", proposalKind);
      const query = params.toString();
      ctx.changeRequests = await ctx.fetchJson(`${ctx.API_BASE}/change-requests${query ? `?${query}` : ""}`);
      renderChangeRequests(ctx);
      ctx.setChangeRequestMessage("变更单已同步");
    } catch (err) {
      document.getElementById("changeRequestList").innerHTML = `<div class="empty">${ctx.escapeHtml(err.message)}</div>`;
      ctx.setChangeRequestMessage("变更单加载失败", true);
    }
  }

  async function loadAccessQuotaUsage(ctx) {
    try {
      ctx.accessQuotaUsage = await ctx.fetchJson(`${ctx.API_BASE}/access/quota-usage`);
      renderAccessQuotaUsage(ctx);
    } catch (err) {
      document.getElementById("accessQuotaList").innerHTML = `<div class="empty">${ctx.escapeHtml(err.message)}</div>`;
    }
  }

  async function loadAccessActors(ctx) {
    try {
      ctx.accessActors = await ctx.fetchJson(`${ctx.API_BASE}/access/actors`);
      renderAccessActors(ctx);
      ctx.renderActorContext();
    } catch (err) {
      document.getElementById("accessActorList").innerHTML = `<div class="empty">${ctx.escapeHtml(err.message)}</div>`;
      ctx.renderActorContext();
    }
  }

  async function loadToolRegistry(ctx) {
    try {
      ctx.toolRegistry = await ctx.fetchJson(`${ctx.API_BASE}/tools`);
      renderToolRegistry(ctx);
    } catch (err) {
      document.getElementById("toolRegistryList").innerHTML = `<div class="empty">${ctx.escapeHtml(err.message)}</div>`;
    }
  }

  async function loadModelRegistry(ctx) {
    try {
      const [routes, providers] = await Promise.all([
        ctx.fetchJson(`${ctx.API_BASE}/model-routes`),
        ctx.fetchJson(`${ctx.API_BASE}/model-providers`),
      ]);
      ctx.modelRoutes = routes;
      ctx.modelProviders = providers;
      renderModelRegistry(ctx);
      ctx.renderGlobalStatusBar();
      ctx.renderSettingsView();
    } catch (err) {
      document.getElementById("modelRegistryList").innerHTML = `<div class="empty">${ctx.escapeHtml(err.message)}</div>`;
      ctx.renderSettingsView();
    }
  }

  function toggleRiskEditor(ctx, policyKey) {
    ctx.riskEditorKey = ctx.riskEditorKey === policyKey ? "" : policyKey;
    renderRiskPolicies(ctx);
  }

  function cancelRiskEdit(ctx) {
    ctx.riskEditorKey = "";
    renderRiskPolicies(ctx);
  }

  async function saveRiskPolicy(ctx, policyKey, valueType) {
    const sanitizedKey = ctx.sanitizePolicyKey(policyKey);
    let payloadValue;
    if (valueType === "bool") {
      payloadValue = document.getElementById(`risk-input-${sanitizedKey}`).value === "true";
    } else {
      const input = document.getElementById(`risk-input-${sanitizedKey}`);
      try {
        payloadValue = JSON.parse(input.value);
        if (!Array.isArray(payloadValue)) {
          throw new Error("需要提供 JSON 数组");
        }
      } catch (err) {
        ctx.setRiskMessage(`解析失败：${err.message}`, true);
        return;
      }
    }

    try {
      await ctx.fetchJson(`${ctx.API_BASE}/risk-policies/${encodeURIComponent(policyKey)}`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ policy_value: payloadValue }),
      });
      ctx.riskEditorKey = "";
      ctx.setRiskMessage(`策略 ${policyKey} 保存成功`);
      await loadRiskPolicies(ctx);
    } catch (err) {
      ctx.setRiskMessage(err.message, true);
    }
  }

  async function createChangeRequest(ctx) {
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
      await ctx.fetchJson(`${ctx.API_BASE}/change-requests`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          target_type: targetType,
          target_key: targetKey,
          proposed_payload: proposedPayload,
          rationale,
        }),
      });
      document.getElementById("changeTargetKey").value = "";
      document.getElementById("changePayload").value = "";
      document.getElementById("changeRationale").value = "";
      await loadChangeRequests(ctx);
      await ctx.loadMonitorOverview();
      ctx.showToast("变更单已创建", "success");
    } catch (err) {
      ctx.setChangeRequestMessage(err.message, true);
      ctx.showToast("创建变更单失败", "error");
      alert(err.message);
    }
  }

  async function decideChangeRequest(ctx, changeRequestId, approved) {
    const note = window.prompt(approved ? "请输入批准备注（可留空）" : "请输入拒绝原因", "");
    if (note === null) {
      return;
    }
    const path = approved ? "approve" : "reject";
    try {
      await ctx.fetchJson(`${ctx.API_BASE}/change-requests/${changeRequestId}/${path}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ note }),
      });
      await loadChangeRequests(ctx);
      await ctx.loadMonitorOverview();
      await loadRiskPolicies(ctx);
      await loadToolRegistry(ctx);
      await loadModelRegistry(ctx);
      ctx.showToast(`变更单 #${changeRequestId} 已${approved ? "批准" : "拒绝"}`, "success");
    } catch (err) {
      ctx.setChangeRequestMessage(err.message, true);
      ctx.showToast("变更单审批失败", "error");
      alert(err.message);
    }
  }

  async function applyChangeRequest(ctx, changeRequestId) {
    try {
      await ctx.fetchJson(`${ctx.API_BASE}/change-requests/${changeRequestId}/apply`, {
        method: "POST",
      });
      await loadChangeRequests(ctx);
      await ctx.loadMonitorOverview();
      await loadRiskPolicies(ctx);
      await loadToolRegistry(ctx);
      await loadModelRegistry(ctx);
      await loadAccessQuotaUsage(ctx);
      ctx.showToast(`变更单 #${changeRequestId} 已应用`, "success");
    } catch (err) {
      ctx.setChangeRequestMessage(err.message, true);
      ctx.showToast("变更单应用失败", "error");
      alert(err.message);
    }
  }

  async function runChangeRequestShadowValidation(ctx, changeRequestId) {
    try {
      const result = await ctx.fetchJson(`${ctx.API_BASE}/change-requests/${changeRequestId}/shadow-validate`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          note: `web governance shadow validation for change request #${changeRequestId}`,
          await_completion: true,
          timeout_seconds: 90,
          poll_interval_seconds: 1.0,
        }),
      });
      const shadowState = await ctx.fetchJson(`${ctx.API_BASE}/change-requests/${changeRequestId}/shadow-validation?history_limit=6`);
      const latestValidation = (shadowState || {}).latest_validation || {};
      const latestShadowTask = (shadowState || {}).latest_shadow_task || {};
      const validationResult = ((latestValidation || {}).validation || {}).validation_result || "-";
      const validationMode = ((latestValidation || {}).validation || {}).validation_mode || (result || {}).validation_mode || "-";
      const proposalStatus = shadowState.proposal_shadow_validation_status || "-";
      const gateStatus = ((shadowState || {}).change_request || {}).shadow_validation_status || "-";
      ctx.setChangeRequestMessage(
        `Shadow Validation 完成：gate=${gateStatus} proposal_status=${proposalStatus} result=${validationResult} mode=${validationMode} shadow_task=#${latestShadowTask.id || "-"}`
      );
      await loadChangeRequests(ctx);
      await ctx.loadMonitorOverview();
      ctx.showToast(`变更单 #${changeRequestId} Shadow Validation 完成`, "success");
    } catch (err) {
      ctx.setChangeRequestMessage(err.message, true);
      ctx.showToast("Shadow Validation 失败", "error");
      alert(err.message);
    }
  }

  async function showChangeRequestShadowValidation(ctx, changeRequestId) {
    try {
      const result = await ctx.fetchJson(`${ctx.API_BASE}/change-requests/${changeRequestId}/shadow-validation?history_limit=6`);
      const changeRequest = (result || {}).change_request || {};
      const latestValidation = (result || {}).latest_validation || {};
      const latestShadowTask = (result || {}).latest_shadow_task || {};
      const validationResult = ((latestValidation || {}).validation || {}).validation_result || "-";
      const historyCount = Number(result.history_count || 0);
      const requestCount = Number(result.request_count || 0);
      const validationCount = Number(result.validation_count || 0);
      ctx.setChangeRequestMessage(
        `CR #${changeRequestId} shadow：gate=${changeRequest.shadow_validation_status || "-"} ready=${String(Boolean(changeRequest.shadow_validation_ready_to_apply))} proposal_status=${result.proposal_shadow_validation_status || "-"} history=${historyCount} request=${requestCount} validation=${validationCount} latest_result=${validationResult} shadow_task=#${latestShadowTask.id || "-"}`
      );
    } catch (err) {
      ctx.setChangeRequestMessage(err.message, true);
      alert(err.message);
    }
  }

  async function createRollbackChangeRequest(ctx, changeRequestId) {
    try {
      const result = await ctx.fetchJson(`${ctx.API_BASE}/change-requests/${changeRequestId}/rollback`, {
        method: "POST",
      });
      const rollbackCr = (result || {}).change_request || {};
      ctx.setChangeRequestMessage(
        result && result.created === false ? `回滚单已存在：#${rollbackCr.id || "-"}` : `回滚单已创建：#${rollbackCr.id || "-"}`
      );
      await loadChangeRequests(ctx);
      await ctx.loadMonitorOverview();
      ctx.showToast(`变更单 #${changeRequestId} 回滚单已处理`, "success");
    } catch (err) {
      ctx.setChangeRequestMessage(err.message, true);
      ctx.showToast("创建回滚单失败", "error");
      alert(err.message);
    }
  }

  window.DashboardGovernance = {
    createChangeRequest,
    loadAccessActors,
    loadAccessQuotaUsage,
    loadChangeRequests,
    loadModelRegistry,
    loadRiskPolicies,
    loadToolRegistry,
    applyChangeRequest,
    cancelRiskEdit,
    createRollbackChangeRequest,
    decideChangeRequest,
    renderAccessActors,
    renderAccessQuotaUsage,
    renderChangeRequests,
    renderModelRegistry,
    renderRiskPolicies,
    renderToolRegistry,
    runChangeRequestShadowValidation,
    saveRiskPolicy,
    showChangeRequestShadowValidation,
    toggleRiskEditor,
  };
})();
