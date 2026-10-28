#!/usr/bin/env node
// Static server for the mock host. Serves the built app with the CSP a host would apply, so
// browser tests see the same restrictions as a real MCP Apps sandbox.
// Usage: node test/mock-host/server.mjs [port]

import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const root = new URL("../../", import.meta.url);
const port = Number(process.argv[2] ?? process.env.MOCK_HOST_PORT ?? 4173);

// The spec's restrictive default for a resource without `_meta.ui.csp` (apps.mdx, "Host Behavior").
const SPEC_DEFAULT = [
  "default-src 'none'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "media-src 'self' data:",
  "connect-src 'none'",
];

export const CSP = {
  spec: SPEC_DEFAULT.join("; "),
  // Same, plus the one keyword WebAssembly compilation needs.
  "spec-wasm": SPEC_DEFAULT.map((d) =>
    d.startsWith("script-src") ? `${d} 'wasm-unsafe-eval'` : d,
  ).join("; "),
};

const routes = {
  "/": { file: "test/mock-host/index.html", type: "text/html; charset=utf-8" },
  "/host.js": { file: "test/mock-host/host.js", type: "text/javascript; charset=utf-8" },
  "/app.html": { file: "dist/score-viewer.html", type: "text/html; charset=utf-8", app: true },
};

const server = createServer(async (req, res) => {
  const url = new URL(req.url ?? "/", `http://localhost:${port}`);
  const fixture = url.pathname.match(/^\/fixtures\/([\w.-]+\.musicxml)$/);
  const route = fixture
    ? { file: `test/fixtures/${fixture[1]}`, type: "application/xml; charset=utf-8" }
    : routes[url.pathname];
  if (!route) {
    res.writeHead(404).end("not found");
    return;
  }
  try {
    const body = await readFile(fileURLToPath(new URL(route.file, root)));
    const headers = { "content-type": route.type, "cache-control": "no-store" };
    if (route.app) headers["content-security-policy"] = CSP[url.searchParams.get("csp") ?? "spec-wasm"] ?? CSP.spec;
    res.writeHead(200, headers).end(body);
  } catch {
    res.writeHead(404).end(route.app ? "dist/score-viewer.html missing: run npm run build" : "not found");
  }
});

server.listen(port, "127.0.0.1", () => console.log(`mock host on http://127.0.0.1:${port}/`));
