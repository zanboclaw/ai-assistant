import { bindRouter, navigateTo } from "./router.js";
import { patchAppState } from "./state.js";
import { mountComposerPage } from "../domains/composer/composer_page.js";
import { mountWorkspacePage } from "../domains/workspace/workspace_page.js";
import { mountSessionsPage } from "../domains/sessions/sessions_page.js";
import { mountGovernancePage } from "../domains/governance/governance_page.js";
import { mountMonitorPage } from "../domains/monitor/monitor_page.js";
import { mountSettingsPage } from "../domains/settings/settings_page.js";

function connectLegacyGlobals() {
  if (typeof window.setAppTab === "function") {
    const legacySetAppTab = window.setAppTab;
    window.setAppTab = function setAppTabWithRouter(tabName) {
      patchAppState({ currentTab: tabName });
      legacySetAppTab(tabName);
      if (window.location.hash !== `#/${tabName}`) {
        history.replaceState(null, "", `#/${tabName}`);
      }
    };
  }
}

function mountDomains() {
  mountComposerPage();
  mountWorkspacePage();
  mountSessionsPage();
  mountGovernancePage();
  mountMonitorPage();
  mountSettingsPage();
}

window.addEventListener("DOMContentLoaded", () => {
  connectLegacyGlobals();
  mountDomains();
  bindRouter();
  navigateTo(window.localStorage.getItem("ai-assistant-tab") || "home");
});

