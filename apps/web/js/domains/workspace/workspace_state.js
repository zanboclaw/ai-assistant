export function getSelectedTaskId() {
  const raw = window.localStorage.getItem("ai-assistant-selected-task") || "";
  const value = Number.parseInt(raw, 10);
  return Number.isFinite(value) ? value : null;
}

export function setSelectedTaskId(taskId) {
  const normalized = Number(taskId);
  if (Number.isFinite(normalized)) {
    window.localStorage.setItem("ai-assistant-selected-task", String(normalized));
    return normalized;
  }
  window.localStorage.removeItem("ai-assistant-selected-task");
  return null;
}

export function getCurrentWorkspaceTab() {
  return window.localStorage.getItem("ai-assistant-workspace-tab") || "overview";
}

export function setCurrentWorkspaceTab(tabName) {
  const normalized = String(tabName || "overview");
  window.localStorage.setItem("ai-assistant-workspace-tab", normalized);
  return normalized;
}
