// Playwright fixture for specs that need the real render-mcp: starts it over stdio for the test
// (its own uv venv, a fresh output root), exposes window.mcpHostRelay to the page, and stops it
// afterwards. Open the host with server=real (test/e2e/host-helpers.ts openHost).

import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { test as base, expect } from "@playwright/test";
import { McpRelay, renderMcpLaunch } from "../mock-host/mcp-relay.ts";

const RENDER_MCP_DIR = fileURLToPath(new URL("../../../render-mcp", import.meta.url));

export const test = base.extend<{ renderMcp: McpRelay }>({
  renderMcp: async ({ page }, use) => {
    const outputRoot = mkdtempSync(join(tmpdir(), "sheet-music-ui-e2e-"));
    const relay = await McpRelay.start(renderMcpLaunch(RENDER_MCP_DIR, outputRoot), outputRoot);
    try {
      await page.exposeFunction("mcpHostRelay", (method: string, params: unknown) => relay.handle(method, params));
      await use(relay);
    } finally {
      await relay.close();
      rmSync(outputRoot, { recursive: true, force: true });
    }
  },
});

export { expect };
