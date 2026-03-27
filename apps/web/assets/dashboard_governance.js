(function () {
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
      " from __future__ import annotations",
    ].join("\n");
  }

  function buildChangePayloadTemplate(targetType) {
    if (targetType === "risk_policy") {
      return {
        targetKey: "approval_require_for_hidden_files",
        payload: {
          policy_value: false,
        },
        rationale: "调整隐藏文件审批策略",
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
          description: "临时禁用联网搜索",
        },
        rationale: "收紧工具执行范围",
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
          description: "任务规划模型",
        },
        rationale: "调整规划模型路由",
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
          description: "默认 DeepSeek provider",
        },
        rationale: "维护默认 provider 配置",
      };
    }
    if (targetType === "access_quota") {
      return {
        targetKey: "local_operator",
        payload: {
          daily_task_limit: 30,
          active_task_limit: 10,
          daily_token_limit: 300000,
          max_parallel_agents: 16,
        },
        rationale: "调整 operator 配额",
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
              STAGE7_EXPECT_CONTAINS: "stage7 sandbox_file patch example",
            },
          },
        },
        rationale: "创建 sandbox_file source-patch 实验变更",
      };
    }
    return {
      targetKey: "change_bot",
      payload: {
        role: "viewer",
        description: "变更管理 smoke actor",
        tenant_key: "default",
        permission_overrides: [],
      },
      rationale: "创建只读 actor",
    };
  }

  function fillChangePayloadTemplate(ctx, force = true, overrides = {}) {
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
        <div class="governance-help-title">${ctx.escapeHtml(meta.title)}</div>
        <div class="governance-help-line"><span class="label">${ctx.escapeHtml(meta.keyLabel)}：</span>${ctx.escapeHtml(meta.keyHint)}</div>
        <div class="governance-help-line">${ctx.escapeHtml(meta.formHint)}</div>
        <div class="governance-help-line">${ctx.escapeHtml(meta.example)}</div>
      `;
    }

    if (previewEl) {
      previewEl.innerHTML = `
        <div class="governance-template-badge">${ctx.escapeHtml(meta.badge)}</div>
        <div class="governance-template-card">
          <div class="governance-template-card-title">${ctx.escapeHtml(meta.title)}</div>
          <div class="governance-template-card-text"><span class="label">target_key：</span>${ctx.escapeHtml(targetKey)}</div>
          <div class="governance-template-card-text"><span class="label">payload：</span><pre>${ctx.escapeHtml(JSON.stringify(payload, null, 2))}</pre></div>
          <div class="governance-template-card-text"><span class="label">rationale：</span>${ctx.escapeHtml(rationale)}</div>
        </div>
      `;
    }
  }

  function jumpToChangeTemplate(ctx, targetType, targetKey = "", payload = null, rationale = "") {
    const targetTypeEl = document.getElementById("changeTargetType");
    targetTypeEl.value = targetType;
    fillChangePayloadTemplate(ctx, true, {
      targetKey,
      payload,
      rationale,
    });
  }

  function openChangeRequestTemplate(ctx, targetType, targetKey, payload = null, rationale = "") {
    jumpToChangeTemplate(ctx, targetType, targetKey, payload, rationale);
    ctx.setAppTab("governance");
    document.getElementById("changeTargetType").scrollIntoView({ behavior: "smooth", block: "start" });
  }

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
    buildSandboxFileSourcePatchTemplate,
    loadModelRegistry,
    loadRiskPolicies,
    loadToolRegistry,
    applyChangeRequest,
    fillChangePayloadTemplate,
    cancelRiskEdit,
    createRollbackChangeRequest,
    decideChangeRequest,
    getChangeTargetMeta,
    jumpToChangeTemplate,
    openChangeRequestTemplate,
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
