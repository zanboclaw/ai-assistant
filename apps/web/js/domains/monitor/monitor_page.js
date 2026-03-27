export function mountMonitorPage() {
  const tab = document.getElementById("app-tab-monitor");
  if (!tab) {
    return;
  }
  tab.dataset.domainMounted = "true";
}

