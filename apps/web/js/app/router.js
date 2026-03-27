import { emit } from "./event_bus.js";
import { patchAppState } from "./state.js";

function normalizeRoute(hashValue) {
  const raw = String(hashValue || "").replace(/^#\/?/, "").trim();
  return raw || "home";
}

export function navigateTo(tabName) {
  const nextTab = normalizeRoute(tabName);
  patchAppState({ currentTab: nextTab });
  if (window.location.hash !== `#/${nextTab}`) {
    window.location.hash = `#/${nextTab}`;
  }
  if (typeof window.setAppTab === "function") {
    window.setAppTab(nextTab);
  }
  emit("route:changed", nextTab);
}

export function bindRouter() {
  window.addEventListener("hashchange", () => {
    navigateTo(window.location.hash);
  });
  navigateTo(window.location.hash || window.localStorage.getItem("ai-assistant-tab") || "home");
}

