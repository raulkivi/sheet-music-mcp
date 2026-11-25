#!/usr/bin/env node
// Builds registered app pages (apps.config.mjs) to dist/<name>.html, one vite build per app, then
// checks each is self-contained (AC-R1).
// Usage: node scripts/build.mjs [app...]   (no names = every registered app)

import { spawnSync } from "node:child_process";
import { mkdirSync, rmSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { APPS } from "../apps.config.mjs";
import { distFile, selectApps, validateRegistry } from "./lib/apps.mjs";

const ui = (path) => fileURLToPath(new URL(`../${path}`, import.meta.url));

function run(args, env = {}) {
  const { status } = spawnSync(process.execPath, args, { cwd: ui("."), stdio: "inherit", env: { ...process.env, ...env } });
  if (status !== 0) process.exit(status ?? 1);
}

const problems = validateRegistry(APPS);
if (problems.length > 0) {
  console.error(`apps.config.mjs: ${problems.join("; ")}`);
  process.exit(1);
}

const requested = process.argv.slice(2);
let names;
try {
  names = selectApps(APPS, requested);
} catch (error) {
  console.error(error.message);
  process.exit(2);
}

// A full build starts clean; a single-app build leaves the other pages alone.
if (requested.length === 0) rmSync(ui("dist"), { recursive: true, force: true });
mkdirSync(ui("dist"), { recursive: true });

for (const name of names) run([ui("node_modules/vite/bin/vite.js"), "build"], { APP: name });
run([ui("scripts/check-html.mjs"), ...names.map((name) => ui(distFile(name)))]);
