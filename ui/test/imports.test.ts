// Boundaries the kit relies on: one adapter per third-party engine, so an API change touches one file.
import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const root = fileURLToPath(new URL("..", import.meta.url));

function sources(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return entry.name === "node_modules" || entry.name === "e2e" ? [] : sources(path);
    return /\.ts$/.test(entry.name) && !/\.(test|d)\.ts$/.test(entry.name) ? [relative(root, path)] : [];
  });
}

function importers(pattern: RegExp): string[] {
  return [...sources(join(root, "packages")), ...sources(join(root, "apps"))]
    .filter((file) => pattern.test(readFileSync(join(root, file), "utf8")))
    .sort();
}

describe("import boundaries", () => {
  it("only ExtAppsBridge imports the ext-apps SDK", () => {
    expect(importers(/from\s+["']@modelcontextprotocol\/ext-apps/)).toEqual(["packages/kit/src/host/ExtAppsBridge.ts"]);
  });

  it("only the WASM renderer imports Verovio", () => {
    expect(importers(/from\s+["']verovio/)).toEqual(["packages/kit/src/score/ScoreView.ts"]);
  });
});
