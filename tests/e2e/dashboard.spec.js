const { test, expect } = require("@playwright/test");

test("dashboard supports draft confirm, task detail, memory search, and quota visibility", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByTestId("task-input")).toBeVisible();
  await page.getByTestId("task-input").fill("如何整理发布回滚 checklist？");
  await page.getByTestId("task-analyze-button").click();

  await expect(page.getByTestId("task-draft-detail")).toContainText("快速路径");
  await expect(page.getByTestId("task-draft-detail")).toContainText("长期记忆召回");
  await page.getByTestId("fast-path-answer-button").click();
  await expect(page.getByTestId("fast-path-answer-detail")).toContainText("Fast Path 轻量回答");
  await expect(page.getByTestId("fast-path-answer-detail")).toContainText("fast-path:");

  await page.getByTestId("task-confirm-button").click();

  await expect(page.getByTestId("workspace-hero")).toContainText("当前任务");
  await expect(page.getByTestId("task-detail")).toContainText("最终交付");
  await expect(page.getByTestId("task-final-deliverable")).toContainText("mock API 返回的稳定交付");

  await page.getByTestId("memory-search-input").fill("发布 回滚");
  await page.getByTestId("memory-search-button").click();
  await expect(page.getByTestId("memory-search-result")).toContainText("发布回滚 Checklist");
  await expect(page.getByTestId("memory-search-result")).toContainText("命中原因");

  await page.getByTestId("app-tab-governance").click();
  await expect(page.getByTestId("access-quota-list")).toContainText("local_admin");
  await expect(page.getByTestId("access-quota-card").first()).toContainText("今日剩余额度");
});
