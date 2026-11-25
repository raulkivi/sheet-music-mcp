#!/usr/bin/env node
// Prints `pages=true|false`: whether the named server serves a page in apps.config.mjs.
// Usage: node scripts/has-pages.mjs <server>   (the release workflow appends this to $GITHUB_OUTPUT)

import { APPS } from "../apps.config.mjs";
import { serversWithPages } from "./lib/apps.mjs";

console.log(`pages=${serversWithPages(APPS).includes(process.argv[2] ?? "")}`);
