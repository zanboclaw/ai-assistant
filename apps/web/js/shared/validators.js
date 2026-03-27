export function isNonEmptyText(value) {
  return String(value || "").trim().length > 0;
}

