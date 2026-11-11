import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
    include: ["packages/**/*.test.ts", "apps/**/*.test.ts", "test/**/*.test.ts"],
    exclude: ["**/node_modules/**", "**/e2e/**"],
    // Verovio's WASM instantiation takes a moment on a cold worker.
    testTimeout: 30_000,
  },
});
