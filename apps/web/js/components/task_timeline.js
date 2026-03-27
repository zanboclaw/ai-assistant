export function buildTaskTimelineSteps(steps = []) {
  return Array.isArray(steps) ? steps.map((item) => item.step_name || item.title || "") : [];
}

