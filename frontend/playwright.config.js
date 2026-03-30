import { defineConfig } from "@playwright/test";


export default defineConfig({
  testDir: "./tests",
  timeout: 30_000,
  fullyParallel: false,
  retries: 0,
  use: {
    baseURL: "http://127.0.0.1:8000",
    headless: true,
    trace: "on-first-retry",
  },
});
