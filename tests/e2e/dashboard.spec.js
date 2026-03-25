const { test, expect } = require("@playwright/test");

test("dashboard supports dedicated composer page, multi-turn task dialogue, task workspace, session memory search, settings, and governance quota visibility", async ({ page }) => {
  await page.goto("/?api_base=http://127.0.0.1:18000");

  await expect(page.getByTestId("app-tab-home")).toHaveAttribute("aria-selected", "true");
  await expect(page.getByTestId("global-status-bar")).toBeVisible();
  await page.getByTestId("app-tab-composer").click();
  await expect(page.getByTestId("app-tab-composer")).toHaveAttribute("aria-selected", "true");
  await expect(page.getByTestId("task-input")).toBeVisible();
  await page.getByTestId("task-input").fill("如何整理发布回滚 checklist？");
  await page.getByTestId("task-analyze-button").click();

  await expect(page.getByTestId("task-draft-detail")).toContainText("快速路径");
  await expect(page.getByTestId("task-draft-detail")).toContainText("长期记忆召回");
  await expect(page.locator("#taskDialogueTimeline")).toContainText("如何整理发布回滚 checklist？");
  await page.getByTestId("fast-path-answer-button").click();
  await expect(page.getByTestId("fast-path-answer-detail")).toContainText("Fast Path 轻量回答");
  await expect(page.getByTestId("fast-path-answer-detail")).toContainText("fast-path:");
  await expect(page.locator("#taskDialogueTimeline")).toContainText("Fast Path");

  await page.getByTestId("task-input").fill("再补充一版，要求按优先级排序");
  await page.getByTestId("task-analyze-button").click();
  await expect(page.locator("#taskDialogueTimeline")).toContainText("再补充一版，要求按优先级排序");

  await page.getByTestId("task-confirm-button").click();

  await expect(page.getByTestId("workspace-hero")).toContainText("当前任务");
  await expect(page.getByTestId("workspace-hero")).toContainText("下一步");
  await expect(page.getByTestId("task-detail")).toContainText("最终交付");
  await expect(page.getByTestId("task-final-deliverable")).toContainText("mock API 返回的稳定交付");

  await page.getByTestId("app-tab-tasks").click();
  await expect(page.locator("#taskQueueSummary")).toContainText("Needs Action");

  await page.getByTestId("app-tab-sessions").click();
  await page.getByTestId("memory-search-input").fill("发布 回滚");
  await page.getByTestId("memory-search-button").click();
  await expect(page.getByTestId("memory-search-result")).toContainText("发布回滚 Checklist");
  await expect(page.getByTestId("memory-search-result")).toContainText("命中原因");

  await page.getByTestId("app-tab-settings").click();
  await expect(page.locator("#settingsRuntimeSummary")).toContainText("当前 API Base");
  await expect(page.locator("#settingsRuntimeSummary")).toContainText("local_admin");
  await expect(page.locator("#settingsRuntimeSummary")).toContainText("mock12345678");

  await page.getByTestId("app-tab-governance").click();
  await expect(page.getByTestId("access-quota-list")).toContainText("local_admin");
  await expect(page.getByTestId("access-quota-card").first()).toContainText("今日剩余额度");
});
