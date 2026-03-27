const appState = {
  currentTab: window.localStorage.getItem("ai-assistant-tab") || "home",
  currentActor: window.localStorage.getItem("ai-assistant-actor") || "local_admin",
  currentTaskId: null,
  currentEnvironment: window.location.origin,
  domains: {},
};

export function getAppState() {
  return { ...appState };
}

export function patchAppState(patch) {
  Object.assign(appState, patch || {});
  if (patch && Object.prototype.hasOwnProperty.call(patch, "currentTab")) {
    window.localStorage.setItem("ai-assistant-tab", String(appState.currentTab || "home"));
  }
  if (patch && Object.prototype.hasOwnProperty.call(patch, "currentActor")) {
    window.localStorage.setItem("ai-assistant-actor", String(appState.currentActor || "local_admin"));
  }
  return getAppState();
}

export function registerDomainState(domainName, payload = {}) {
  const nextDomains = {
    ...appState.domains,
    [domainName]: {
      ...(appState.domains[domainName] || {}),
      ...payload,
    },
  };
  appState.domains = nextDomains;
  return getAppState();
}

export function getDomainState(domainName) {
  return { ...(appState.domains[domainName] || {}) };
}
