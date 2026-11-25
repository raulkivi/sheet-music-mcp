import { expect, test } from "@playwright/test";
import { DiffViewerFrame, SIZES } from "./diff-frame.ts";

// U8: the Diff Viewer's stops at 1280 px and 360 px, in the default host and in Claude light and
// dark (the recorded variables, so axe measures real contrast): axe finds nothing in the chrome
// (the notation is excluded, R4), every Tab stop shows its ring, nothing scrolls sideways.
// Then keyboard use (X1): list navigation, filters, the live selection summary.

const HOSTS: { name: string; query: Record<string, string> }[] = [
  { name: "default host", query: {} },
  { name: "Claude light", query: { host: "claude", theme: "light" } },
  { name: "Claude dark", query: { host: "claude", theme: "dark" } },
];

const STOPS: { name: string; query: Record<string, string>; reach(view: DiffViewerFrame): Promise<void> }[] = [
  { name: "first view", query: {}, reach: (view) => view.scoresDrawn() },
  {
    name: "bar 19 selected",
    query: {},
    reach: async (view) => {
      await view.scoresDrawn();
      await view.change(/Soprano, bar 19/).click();
      await expect(view.highlight("target")).toHaveCount(1);
    },
  },
  {
    name: "report",
    query: {},
    reach: async (view) => {
      await view.scoresDrawn();
      await view.tab("Report").click();
      await expect(view.report()).toBeVisible();
    },
  },
  {
    name: "identical scores",
    query: { scenario: "diff-identical" },
    reach: async (view) => void (await expect(view.notice()).toBeVisible()),
  },
  {
    name: "failed comparison",
    query: { scenario: "diff-error" },
    reach: async (view) => void (await expect(view.notice()).toBeVisible()),
  },
];

for (const host of HOSTS) {
  for (const size of SIZES) {
    for (const stop of STOPS) {
      test(`U8 ${host.name}, ${size.name}: ${stop.name}: axe clean, focus ring on Tab, no sideways scroll`, async ({ page }) => {
        const view = await DiffViewerFrame.open(page, { ...stop.query, ...host.query }, size);
        await stop.reach(view);

        expect(await view.width()).toBeLessThanOrEqual(size.width);
        expect(await view.scrollsSideways()).toBe(false);
        expect(await view.axeViolations()).toEqual([]);
        const stops = await view.tabThrough();
        expect(stops.length).toBeGreaterThan(0);
        for (const tabStop of stops) expect(tabStop, `focus ring on ${tabStop.name}`).toMatchObject({ ringVisible: true });
      });
    }
  }
}

test("U8 Tab order: tabs, actions, kinds, one stop in the list, then each score pane", async ({ page }) => {
  const view = await DiffViewerFrame.open(page);
  await view.scoresDrawn();

  const names = (await view.tabThrough()).map((stop) => stop.name);

  expect(names).toEqual([
    "Scores",
    "Save annotated scores",
    "Open in Score Viewer",
    "Pitch changed (3)",
    "Removed (1)",
    expect.stringMatching(/^Alto, bar 7/),
    "Reference score",
    "Target score",
  ]);
});

test("U8 at 360 px the two scores are stacked, reference above target", async ({ page }) => {
  const view = await DiffViewerFrame.open(page, {}, SIZES[1]);
  await view.scoresDrawn();

  const reference = await view.pane("reference").boundingBox();
  const target = await view.pane("target").boundingBox();

  expect(target!.y).toBeGreaterThanOrEqual(reference!.y + reference!.height);
  expect(Math.abs(target!.x - reference!.x)).toBeLessThan(2);
});

test("U8 at 1280 px the two scores are side by side", async ({ page }) => {
  const view = await DiffViewerFrame.open(page, {}, SIZES[0]);
  await view.scoresDrawn();

  const reference = await view.pane("reference").boundingBox();
  const target = await view.pane("target").boundingBox();

  expect(target!.x).toBeGreaterThanOrEqual(reference!.x + reference!.width);
  expect(Math.abs(target!.y - reference!.y)).toBeLessThan(2);
});

test.describe("X1 keyboard", () => {
  test("arrow keys move through the list, Home and End jump, Enter selects and announces", async ({ page }) => {
    const view = await DiffViewerFrame.open(page);
    await view.scoresDrawn();
    await view.change(/Alto, bar 7/).focus();

    await view.press("ArrowDown");
    expect((await view.focused()).name).toMatch(/^Bass, bar 12/);
    await view.press("End");
    expect((await view.focused()).name).toMatch(/^Soprano, bar 19|^Tenor, bar 19/);
    await view.press("ArrowUp");
    await view.press("Home");
    expect((await view.focused()).name).toMatch(/^Alto, bar 7/);
    await view.press("ArrowDown");
    await view.press("Enter");

    await expect(view.selection()).toHaveText(/^Change 2 of 4\. Bass, bar 12, beat \d.*Both scores show bar 12\.$/);
    await expect(view.highlight("target")).toHaveCount(1);
    await expect(view.selection()).toHaveAttribute("aria-live", "polite");
  });

  test("Space on a kind toggles it and keeps focus on it", async ({ page }) => {
    const view = await DiffViewerFrame.open(page);
    await view.scoresDrawn();
    await view.filter(/Removed/).focus();

    await view.press("Space");

    await expect(view.changes()).toHaveCount(1);
    expect((await view.focused()).name).toBe("Removed (1)");
  });

  test("arrow keys move between the Scores and Report tabs", async ({ page }) => {
    const view = await DiffViewerFrame.open(page);
    await view.scoresDrawn();
    await view.tab("Scores").focus();

    await view.press("ArrowRight");

    await expect(view.tab("Report")).toHaveAttribute("aria-selected", "true");
    expect((await view.focused()).name).toBe("Report");
  });
});
