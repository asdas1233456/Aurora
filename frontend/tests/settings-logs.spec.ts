import { expect, test, type Locator, type Page } from "@playwright/test";


async function expectInViewport(page: Page, locator: Locator, label: string) {
  const box = await locator.boundingBox();
  expect(box, `${label} should have a layout box`).not.toBeNull();
  if (!box) {
    return;
  }

  const viewport = page.viewportSize();
  expect(viewport, "viewport should be available").not.toBeNull();
  if (!viewport) {
    return;
  }

  expect(box.y, `${label} top should be visible`).toBeGreaterThanOrEqual(0);
  expect(box.y + box.height, `${label} bottom should be visible`).toBeLessThanOrEqual(viewport.height);
}

test("logs terminal keeps a real viewport and destructive clear is confirmed", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 768 });
  await page.goto("/logs");

  await expect(page.getByTestId("logs-terminal")).toBeVisible();
  await expect(page.getByTestId("clear-logs-button")).toBeVisible();

  const terminalLayout = await page.getByTestId("logs-terminal").evaluate((element) => {
    const terminal = element.getBoundingClientRect();
    const scroller = element.querySelector('[data-testid="logs-terminal-scroller"]')?.getBoundingClientRect();
    return {
      terminalHeight: terminal.height,
      scrollerHeight: scroller?.height ?? terminal.height,
      pageOverflow: document.documentElement.scrollHeight - document.documentElement.clientHeight,
    };
  });

  expect(terminalLayout.terminalHeight).toBeGreaterThan(330);
  expect(terminalLayout.scrollerHeight).toBeGreaterThan(330);
  expect(terminalLayout.pageOverflow).toBeLessThanOrEqual(140);

  await page.getByTestId("clear-logs-button").click();
  await expect(page.getByRole("alertdialog", { name: "确认清空日志？" })).toBeVisible();
  await page.getByRole("button", { name: "取消" }).click();
  await expect(page.getByRole("alertdialog", { name: "确认清空日志？" })).toHaveCount(0);
});

test("mobile logs keeps the terminal in the first screen with a stable height", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/logs");

  await expect(page.getByTestId("logs-terminal")).toBeVisible();

  const layout = await page.evaluate(() => {
    const terminal = document.querySelector('[data-testid="logs-terminal"]')?.getBoundingClientRect();
    const scroller = document.querySelector('[data-testid="logs-terminal-scroller"]')?.getBoundingClientRect();
    return {
      terminalTop: terminal?.top ?? Number.POSITIVE_INFINITY,
      terminalHeight: terminal?.height ?? 0,
      scrollerHeight: scroller?.height ?? terminal?.height ?? 0,
      overflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    };
  });

  expect(layout.terminalTop).toBeLessThanOrEqual(500);
  expect(layout.terminalHeight).toBeGreaterThan(300);
  expect(layout.scrollerHeight).toBeGreaterThan(300);
  expect(layout.overflowX).toBe(0);
});

test("logs page explains empty and error states", async ({ page }) => {
  await page.route("**/api/v1/logs**", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        summary: { path: "aurora.log", exists: 1, size_bytes: 0, line_count: 0 },
        filters: { level: "", keyword: "", start_time: "", end_time: "" },
        lines: [],
      }),
    });
  });

  await page.goto("/logs");
  await expect(page.getByRole("heading", { name: "没有匹配日志" })).toBeVisible();

  await page.unroute("**/api/v1/logs**");
  await page.route("**/api/v1/logs**", async (route) => {
    await route.fulfill({
      status: 500,
      contentType: "application/json",
      body: JSON.stringify({ detail: "log service unavailable" }),
    });
  });

  await page.reload();
  await expect(page.getByRole("heading", { name: "日志加载失败" })).toBeVisible();
  await expect(page.getByTestId("logs-status")).toContainText("log service unavailable");
});

