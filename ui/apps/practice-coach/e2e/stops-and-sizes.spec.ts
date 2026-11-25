import { expect, test } from "@playwright/test";
import { CoachFrame, type CoachControl } from "../../../test/e2e/coach-frame.ts";
import type { Size } from "../../../test/e2e/view-frame.ts";

// U8 for the Practice Coach: every stop at desktop and phone width, in the default host and in
// Claude light and dark (the recorded Claude Desktop variables). At each stop axe finds nothing in
// the chrome (the SVG notation is excluded, R4), every Tab stop shows its focus ring, and nothing
// scrolls sideways. The theme contrast of the page's own colors is measured here by axe too.

const SIZES: Size[] = [
  { name: "1280 px", width: 1280, viewport: { width: 1360, height: 900 } },
  { name: "360 px", width: 360, viewport: { width: 1280, height: 900 } },
];

const HOSTS: { name: string; query: Record<string, string> }[] = [
  { name: "default host", query: {} },
  { name: "Claude light", query: { host: "claude", theme: "light" } },
  { name: "Claude dark", query: { host: "claude", theme: "dark" } },
];

interface Stop {
  name: string;
  query: Record<string, string>;
  reach(coach: CoachFrame): Promise<void>;
  /** The page's own Tab order at the stop. */
  tabOrder: CoachControl[];
}

const STOPS: Stop[] = [
  {
    name: "listening",
    query: {},
    reach: async (coach) => {
      await coach.ready();
      await expect(coach.status()).toHaveAttribute("data-status", /.+/);
    },
    tabOrder: ["Stop and see summary", "Server microphone"],
  },
  {
    name: "ready (microphone closed)",
    query: { scenario: "coach-loaded" },
    reach: async (coach) => {
      await coach.ready();
      await expect(coach.button("Start listening")).toBeEnabled();
    },
    tabOrder: ["Start listening", "Stop and see summary", "Server microphone"],
  },
  {
    name: "report",
    query: {},
    reach: async (coach) => {
      await coach.ready();
      await expect.poll(() => coach.callCount("get_current_position")).toBeGreaterThan(8);
      await coach.button("Stop and see summary").click();
      await expect(coach.report()).toBeVisible();
    },
    tabOrder: ["Server microphone", "Practice again"],
  },
  {
    name: "empty",
    query: { scenario: "coach-empty" },
    reach: async (coach) => void (await expect(coach.empty()).toBeVisible()),
    tabOrder: ["Server microphone"],
  },
  {
    name: "error",
    query: { scenario: "coach-error" },
    reach: async (coach) => void (await expect(coach.notice()).toContainText("PROCESSING_FAILED")),
    tabOrder: ["Server microphone"],
  },
  {
    name: "server lost",
    query: { take: "lost" },
    reach: async (coach) => void (await expect(coach.notice()).toContainText("Lost contact", { timeout: 10_000 })),
    tabOrder: ["Stop and see summary", "Server microphone"],
  },
];

for (const host of HOSTS) {
  for (const size of SIZES) {
    for (const stop of STOPS) {
      test(`U8 ${stop.name} at ${size.name}, ${host.name}: axe clean, Tab order with a ring, no sideways scroll`, async ({ page }) => {
        const coach = await CoachFrame.open(page, { ...host.query, ...stop.query }, size);
        await stop.reach(coach);
        expect(await coach.width(), "the frame really is this narrow").toBeLessThanOrEqual(size.width!);
        expect(await coach.scrollsSideways(), "sideways scroll").toBe(false);
        expect(await coach.axeViolations()).toEqual([]);
        const stops = await coach.tabThrough();
        expect(stops.map((s) => s.name)).toEqual(stop.tabOrder);
        for (const focus of stops) expect(focus.ringVisible, `${focus.name} shows a focus ring`).toBe(true);
      });
    }
  }
}

for (const theme of ["light", "dark"] as const) {
  test(`U3 Claude ${theme}: the page paints the recorded background and text colors`, async ({ page }) => {
    const coach = await CoachFrame.open(page, { host: "claude", theme });
    await coach.ready();
    const body = coach.content.locator("body");
    await expect(body).toHaveCSS("background-color", theme === "light" ? "rgb(255, 255, 255)" : "rgb(48, 48, 46)");
    await expect(body).toHaveCSS("color", theme === "light" ? "rgb(20, 20, 19)" : "rgb(250, 249, 245)");
    await expect(coach.content.locator("html")).toHaveAttribute("data-theme", theme);
  });
}

test("U3 Claude: a host theme change repaints the status colors too", async ({ page }) => {
  const coach = await CoachFrame.open(page, { host: "claude", theme: "light" });
  await coach.ready();
  const pill = coach.content.locator("#listen-badge");
  await expect(pill).toHaveCSS("background-color", "rgb(228, 242, 232)"); // --kannel-success-tint, light
  await page.evaluate(() => (window as unknown as { __host: { setTheme(name: "dark"): void } }).__host.setTheme("dark"));
  await expect(pill).toHaveCSS("background-color", "rgb(23, 48, 31)"); // dark
});
