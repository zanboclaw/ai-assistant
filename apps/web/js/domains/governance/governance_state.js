export function getGovernanceActor() {
  return window.localStorage.getItem("ai-assistant-actor") || "local_admin";
}

