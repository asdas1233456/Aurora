const path = require("node:path");

const { defineConfig } = require("../frontend/node_modules/@playwright/test");

const repoRoot = path.resolve(__dirname, "..");
const pythonCommand = process.platform === "win32"
  ? ".\\.venv\\Scripts\\python.exe"
  : "./.venv/bin/python";

module.exports = defineConfig({
  testDir: ".",
  testMatch: "final_acceptance_e2e.spec.ts",
  timeout: 60_000,
  fullyParallel: false,
  retries: 0,
  webServer: {
    command: `${pythonCommand} -m uvicorn app.bootstrap.http_app:app --host 127.0.0.1 --port 8010`,
    url: "http://127.0.0.1:8010/health",
    cwd: repoRoot,
    env: {
      ...process.env,
      AUTH_MODE: "trusted_header",
      TENANT_ID: "t1",
      LLM_PROVIDER: "local_mock",
      LLM_MODEL: "local-mock-v1",
      MEMORY_LLM_REVIEW_ENABLED: "false",
    },
    reuseExistingServer: false,
    timeout: 120_000,
  },
  use: {
    baseURL: "http://127.0.0.1:8010",
    headless: true,
    extraHTTPHeaders: {
      "x-auth-request-user": "playwright-admin",
      "x-auth-request-name": "Playwright Admin",
      "x-auth-request-email": "playwright-admin@example.internal",
      "x-auth-request-role": "admin",
      "x-auth-request-team": "team-platform",
      "x-auth-request-projects": "p1",
      "x-aurora-project-id": "p1",
    },
    trace: "on-first-retry",
  },
});
