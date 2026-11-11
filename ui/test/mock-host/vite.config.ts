import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

// The mock host's page script (host-page.ts and ext-apps' AppBridge) as one ES module,
// dist/host.js, which server.mjs serves at /host.js. Test tooling only: never in dist/.
export default defineConfig({
  logLevel: "warn",
  build: {
    outDir: fileURLToPath(new URL("./dist", import.meta.url)),
    emptyOutDir: true,
    target: "es2022",
    reportCompressedSize: false,
    lib: {
      entry: fileURLToPath(new URL("./host-page.ts", import.meta.url)),
      formats: ["es"],
      fileName: () => "host.js",
    },
  },
});
