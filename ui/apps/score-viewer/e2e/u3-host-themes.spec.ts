import { expect, test } from "@playwright/test";
import { openHost } from "../../../test/e2e/host-helpers.ts";

// U3 (docs/research/ui-and-sound-testing-plan.md): the mock host sends the recorded Claude Desktop
// theme and style variables through the AppBridge host context, and the view paints them. The
// contrast of those colours is checked in Node (test/theme/theme-contrast.test.ts).

const BACKGROUND = { light: "rgb(255, 255, 255)", dark: "rgb(48, 48, 46)" } as const;

for (const theme of ["light", "dark"] as const) {
  test(`U3 Claude ${theme}: the view paints the recorded background and text colours`, async ({ page }) => {
    const frame = await openHost(page, { host: "claude", theme });
    const body = frame.locator("body");
    await expect(body).toHaveCSS("background-color", BACKGROUND[theme]);
    await expect(body).toHaveCSS("color", theme === "light" ? "rgb(20, 20, 19)" : "rgb(250, 249, 245)");
    await expect(frame.locator("html")).toHaveAttribute("data-theme", theme);
  });
}

test("U3 Claude: a host theme change repaints with the same recorded variables", async ({ page }) => {
  const frame = await openHost(page, { host: "claude", theme: "light" });
  await expect(frame.locator("body")).toHaveCSS("background-color", BACKGROUND.light);
  await page.evaluate(() => (window as unknown as { __host: { setTheme(name: "dark"): void } }).__host.setTheme("dark"));
  await expect(frame.locator("body")).toHaveCSS("background-color", BACKGROUND.dark);
});
