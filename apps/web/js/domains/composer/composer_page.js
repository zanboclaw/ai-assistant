import { registerDomainState } from "../../app/state.js";
import {
  analyzeComposerInput,
  confirmComposerDraft,
  createComposerTask,
  fetchComposerMemories,
  runComposerFastPath,
} from "./composer_api.js";
import {
  getComposerDraftSnapshot,
  getCurrentComposerDialogueId,
  setComposerDraftSnapshot,
  setCurrentComposerDialogueId,
} from "./composer_state.js";

function registerComposerDomain() {
  window.__appDomains__ = window.__appDomains__ || {};
  window.__appDomains__.composer = {
    name: "composer",
    analyzeComposerInput,
    confirmComposerDraft,
    createComposerTask,
    fetchComposerMemories,
    runComposerFastPath,
    getCurrentComposerDialogueId,
    setCurrentComposerDialogueId,
    getComposerDraftSnapshot,
    setComposerDraftSnapshot,
  };
}

export function mountComposerPage() {
  const tab = document.getElementById("app-tab-composer");
  if (!tab) {
    return;
  }
  tab.dataset.domainMounted = "true";
  tab.dataset.domainName = "composer";
  registerDomainState("composer", {
    mounted: true,
    tabId: tab.id,
    currentDialogueId: getCurrentComposerDialogueId(),
    hasDraftSnapshot: Boolean(getComposerDraftSnapshot()),
  });
  registerComposerDomain();
}
