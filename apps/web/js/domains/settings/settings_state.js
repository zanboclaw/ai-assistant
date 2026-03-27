export function getRuntimeApiBase() {
  return window.localStorage.getItem("ai-assistant-api-base") || "";
}

