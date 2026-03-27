export function buildTaskCardSummary(task) {
  return `${task?.display_user_input || task?.user_input || ""}`.trim();
}

