import { expect, test, type Locator, type Page } from "@playwright/test";


async function expectFullyInViewport(page: Page, locator: Locator, label: string) {
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

  expect(box.y, `${label} top should stay in viewport`).toBeGreaterThanOrEqual(0);
  expect(box.y + box.height, `${label} bottom should stay in viewport`).toBeLessThanOrEqual(viewport.height);
}


test("chat workbench streams answers and keeps citations docked on the right", async ({ page }) => {
  await page.goto("/chat");

  await expect(page.getByTestId("chat-input")).toBeVisible();
  await page.getByTestId("chat-input").fill("ADB 怎么查看当前前台 Activity？");
  await page.getByTestId("send-chat-button").click();

  await expect(page.getByTestId("chat-user-message").last()).toContainText("ADB", { timeout: 15_000 });
  await expect(page.getByTestId("chat-assistant-message").last()).not.toHaveText("", { timeout: 20_000 });
  await expect(page.getByTestId("chat-sources-panel")).toBeVisible();
});

test("chat workbench keeps composer and citations inside the working viewport", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 768 });
  await page.goto("/chat");

  await expect(page.getByTestId("chat-input")).toBeVisible();
  await expectFullyInViewport(page, page.getByTestId("chat-input"), "chat input");
  await expectFullyInViewport(page, page.getByTestId("send-chat-button"), "send button");

  const initialLayout = await page.evaluate(() => ({
    scrollY: window.scrollY,
    overflowY: document.documentElement.scrollHeight - document.documentElement.clientHeight,
    firstPromptHeight: document.querySelector('[data-testid="chat-first-prompt-panel"]')?.getBoundingClientRect().height ?? Number.POSITIVE_INFINITY,
    firstPromptBottom: document.querySelector('[data-testid="chat-first-prompt-panel"]')?.getBoundingClientRect().bottom ?? Number.POSITIVE_INFINITY,
    composerTop: document.querySelector('[data-testid="chat-input-shell"]')?.getBoundingClientRect().top ?? 0,
    composerHeight: document.querySelector('[data-testid="chat-input-shell"]')?.getBoundingClientRect().height ?? Number.POSITIVE_INFINITY,
  }));
  expect(initialLayout.scrollY).toBe(0);
  expect(initialLayout.overflowY).toBeLessThanOrEqual(2);
  expect(initialLayout.firstPromptHeight).toBeLessThanOrEqual(260);
  expect(initialLayout.firstPromptBottom).toBeLessThan(initialLayout.composerTop);
  expect(initialLayout.composerHeight).toBeLessThanOrEqual(112);

  await page.getByTestId("chat-input").fill("ADB 鎬庝箞鏌ョ湅褰撳墠鍓嶅彴 Activity锛?");
  await page.getByTestId("send-chat-button").click();

  await expect(page.getByTestId("chat-citation-card").first()).toBeVisible({ timeout: 20_000 });

  const afterAnswerLayout = await page.evaluate(() => {
    const input = document.querySelector('[data-testid="chat-input"]')?.getBoundingClientRect();
    const send = document.querySelector('[data-testid="send-chat-button"]')?.getBoundingClientRect();
    const citation = document.querySelector('[data-testid="chat-citation-card"]')?.getBoundingClientRect();
    const composer = document.querySelector('[data-testid="chat-input-shell"]')?.getBoundingClientRect();
    return {
      scrollY: window.scrollY,
      overflowY: document.documentElement.scrollHeight - document.documentElement.clientHeight,
      inputBottom: input?.bottom ?? Number.POSITIVE_INFINITY,
      sendBottom: send?.bottom ?? Number.POSITIVE_INFINITY,
      citationTop: citation?.top ?? Number.POSITIVE_INFINITY,
      composerHeight: composer?.height ?? Number.POSITIVE_INFINITY,
      viewportHeight: window.innerHeight,
    };
  });

  expect(afterAnswerLayout.scrollY).toBeLessThanOrEqual(1);
  expect(afterAnswerLayout.overflowY).toBeLessThanOrEqual(2);
  expect(afterAnswerLayout.inputBottom).toBeLessThanOrEqual(afterAnswerLayout.viewportHeight);
  expect(afterAnswerLayout.sendBottom).toBeLessThanOrEqual(afterAnswerLayout.viewportHeight);
  expect(afterAnswerLayout.composerHeight).toBeLessThanOrEqual(112);
  expect(afterAnswerLayout.citationTop).toBeLessThan(500);
});

test("mobile chat starts with the composer reachable before side panels", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/chat");

  await expect(page.getByTestId("chat-input")).toBeVisible();
  await expectFullyInViewport(page, page.getByTestId("chat-input"), "mobile chat input");
  await expectFullyInViewport(page, page.getByTestId("send-chat-button"), "mobile send button");
});

test("graph workbench can route from a highlighted node back into knowledge", async ({ page }) => {
  await page.goto("/graph");

  await expect(page.getByTestId("graph-highlight-list")).toBeVisible();
  await expect(page.getByTestId("graph-node-detail-panel")).toHaveCount(0);

  const firstHighlight = page.locator('[data-testid^="graph-highlight-button-"]').first();
  await expect(firstHighlight).toBeVisible();
  await firstHighlight.click();

  const primaryAction = page.getByTestId("graph-primary-action-button");
  await expect(page.getByTestId("graph-node-detail-panel")).toBeVisible();
  if (await primaryAction.count()) {
    await primaryAction.click();
    await expect(page.getByTestId("selected-document-name")).not.toHaveText("");
  }
});
