export function mountSessionsPage() {
  const tab = document.getElementById("app-tab-sessions");
  if (!tab) {
    return;
  }
  tab.dataset.domainMounted = "true";
}

