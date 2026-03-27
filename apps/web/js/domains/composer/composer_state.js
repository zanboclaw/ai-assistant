const CURRENT_DIALOGUE_KEY = "ai-assistant-current-task-dialogue";
const COMPOSER_DRAFT_KEY = "ai-assistant-current-task-draft";

export function getCurrentComposerDialogueId() {
  return window.localStorage.getItem(CURRENT_DIALOGUE_KEY) || "";
}

export function setCurrentComposerDialogueId(dialogueId) {
  const normalized = String(dialogueId || "");
  if (normalized) {
    window.localStorage.setItem(CURRENT_DIALOGUE_KEY, normalized);
  } else {
    window.localStorage.removeItem(CURRENT_DIALOGUE_KEY);
  }
  return normalized;
}

export function getComposerDraftSnapshot() {
  const raw = window.localStorage.getItem(COMPOSER_DRAFT_KEY) || "";
  if (!raw) {
    return null;
  }
  try {
    return JSON.parse(raw);
  } catch (_error) {
    return null;
  }
}

export function setComposerDraftSnapshot(snapshot) {
  if (!snapshot) {
    window.localStorage.removeItem(COMPOSER_DRAFT_KEY);
    return null;
  }
  window.localStorage.setItem(COMPOSER_DRAFT_KEY, JSON.stringify(snapshot));
  return snapshot;
}
