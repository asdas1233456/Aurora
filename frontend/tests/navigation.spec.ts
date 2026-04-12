import { expect, test } from "@playwright/test";


test("top navigation switches between all redesigned workspaces", async ({ page }) => {
  await page.goto("/");

  const appHeader = page.locator("header");
  await expect(page.getByTestId("hero-title")).toHaveText("Aurora");
  await expect(page.getByTestId("workspace-user-badge")).toHaveText("Playwright Admin");
  await expect(appHeader.getByText(/^p1$/)).toHaveCount(0);

  await page.getByTestId("nav-knowledge").click();
  await expect(page.getByTestId("knowledge-snapshot")).toBeVisible();

  await page.getByTestId("nav-chat").click();
  await expect(page.getByTestId("chat-input")).toBeVisible();

  await page.getByTestId("nav-graph").click();
  await expect(page.getByTestId("graph-highlight-list")).toBeVisible();

  await page.getByTestId("nav-settings").click();
  await expect(page.getByText("可调参数中心")).toBeVisible();

  await page.getByTestId("nav-logs").click();
  await expect(page.getByTestId("logs-terminal")).toBeVisible();
  await expect(page.getByTestId("hero-title")).toHaveText("Aurora");
});
