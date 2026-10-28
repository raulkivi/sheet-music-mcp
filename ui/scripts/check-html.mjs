#!/usr/bin/env node
// AC-R1: a built app page must load nothing from anywhere, so hosts need no CSP allowances.
// Usage: node scripts/check-html.mjs dist/score-viewer.html [...]

import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const RAW_TEXT = /<(script|style)\b([^>]*)>[\s\S]*?<\/\1\s*>/gi;
const TAG = /<([a-z][a-z0-9-]*)\b([^>]*)>/gi;
const URL_ATTR = /\s(src|href)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))/gi;

/** Returns one entry per element that references something outside the document. */
export function externalReferences(html) {
  // Script and style bodies are code, not markup; strings inside them are not references.
  const markup = html.replace(RAW_TEXT, (_m, name, attrs) => `<${name}${attrs}>`);
  const found = [];
  for (const [, name, attrs] of markup.matchAll(TAG)) {
    for (const [, attr, dq, sq, bare] of attrs.matchAll(URL_ATTR)) {
      const value = (dq ?? sq ?? bare ?? "").trim();
      if (isInDocument(name, value)) continue;
      found.push(`<${name.toLowerCase()} ${attr.toLowerCase()}="${value}">`);
    }
  }
  return found;
}

function isInDocument(tag, value) {
  if (tag.toLowerCase() === "base") return false;
  return value.startsWith("#") || /^data:/i.test(value);
}

function main(paths) {
  if (paths.length === 0) {
    console.error("usage: check-html.mjs <file.html> [...]");
    return 2;
  }
  let status = 0;
  for (const path of paths) {
    const refs = externalReferences(readFileSync(path, "utf8"));
    if (refs.length > 0) {
      status = 1;
      console.error(`${path}: ${refs.length} off-origin reference(s) (AC-R1):`);
      for (const ref of refs) console.error(`  ${ref}`);
    } else {
      console.log(`${path}: self-contained (AC-R1 ok)`);
    }
  }
  return status;
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  process.exitCode = main(process.argv.slice(2));
}
