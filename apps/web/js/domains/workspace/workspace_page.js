import { registerDomainState } from "../../app/state.js";
import {
  applyWorkspaceRecovery,
  fetchTaskCheckpoint,
  fetchTaskSteps,
  fetchTaskWorkspace,
  interruptWorkspaceTask,
  resumeWorkspaceTask,
} from "./workspace_api.js";
import {
  getCurrentWorkspaceTab,
  getSelectedTaskId,
  setCurrentWorkspaceTab,
  setSelectedTaskId,
} from "./workspace_state.js";

function registerWorkspaceDomain() {
  window.__appDomains__ = window.__appDomains__ || {};
  window.__appDomains__.workspace = {
    name: "workspace",
    fetchTaskWorkspace,
    fetchTaskSteps,
    fetchTaskCheckpoint,
    interruptWorkspaceTask,
    resumeWorkspaceTask,
    applyWorkspaceRecovery,
    getSelectedTaskId,
    setSelectedTaskId,
    getCurrentWorkspaceTab,
    setCurrentWorkspaceTab,
  };
}

export function mountWorkspacePage() {
  const tab = document.getElementById("app-tab-workspace");
  if (!tab) {
    return;
  }
  tab.dataset.domainMounted = "true";
  tab.dataset.domainName = "workspace";
  registerDomainState("workspace", {
    mounted: true,
    tabId: tab.id,
    selectedTaskId: getSelectedTaskId(),
    currentWorkspaceTab: getCurrentWorkspaceTab(),
  });
  registerWorkspaceDomain();
}
