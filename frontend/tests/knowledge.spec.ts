import { expect, test } from "@playwright/test";


test("knowledge workspace supports upload preview and explicit deletion", async ({ page }) => {
  const fileName = `codex-knowledge-${Date.now()}.md`;
  const longPreviewBody = Array.from(
    { length: 90 },
    (_, index) => `Aurora knowledge upload smoke line ${index + 1}: ${fileName}`,
  ).join("\n");

  await page.goto("/knowledge");
  await expect(page.getByTestId("knowledge-snapshot")).toBeVisible();
  await expect(page.getByTestId("knowledge-search-input")).toBeVisible();

  await page.getByTestId("upload-dialog-button").click();
  await page.getByTestId("knowledge-file-input").setInputFiles({
    name: fileName,
    mimeType: "text/markdown",
    buffer: Buffer.from(`# ${fileName}\n\n${longPreviewBody}\n`, "utf-8"),
  });
  await page.getByTestId("upload-documents-button").click();

  const uploadedRow = page.locator('[data-testid^="document-select-"]').filter({ hasText: fileName }).first();
  await expect(uploadedRow).toBeVisible();
  await expect.poll(async () => page.getByTestId("documents-table").evaluate((element) => element.getBoundingClientRect().height)).toBeGreaterThan(300);

  await expect(page.getByTestId("selected-document-name")).toHaveText(fileName);

  await page.getByTestId("preview-launcher-button").click();
  await expect(page.getByTestId("preview-overlay")).toBeVisible();
  await expect(page.getByTestId("preview-content")).toContainText(fileName);
  const beforeScroll = await page.getByTestId("preview-scroll-area").evaluate((element) => ({
    clientHeight: element.clientHeight,
    scrollHeight: element.scrollHeight,
    scrollTop: element.scrollTop,
  }));
  expect(beforeScroll.scrollHeight).toBeGreaterThan(beforeScroll.clientHeight + 200);
  await page.getByTestId("preview-scroll-area").evaluate((element) => {
    element.scrollTop = element.scrollHeight;
  });
  const afterScroll = await page.getByTestId("preview-scroll-area").evaluate((element) => element.scrollTop);
  expect(afterScroll).toBeGreaterThan(beforeScroll.scrollTop);
  await page.getByRole("button", { name: "Close" }).click();
  await expect(page.getByTestId("preview-overlay")).toHaveCount(0);

  await page.getByTestId("delete-current-document-button").click();
  await page.getByRole("button", { name: "确认删除" }).click();
  await expect(uploadedRow).toHaveCount(0);
});

test("knowledge library searches documents and keeps the bookshelf readable", async ({ page }) => {
  await page.goto("/knowledge");
  await expect(page.getByTestId("knowledge-snapshot")).toBeVisible();

  const tableHeight = await page.getByTestId("documents-table").evaluate((element) => element.getBoundingClientRect().height);
  expect(tableHeight).toBeGreaterThan(300);

  const firstDocument = page.locator('[data-testid^="document-select-"]').first();
  await expect(firstDocument).toBeVisible();
  const documentText = await firstDocument.innerText();
  const searchTerm = documentText.split(/\s+/)[0].slice(0, 16);

  await page.getByTestId("knowledge-search-input").fill(searchTerm);
  await expect(page.locator('[data-testid^="document-select-"]').filter({ hasText: searchTerm }).first()).toBeVisible();

  await firstDocument.click();
  await expect(page.getByTestId("knowledge-preview-panel")).toBeVisible();
  await expect(page.getByTestId("selected-document-name")).not.toHaveText("");
});

test("knowledge search toolbar keeps controls and icon aligned", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 768 });
  await page.goto("/knowledge");

  const controlTestIds = [
    "knowledge-search-control",
    "knowledge-type-filter",
    "knowledge-status-filter",
    "knowledge-theme-filter",
  ];

  for (const testId of controlTestIds) {
    await expect(page.getByTestId(testId)).toBeVisible();
  }

  const boxes = await Promise.all(
    controlTestIds.map(async (testId) => {
      const box = await page.getByTestId(testId).boundingBox();
      expect(box).not.toBeNull();
      return box!;
    }),
  );

  const [searchBox, ...selectBoxes] = boxes;
  for (const box of selectBoxes) {
    expect(Math.abs(box.height - searchBox.height)).toBeLessThanOrEqual(1);
    expect(Math.abs(box.y - searchBox.y)).toBeLessThanOrEqual(1);
  }

  const searchIconBox = await page.getByTestId("knowledge-search-control").locator("svg").first().boundingBox();
  expect(searchIconBox).not.toBeNull();
  const iconCenter = searchIconBox!.y + searchIconBox!.height / 2;
  const searchCenter = searchBox.y + searchBox.height / 2;
  expect(Math.abs(iconCenter - searchCenter)).toBeLessThanOrEqual(1);
});

test("knowledge workspace cards share the same visual height", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 768 });
  await page.goto("/knowledge");
  await expect(page.getByTestId("knowledge-filter-panel")).toBeVisible();
  await expect(page.getByTestId("knowledge-library-list")).toBeVisible();
  await expect(page.getByTestId("knowledge-preview-panel")).toBeVisible();

  const panelTestIds = ["knowledge-filter-panel", "knowledge-library-list", "knowledge-preview-panel"];
  const boxes = await Promise.all(
    panelTestIds.map(async (testId) => {
      const box = await page.getByTestId(testId).boundingBox();
      expect(box).not.toBeNull();
      return box!;
    }),
  );

  const topValues = boxes.map((box) => box.y);
  const bottomValues = boxes.map((box) => box.y + box.height);
  const heightValues = boxes.map((box) => box.height);

  expect(Math.max(...topValues) - Math.min(...topValues)).toBeLessThanOrEqual(1);
  expect(Math.max(...bottomValues) - Math.min(...bottomValues)).toBeLessThanOrEqual(1);
  expect(Math.max(...heightValues) - Math.min(...heightValues)).toBeLessThanOrEqual(1);

  const firstDocument = page.locator('[data-testid^="document-select-"]').first();
  await expect(firstDocument).toBeVisible();
  await firstDocument.click();
  await expect(page.getByTestId("selected-document-name")).not.toHaveText("");

  const selectedBoxes = await Promise.all(
    panelTestIds.map(async (testId) => {
      const box = await page.getByTestId(testId).boundingBox();
      expect(box).not.toBeNull();
      return box!;
    }),
  );
  const selectedBottomValues = selectedBoxes.map((box) => box.y + box.height);
  expect(Math.max(...selectedBottomValues) - Math.min(...selectedBottomValues)).toBeLessThanOrEqual(1);
});