test("settings action bar is reachable on desktop and advanced settings stay folded", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 768 });
  await page.goto("/settings");

  await expect(page.getByTestId("settings-action-bar")).toBeVisible();
  await expectInViewport(page, page.getByTestId("settings-action-bar"), "settings action bar");
  await expect(page.getByTestId("test-settings-button")).toBeVisible();
  await expect(page.getByTestId("save-settings-button")).toBeVisible();
  await expect(page.getByTestId("settings-runtime-status").getByRole("switch")).toHaveCount(0);

  const layout = await page.getByTestId("settings-action-bar").evaluate((element) => ({
    position: window.getComputedStyle(element).position,
  }));
  expect(layout.position).toBe("sticky");

  const scrollState = await page.evaluate(() => {
    window.scrollTo(0, 620);
    return {
      scrollY: window.scrollY,
      scrollHeight: document.documentElement.scrollHeight,
      clientHeight: document.documentElement.clientHeight,
    };
  });
  const stickyBox = await page.getByTestId("settings-action-bar").boundingBox();
  if (scrollState.scrollHeight > scrollState.clientHeight + 16 && scrollState.scrollY > 0) {
    expect(stickyBox?.y ?? Number.POSITIVE_INFINITY).toBeGreaterThanOrEqual(0);
    expect(stickyBox?.y ?? Number.POSITIVE_INFINITY).toBeLessThanOrEqual(16);
  } else {
    expect(stickyBox?.y ?? Number.POSITIVE_INFINITY).toBeLessThan(220);
  }

  const advancedOpen = await page.getByTestId("settings-advanced-section").evaluate((element) => (element as HTMLDetailsElement).open);
  const apiBaseOpen = await page.getByTestId("settings-api-base-section").evaluate((element) => (element as HTMLDetailsElement).open);
  expect(advancedOpen).toBe(false);
  expect(apiBaseOpen).toBe(false);
});

test("mobile settings starts with the editable controls before runtime metadata", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/settings");

  await expect(page.getByTestId("settings-action-bar")).toBeVisible();
  await expectInViewport(page, page.getByTestId("settings-action-bar"), "mobile settings action bar");

  const layout = await page.evaluate(() => {
    const actionBarElement = document.querySelector('[data-testid="settings-action-bar"]');
    const runtimeElement = document.querySelector('[data-testid="settings-runtime-status"]');
    const actionBar = actionBarElement?.getBoundingClientRect();
    const runtime = runtimeElement?.getBoundingClientRect();
    return {
      actionTop: actionBar?.top ?? Number.POSITIVE_INFINITY,
      runtimeTop: runtime?.top ?? 0,
      actionPosition: actionBarElement ? window.getComputedStyle(actionBarElement).position : "",
      scrollHeight: document.documentElement.scrollHeight,
      overflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    };
  });

  expect(layout.actionTop).toBeLessThan(layout.runtimeTop);
  expect(layout.actionPosition).toBe("sticky");
  expect(layout.scrollHeight).toBeLessThanOrEqual(2100);
  expect(layout.overflowX).toBe(0);
});

test("settings connection test reports results beside the action buttons", async ({ page }) => {
  await page.route("**/api/v1/settings/test", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        llm: { ok: true, latency_ms: 42, message: "LLM reachable" },
        embedding: { ok: true, latency_ms: 58, message: "Embedding reachable" },
        checked_at: new Date().toISOString(),
      }),
    });
  });

  await page.setViewportSize({ width: 1366, height: 768 });
  await page.goto("/settings");
  await expect(page.getByTestId("test-settings-button")).toBeEnabled();
  await page.getByTestId("test-settings-button").click();

  await expect(page.getByTestId("settings-test-results")).toContainText("LLM reachable");
  await expect(page.getByTestId("settings-test-results")).toContainText("Embedding reachable");

  const distance = await page.evaluate(() => {
    const actionBar = document.querySelector('[data-testid="settings-action-bar"]')?.getBoundingClientRect();
    const results = document.querySelector('[data-testid="settings-test-results"]')?.getBoundingClientRect();
    return Math.abs((results?.top ?? 0) - (actionBar?.top ?? 0));
  });

  expect(distance).toBeLessThan(220);
});
