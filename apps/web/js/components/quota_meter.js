export function buildQuotaLabel(quota) {
  return `${quota?.actor_name || "actor"} ${quota?.remaining_today || quota?.daily_limit || 0}`;
}

