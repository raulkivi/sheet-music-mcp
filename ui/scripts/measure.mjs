#!/usr/bin/env node
// Spike step 11 (decision D4): page size, time to first rendered page and peak JS heap of the
// built Score Viewer inside the mock host. Run after `npm run build`.
// Usage: node scripts/measure.mjs [--runs 3] [--json out.json]

import { spawn } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { gzipSync } from "node:zlib";
import { chromium, devices } from "@playwright/test";

const args = process.argv.slice(2);
const option = (name, fallback) => {
  const i = args.indexOf(name);
  return i >= 0 ? args[i + 1] : fallback;
};
const RUNS = Number(option("--runs", "3"));
const JSON_OUT = option("--json", undefined);
const PORT = 4174;
const FIRST_PAGE_MARK = "score-first-page"; // apps/score-viewer/dom.ts

const PROFILES = [
  {
    name: "desktop",
    context: { viewport: { width: 1280, height: 800 } },
    cpuThrottle: 1,
    query: "scenario=inline-long&width=1000",
  },
  {
    name: "phone, 4x CPU throttle",
    context: { ...devices["Pixel 5"] },
    cpuThrottle: 4,
    query: "scenario=inline-long&width=361",
  },
];

function sizes() {
  const html = readFileSync(new URL("../dist/score-viewer.html", import.meta.url));
  return { rawBytes: html.length, gzipBytes: gzipSync(html, { level: 9 }).length };
}

async function startServer() {
  const server = spawn(process.execPath, ["test/mock-host/server.mjs", String(PORT)], {
    cwd: new URL("..", import.meta.url),
    stdio: ["ignore", "pipe", "inherit"],
  });
  await new Promise((resolve, reject) => {
    server.stdout.once("data", resolve);
    server.once("exit", (code) => reject(new Error(`mock host exited with ${code}`)));
  });
  return server;
}

async function measureOnce(browser, profile) {
  const context = await browser.newContext(profile.context);
  const page = await context.newPage();
  const cdp = await context.newCDPSession(page);
  await cdp.send("Performance.enable");
  if (profile.cpuThrottle > 1) await cdp.send("Emulation.setCPUThrottlingRate", { rate: profile.cpuThrottle });

  let peakHeap = 0;
  let sampling = true;
  const sampler = (async () => {
    while (sampling) {
      const { metrics } = await cdp.send("Performance.getMetrics").catch(() => ({ metrics: [] }));
      const used = metrics.find((m) => m.name === "JSHeapUsedSize")?.value ?? 0;
      peakHeap = Math.max(peakHeap, used);
      await new Promise((r) => setTimeout(r, 25));
    }
  })();

  const started = Date.now();
  await page.goto(`http://127.0.0.1:${PORT}/?${profile.query}`);
  const frame = page.frameLocator("iframe");
  await frame.locator("#score svg").first().waitFor({ timeout: 120_000 });
  const hostMs = Date.now() - started;
  const appFrame = page.frames().find((f) => f.url().includes("/app.html"));
  const frameMs = await appFrame.evaluate(
    (mark) => performance.getEntriesByName(mark)[0]?.startTime ?? Number.NaN,
    FIRST_PAGE_MARK,
  );
  sampling = false;
  await sampler;
  const pageCount = (await frame.locator("#page-label").textContent())?.trim();
  await context.close();
  return { frameMs, hostMs, peakHeapBytes: peakHeap, pageCount };
}

const median = (values) => [...values].sort((a, b) => a - b)[Math.floor(values.length / 2)];
const mb = (bytes) => `${(bytes / 1024 / 1024).toFixed(2)} MB`;

const size = sizes();
const server = await startServer();
// Keep the sandboxed iframe in the page's process so CPU throttling and heap metrics cover it.
const browser = await chromium.launch({ args: ["--disable-features=IsolateSandboxedIframes"] });
const results = [];
try {
  for (const profile of PROFILES) {
    const runs = [];
    for (let i = 0; i < RUNS; i++) runs.push(await measureOnce(browser, profile));
    results.push({
      profile: profile.name,
      runs: RUNS,
      frameToFirstPageMs: Math.round(median(runs.map((r) => r.frameMs))),
      hostToFirstPageMs: Math.round(median(runs.map((r) => r.hostMs))),
      peakJsHeapBytes: Math.max(...runs.map((r) => r.peakHeapBytes)),
      pageLabel: runs[0].pageCount,
    });
  }
} finally {
  await browser.close();
  server.kill();
}

console.log(
  `score-viewer.html: ${size.rawBytes} bytes (${mb(size.rawBytes)}) raw, ` +
    `${size.gzipBytes} bytes (${mb(size.gzipBytes)}) gzip -9`,
);
console.log("");
console.log("| Profile | Frame start → first page | Host navigation → first page | Peak JS heap | Pages |");
console.log("|---|---|---|---|---|");
for (const r of results) {
  console.log(
    `| ${r.profile} | ${r.frameToFirstPageMs} ms | ${r.hostToFirstPageMs} ms | ${mb(r.peakJsHeapBytes)} | ${r.pageLabel} |`,
  );
}
console.log("");
console.log(`Median of ${RUNS} runs; fixture test/fixtures/satb-long.musicxml; Chromium via Playwright.`);
if (JSON_OUT) writeFileSync(JSON_OUT, JSON.stringify({ size, results }, null, 2));
