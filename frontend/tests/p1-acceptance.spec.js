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

test("document deletion actions stay explicit and usable", async ({ page }) => {
  const fileName = `codex-delete-smoke-${Date.now()}.md`;

  await page.goto("/");
  await page.getByTestId("nav-knowledge").click();
  await expect(page.getByTestId("documents-table")).toBeVisible();

  await page.locator('input[type="file"]').setInputFiles({
    name: fileName,
    mimeType: "text/markdown",
    buffer: Buffer.from(`# ${fileName}\n\nDelete flow smoke test.\n`, "utf-8"),
  });
  await page.getByTestId("upload-documents-button").click();

  const uploadedRowButton = page.getByRole("button", { name: fileName });
  await expect(uploadedRowButton).toBeVisible();

  await uploadedRowButton.click();
  await expect(page.getByTestId("document-preview-name")).toHaveText(fileName);
  await expect(page.getByTestId("delete-selected-documents-button")).toBeDisabled();
  await expect(page.getByTestId("delete-current-document-button")).toBeEnabled();

  page.once("dialog", (dialog) => dialog.accept());
  await page.getByTestId("delete-current-document-button").click();

  await expect(uploadedRowButton).toHaveCount(0);
});
