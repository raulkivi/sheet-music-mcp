#!/usr/bin/env node
// Copies built app pages into the servers that serve them (decision D1: generated, not committed).

import { copyFileSync, existsSync, mkdirSync } from "node:fs";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

const ui = (path) => fileURLToPath(new URL(`../${path}`, import.meta.url));

const ASSETS = [
  { from: ui("dist/score-viewer.html"), to: ui("../render-mcp/src/render_mcp/ui/assets/score-viewer.html") },
];

let missing = false;
for (const { from, to } of ASSETS) {
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
