import { renameSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, type Plugin } from "vite";
import { viteSingleFile } from "vite-plugin-singlefile";
// @ts-expect-error -- plain .mjs without type declarations
import { APPS } from "./apps.config.mjs";
// @ts-expect-error -- plain .mjs without type declarations
import { requireApp } from "./scripts/lib/apps.mjs";

// One page per build: `APP=<name> vite build`, or `npm run build [-- <name>...]` (scripts/build.mjs).
const app: string = requireApp(APPS, process.env.APP);

// Vite names the page after its source (index.html); servers look it up by app name.
function nameOutput(fileName: string): Plugin {
  return {
    name: "name-output",
    enforce: "post",
    // Rolldown ignores renames inside the bundle object, so rename the written file.
    writeBundle(options) {
      const dir = options.dir ?? "";
      renameSync(join(dir, "index.html"), join(dir, fileName));
    },
  };
}

export default defineConfig({
  root: fileURLToPath(new URL(`./apps/${app}`, import.meta.url)),
  base: "./",
  build: {
    outDir: fileURLToPath(new URL("./dist", import.meta.url)),
    // scripts/build.mjs empties dist/ once; each app's build must keep the others' pages.
    emptyOutDir: false,
    target: "es2022",
    // The page is one file by design (AC-R1); Verovio alone is several MB.
    chunkSizeWarningLimit: 20_000,
    reportCompressedSize: false,
  },
  plugins: [viteSingleFile({ removeViteModuleLoader: true }), nameOutput(`${app}.html`)],
});
