import { expect, test } from "@playwright/test";


test("P1 knowledge flow acceptance", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByTestId("hero-title")).toBeVisible();

  await page.getByTestId("nav-knowledge").click();
  await expect(page.getByTestId("knowledge-snapshot")).toBeVisible();
  await expect(page.getByTestId("documents-table")).toBeVisible();
  await expect(page.getByTestId("sync-knowledge-button")).toBeVisible();
  await expect(page.getByTestId("scan-knowledge-button")).toBeVisible();
  await expect(page.getByTestId("reset-knowledge-button")).toBeVisible();

  const firstDocumentTrigger = page.locator('[data-testid^="document-select-"]').first();
  await expect(firstDocumentTrigger).toBeVisible();
  await firstDocumentTrigger.click();

  await expect(page.getByTestId("selected-document-name")).not.toHaveText("--");
  await expect(page.getByTestId("document-preview-name")).toBeVisible();

  await page.getByTestId("preview-launcher-button").click();
  await expect(page.getByTestId("preview-overlay")).toBeVisible();
  await expect(page.getByTestId("preview-content")).toBeVisible();
  await expect(page.getByTestId("preview-content")).not.toHaveText("");
});
