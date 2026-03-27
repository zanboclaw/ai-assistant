export function getSelectedSessionId() {
  const raw = window.localStorage.getItem("ai-assistant-session-browser") || "";
  const value = Number.parseInt(raw, 10);
  return Number.isFinite(value) ? value : null;
}

