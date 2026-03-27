export function mountSettingsPage() {
  const tab = document.getElementById("app-tab-settings");
  if (!tab) {
    return;
  }
  tab.dataset.domainMounted = "true";
}

