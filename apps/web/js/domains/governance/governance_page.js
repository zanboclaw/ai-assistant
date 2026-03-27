export function mountGovernancePage() {
  const tab = document.getElementById("app-tab-governance");
  if (!tab) {
    return;
  }
  tab.dataset.domainMounted = "true";
}

