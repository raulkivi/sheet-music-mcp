import { defineConfig, devices } from "@playwright/test";

const PORT = 4173;

// A machine with another pre-installed Chromium can point at it; unset, Playwright uses its own.
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE;

// Runs against the BUILT page (npm run build first), served inside test/mock-host. Specs that
// need the real render-mcp start it over stdio themselves (test/e2e/host-fixture.ts).
// No retries: a flaky spec is fixed, not re-run (docs/research/ui-and-sound-testing-plan.md, U6).
export default defineConfig({
  testDir: "./apps",
  testMatch: "*/e2e/*.spec.ts",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    acceptDownloads: true,
    trace: "retain-on-failure",
    ...(executablePath ? { launchOptions: { executablePath } } : {}),
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: `node test/mock-host/server.mjs ${PORT}`,
    url: `http://127.0.0.1:${PORT}/host.js`,
    reuseExistingServer: !process.env.CI,
  },
});
