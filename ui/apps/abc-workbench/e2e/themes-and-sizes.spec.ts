import { expect, test, type Page } from "@playwright/test";
import { AbcWorkbenchFrame, SIZES } from "../../../test/e2e/abc-frame.ts";
import { ABC_ORIGINAL } from "../../../test/mock-host/abc-tools.ts";

// U3/U4 for the ABC Workbench: the recorded Claude Desktop variables in light and dark, desktop and
// 360 px, with axe (color contrast included) on every state, a visible focus ring on every Tab
// stop, and no sideways scroll.

const HOSTS: { name: string; query: Record<string, string> }[] = [
  { name: "default host", query: {} },
  { name: "Claude light", query: { host: "claude", theme: "light" } },
  { name: "Claude dark", query: { host: "claude", theme: "dark" } },
];

interface Stop {
  name: string;
  query: Record<string, string>;
  reach(view: AbcWorkbenchFrame): Promise<void>;
}

const STOPS: Stop[] = [
  {
    name: "render",
    query: {},
    reach: async (view) => {
      await expect(view.validation()).toHaveText("Valid ABC");
    },
  },
  {
    name: "full text",
    query: {},
    reach: async (view) => {
      await view.button("Full text").click();
      await expect(view.validation()).toHaveText("Valid ABC");
    },
  },
  {
    name: "empty",
    query: { scenario: "abc-export" },
    reach: async (view) => {
      await expect(view.content.locator(".empty")).toBeVisible();
    },
  },
  {
    name: "error",
    query: { scenario: "abc-error" },
    reach: async (view) => {
      await expect(view.notice()).toBeVisible();
    },
  },
  {
    name: "edit with an error marker",
    query: { scenario: "abc-export" },
    reach: async (view) => {
      await view.button("Edit").click();
      await view.editor().fill(ABC_ORIGINAL.replace("G4 z4 |", "G?4 z4 |"));
      await expect(view.gutterLine(7, true)).toBeVisible();
    },
  },
  {
    name: "accepted with a file chip",
    query: { scenario: "abc-edit-file" },
    reach: async (view) => {
      await view.button("Accept all").click();
      await expect(view.fileChip()).toBeVisible();
    },
  },
];

async function open(page: Page, query: Record<string, string>, width: number): Promise<AbcWorkbenchFrame> {
  return AbcWorkbenchFrame.open(page, query, width);
}

for (const size of SIZES) {
  for (const host of HOSTS) {
    for (const stop of STOPS) {
      test(`${stop.name} at ${size.name} in ${host.name}: axe clean, a focus ring on every Tab stop, no sideways scroll`, async ({ page }) => {
        const view = await open(page, { ...host.query, ...stop.query }, size.width);
        await stop.reach(view);

        expect(await view.axeViolations()).toEqual([]);
        expect(await view.scrollsSideways()).toBe(false);
        expect(await view.width()).toBeLessThanOrEqual(size.width);
        const stops = await view.tabThrough();
        expect(stops.length).toBeGreaterThan(3);
        for (const tabStop of stops) expect(tabStop, `focus ring on ${tabStop.name}`).toMatchObject({ ringVisible: true });
      });
    }
  }
}

for (const theme of ["light", "dark"] as const) {
  test(`Claude ${theme}: the page paints the recorded background and sets data-theme`, async ({ page }) => {
    const view = await AbcWorkbenchFrame.open(page, { host: "claude", theme });
    await expect(view.content.locator("body")).toHaveCSS("background-color", theme === "light" ? "rgb(255, 255, 255)" : "rgb(48, 48, 46)");
    await expect(view.content.locator("html")).toHaveAttribute("data-theme", theme);
  });
}

test("X1 reduced motion: no transition runs", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  const view = await AbcWorkbenchFrame.open(page);
  await expect(view.hunks().first().locator(".col.add")).toHaveCSS("transition-duration", "0s");
});
