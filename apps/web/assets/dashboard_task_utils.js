(function attachDashboardTaskUtils(global) {
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

  global.DashboardTaskUtils = {
    formatDateTime,
    getTaskActionCategory,
    getTaskAttentionLevel,
    getTaskSearchableText,
    safeArray,
    summarizeTaskStatus,
  };
})(window);
