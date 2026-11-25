#!/usr/bin/env node
// Copies built app pages into the servers that serve them (decision D1: generated, not committed).
// The mapping comes from apps.config.mjs (copyPlan); a page with several targets is copied to each.

import { copyFileSync, existsSync, mkdirSync } from "node:fs";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { APPS } from "../apps.config.mjs";
import { copyPlan } from "./lib/apps.mjs";

const ui = (path) => fileURLToPath(new URL(`../${path}`, import.meta.url));

let missing = false;
for (const plan of copyPlan(APPS)) {
  const from = ui(plan.from);
  const to = ui(plan.to);
  if (!existsSync(from)) {
    console.error(`missing ${from}: run npm run build first`);
    missing = true;
    continue;
  }
  mkdirSync(dirname(to), { recursive: true });
  copyFileSync(from, to);
  console.log(`copied ${from} -> ${to}`);
}
process.exitCode = missing ? 1 : 0;
