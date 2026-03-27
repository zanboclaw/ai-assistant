export function getMonitorRefreshEnabled() {
  return (window.localStorage.getItem("ai-assistant-monitor-auto-refresh") || "1") === "1";
}

