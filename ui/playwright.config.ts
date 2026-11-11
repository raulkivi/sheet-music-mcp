import { defineConfig, devices } from "@playwright/test";

const PORT = 4173;

// Runs against the BUILT page (npm run build first), served inside test/mock-host.
export default defineConfig({
  testDir: "./apps",
  testMatch: "*/e2e/*.spec.ts",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    acceptDownloads: true,
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: `node test/mock-host/server.mjs ${PORT}`,
    url: `http://127.0.0.1:${PORT}/host.js`,
    reuseExistingServer: !process.env.CI,
  },
});
