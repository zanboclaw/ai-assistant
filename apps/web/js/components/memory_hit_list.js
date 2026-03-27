export function buildMemoryHitSummary(memory) {
  return `${memory?.title || ""} ${memory?.reason || ""}`.trim();
}

