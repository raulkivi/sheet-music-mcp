#!/usr/bin/env node
// U7: runs measure.mjs, applies perf-budget.json and exits 1 on a breach. Run after `npm run build`.
// Needs Node 22.18+ (CI uses 24): it imports the TypeScript budget module, which Vitest also tests.
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { checkBudget, summarise } from "../test/perf/budget.ts";

const budget = JSON.parse(readFileSync(new URL("../perf-budget.json", import.meta.url), "utf8")).limits;
const dir = mkdtempSync(join(tmpdir(), "perf-"));
const reportPath = join(dir, "report.json");
try {
  const run = spawnSync(process.execPath, ["scripts/measure.mjs", "--json", reportPath], {
    cwd: new URL("..", import.meta.url),
    stdio: "inherit",
  });
  if (run.status !== 0) {
    console.error("perf: measure.mjs failed, so there is nothing to check");
    process.exit(2);
  }
  const measured = summarise(JSON.parse(readFileSync(reportPath, "utf8")));
  const breaches = checkBudget(measured, budget);
  console.log("");
  for (const [metric, limit] of Object.entries(budget)) console.log(`${metric}: ${measured[metric]} (limit ${limit})`);
  if (breaches.length) {
    for (const b of breaches) console.error(`PERF BUDGET BREACH ${b.metric}: measured ${b.measured}, limit ${b.limit}`);
    process.exit(1);
  }
  console.log("perf: within budget");
} finally {
  rmSync(dir, { recursive: true, force: true });
}
