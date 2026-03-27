import { apiRequest } from "../../app/api_client.js";

export function analyzeComposerInput(payload) {
  return apiRequest("/intake/route", { method: "POST", body: payload });
}

export function confirmComposerDraft(payload) {
  return apiRequest("/intake/confirm", { method: "POST", body: payload });
}

export function runComposerFastPath(payload) {
  return apiRequest("/chat/fast-path", { method: "POST", body: payload });
}

export function createComposerTask(payload) {
  return apiRequest("/tasks", { method: "POST", body: payload });
}

export function fetchComposerMemories(query, options = {}) {
  const params = new URLSearchParams({ query: String(query || "") });
  if (options.limit) {
    params.set("limit", String(options.limit));
  }
  if (options.memoryKind) {
    params.set("memory_kind", String(options.memoryKind));
  }
  return apiRequest(`/memories/search?${params.toString()}`);
}
