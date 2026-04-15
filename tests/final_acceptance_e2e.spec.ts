import { expect, test, type Page } from "../frontend/node_modules/@playwright/test";


const WORKSPACES = [
  { path: "/", marker: "overview-dashboard" },
  { path: "/knowledge", marker: "knowledge-snapshot" },
  { path: "/chat", marker: "chat-input" },
  { path: "/graph", marker: "graph-highlight-list" },
  { path: "/settings", marker: "settings-action-bar" },
  { path: "/logs", marker: "logs-terminal" },
];

function attachRuntimeGuards(page: Page) {
  const failures: string[] = [];

  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning") {
      failures.push(`console:${message.type()}:${message.text()}`);
    }
  });
  page.on("pageerror", (error) => failures.push(`pageerror:${error.message}`));
  page.on("response", (response) => {
    const url = response.url();
    const status = response.status();
    if (url.includes("/api/") && status >= 400) {
      failures.push(`network:${status}:${url}`);
    }
  });

  return failures;
}

async function expectNoHorizontalOverflow(page: Page) {
  const overflowX = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflowX).toBeLessThanOrEqual(1);
}

test("final smoke: every workspace loads without console or API failures", async ({ page }) => {
  const failures = attachRuntimeGuards(page);

  for (const workspace of WORKSPACES) {
    await page.goto(workspace.path);
    await expect(page.getByTestId(workspace.marker)).toBeVisible();
    await expect(page.getByTestId("hero-title")).toHaveText("Aurora");
    await expect(page.locator("body")).not.toContainText(/\?{6,}/);
    await expectNoHorizontalOverflow(page);
  }

  expect(failures).toEqual([]);
});

test("final beta flow: a user can upload, find, preview, and delete knowledge safely", async ({ page }) => {
  const fileName = `final-beta-${Date.now()}.md`;
  const fileBody = Array.from(
    { length: 64 },
    (_, index) => `Final beta acceptance line ${index + 1}: ${fileName}`,
  ).join("\n");

  await page.goto("/knowledge");
  await expect(page.getByTestId("knowledge-search-input")).toBeVisible();

  await page.getByTestId("upload-dialog-button").click();
  await page.getByTestId("knowledge-file-input").setInputFiles({
    name: fileName,
    mimeType: "text/markdown",
    buffer: Buffer.from(`# ${fileName}\n\n${fileBody}\n`, "utf-8"),
  });
  await page.getByTestId("upload-documents-button").click();

  await page.getByTestId("knowledge-search-input").fill(fileName);
  const uploadedRow = page.locator('[data-testid^="document-select-"]').filter({ hasText: fileName }).first();
  await expect(uploadedRow).toBeVisible({ timeout: 20_000 });
  await uploadedRow.click();

  await expect(page.getByTestId("selected-document-name")).toHaveText(fileName);
  await page.getByTestId("preview-launcher-button").click();
  await expect(page.getByTestId("preview-overlay")).toBeVisible();
  await expect(page.getByTestId("preview-content")).toContainText(fileName);
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("preview-overlay")).toHaveCount(0);

  await page.getByTestId("delete-current-document-button").click();
  const confirmDialog = page.getByRole("alertdialog");
  await expect(confirmDialog).toBeVisible();
  await confirmDialog.getByRole("button").last().click();
  await expect(uploadedRow).toHaveCount(0, { timeout: 20_000 });
});

test("final API contract and performance budgets stay within launch thresholds", async ({ request }) => {
  const endpoints = [
    { path: "/api/v1/system/bootstrap", keys: ["overview", "knowledge_status", "documents", "graph"], budgetMs: 3500 },
    { path: "/api/v1/documents", keys: null, budgetMs: 2500 },
    { path: "/api/v1/knowledge-base/status", keys: ["ready", "chunk_count", "document_count"], budgetMs: 2500 },
    { path: "/api/v1/graph", keys: ["nodes", "edges"], budgetMs: 3500 },
    { path: "/api/v1/logs", keys: ["summary", "filters", "lines"], budgetMs: 2500 },
    { path: "/api/v1/settings", keys: ["llm_provider", "embedding_provider", "operations_managed_fields"], budgetMs: 2500 },
  ];

  for (const endpoint of endpoints) {
    const started = performance.now();
    const response = await request.get(endpoint.path);
    const durationMs = performance.now() - started;
    expect(response.ok(), `${endpoint.path} should be healthy`).toBeTruthy();
    expect(durationMs, `${endpoint.path} exceeded performance budget`).toBeLessThan(endpoint.budgetMs);

    const payload = await response.json();
    if (endpoint.keys) {
      for (const key of endpoint.keys) {
        expect(payload, `${endpoint.path} should expose ${key}`).toHaveProperty(key);
      }
    }
  }
});

test("final stability: overview live polling refreshes without stale UI or failed requests", async ({ page }) => {
  const failures = attachRuntimeGuards(page);
  let bootstrapResponses = 0;

  page.on("response", (response) => {
    if (response.url().includes("/api/v1/system/bootstrap") && response.status() === 200) {
      bootstrapResponses += 1;
    }
  });

  await page.goto("/");
  await expect(page.getByTestId("overview-dashboard")).toBeVisible();
  await expect(page.getByText("实时同步")).toBeVisible();
  await page.waitForTimeout(6500);

  expect(bootstrapResponses).toBeGreaterThanOrEqual(2);
  expect(failures).toEqual([]);
});

test("final compatibility: desktop, tablet, and mobile layouts avoid horizontal overflow", async ({ page }) => {
  const viewports = [
    { name: "desktop", width: 1440, height: 900 },
    { name: "tablet", width: 1024, height: 768 },
    { name: "mobile", width: 390, height: 844 },
  ];

  for (const viewport of viewports) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    for (const workspace of WORKSPACES) {
      await page.goto(workspace.path);
      await expect(page.getByTestId(workspace.marker), `${viewport.name} ${workspace.path}`).toBeVisible();
      await expectNoHorizontalOverflow(page);
    }
  }
});
