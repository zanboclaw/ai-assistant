export function buildDeliverySummary(deliverable) {
  return `${deliverable?.summary || deliverable?.result || ""}`.trim();
}

