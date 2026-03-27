import { apiRequest } from "../../app/api_client.js";

export function fetchTaskWorkspace(taskId) {
  return apiRequest(`/tasks/${taskId}`);
}

export function fetchTaskSteps(taskId) {
  return apiRequest(`/tasks/${taskId}/steps`);
}

export function fetchTaskCheckpoint(taskId) {
  return apiRequest(`/tasks/${taskId}/checkpoint`);
}

export function interruptWorkspaceTask(taskId, payload = {}) {
  return apiRequest(`/tasks/${taskId}/interrupt`, { method: "POST", body: payload });
}

export function resumeWorkspaceTask(taskId, payload = {}) {
  return apiRequest(`/tasks/${taskId}/resume`, { method: "POST", body: payload });
}

export function applyWorkspaceRecovery(taskId, payload = {}) {
  return apiRequest(`/tasks/${taskId}/apply-recovery-action`, { method: "POST", body: payload });
}
