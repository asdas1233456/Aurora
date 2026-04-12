import { expect, test } from "@playwright/test";


test("overview dashboard exposes launch-readiness signals", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByTestId("overview-dashboard")).toBeVisible();
  await expect(page.getByTestId("overview-index-card")).toBeVisible();
  await expect(page.getByTestId("overview-quality-card")).toBeVisible();
  await expect(page.getByTestId("overview-chat-trend")).toBeVisible();
  await expect(page.getByTestId("overview-latency-distribution")).toBeVisible();
  await expect(page.getByTestId("overview-action-items")).toBeVisible();
  await expect(page.getByTestId("overview-asset-stream")).toBeVisible();
  await expect(page.locator("body")).not.toContainText(/\?{6,}/);
});

test("overview intro copy is tucked behind title info icons", async ({ page }) => {
  await page.goto("/");

  const introCopy = "一屏查看系统健康、知识库索引、问答质量和上线前需要处理的事项。";
  await expect(page.getByText(introCopy)).not.toBeVisible();

  await page.getByLabel("Aurora 运行态势说明").hover();
  await expect(page.getByText(introCopy)).toBeVisible();
});
