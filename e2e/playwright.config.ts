import { defineConfig, devices } from "@playwright/test";

// The server runs with ENV=test (FakeRunner: the verdict comes from a
// "# VERDICT: ..." comment) and serves the built web app, so one origin
// handles pages, REST and WebSockets. Run `make e2e` from the repo root.
const PORT = Number(process.env.E2E_PORT ?? 8010);

export default defineConfig({
  testDir: "./specs",
  timeout: 120_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    viewport: { width: 1280, height: 860 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 860 } } }],
  webServer: {
    command: `bash ../scripts/e2e_server.sh ${PORT}`,
    url: `http://127.0.0.1:${PORT}/api/healthz`,
    reuseExistingServer: false,
    timeout: 60_000,
    stdout: "pipe",
  },
});
