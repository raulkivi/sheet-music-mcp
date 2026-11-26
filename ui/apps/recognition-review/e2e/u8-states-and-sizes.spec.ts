import { expect, test } from "@playwright/test";
import { ReviewFrame, SIZES } from "./review-frame.ts";

// U8: the Recognition Review's stops at 1280 px and 360 px, in the default host and in Claude
// light and dark (the recorded variables, so axe measures real contrast): axe finds nothing in
// the chrome (the notation is excluded, R4), every Tab stop shows its ring, nothing scrolls
// sideways. Then keyboard use (X1).

const HOSTS: { name: string; query: Record<string, string> }[] = [
  { name: "default host", query: {} },
  { name: "Claude light", query: { host: "claude", theme: "light" } },
  { name: "Claude dark", query: { host: "claude", theme: "dark" } },
];

const STOPS: { name: string; query: Record<string, string>; reach(view: ReviewFrame): Promise<void> }[] = [
  { name: "warnings", query: {}, reach: (view) => view.drawn() },
  {
    name: "bar 3 selected",
    query: {},
    reach: async (view) => {
      await view.drawn();
      await view.issue(/Measure 3 has no notes/).click();
      await expect(view.highlight()).toHaveCount(1);
    },
  },
  { name: "clean", query: { scenario: "review-clean" }, reach: (view) => view.drawn() },
  {
    name: "re-run done",
    query: {},
    reach: async (view) => {
      await view.drawn();
      await view.button("Recognize again with Audiveris").click();
      await expect(view.status()).toHaveText(/^Recognized again/);
    },
  },
  {
    name: "accepted",
    query: {},
    reach: async (view) => {
      await view.drawn();
      await view.button("Accept score").click();
      await expect(view.button("Accepted")).toBeVisible();
    },
  },
  {
    name: "failed recognition",
    query: { scenario: "review-error" },
    reach: async (view) => void (await expect(view.notices()).toBeVisible()),
  },
];

for (const host of HOSTS) {
  for (const size of SIZES) {
    for (const stop of STOPS) {
      test(`U8 ${host.name}, ${size.name}: ${stop.name}: axe clean, focus ring on Tab, no sideways scroll`, async ({ page }) => {
        const view = await ReviewFrame.open(page, { ...stop.query, ...host.query }, size);
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

test("U8 Tab order: the actions, one stop in the list, then the photo and the score", async ({ page }) => {
  const view = await ReviewFrame.open(page);
  await view.drawn();

  const names = (await view.tabThrough()).map((stop) => stop.name);

  expect(names).toEqual([
    "Recognize again with Audiveris",
    "Accept score",
    expect.stringMatching(/^Check Image is 150 DPI/),
    "Photo of the page",
    "Recognized score",
  ]);
});

test("U8 at 360 px the photo and the score are stacked, photo above", async ({ page }) => {
  const view = await ReviewFrame.open(page, {}, SIZES[1]);
  await view.drawn();

  const photo = await view.photoPane().boundingBox();
  const score = await view.score().boundingBox();

  expect(score!.y).toBeGreaterThanOrEqual(photo!.y + photo!.height);
  expect(Math.abs(score!.x - photo!.x)).toBeLessThan(2);
});

test("U8 at 1280 px the photo and the score are side by side", async ({ page }) => {
  const view = await ReviewFrame.open(page, {}, SIZES[0]);
  await view.drawn();

  const photo = await view.photoPane().boundingBox();
  const score = await view.score().boundingBox();

  expect(score!.x).toBeGreaterThanOrEqual(photo!.x + photo!.width);
  expect(Math.abs(score!.y - photo!.y)).toBeLessThan(2);
});

test.describe("X1 keyboard", () => {
  test("arrow keys move through the issues, Home and End jump, Enter selects and announces", async ({ page }) => {
    const view = await ReviewFrame.open(page);
    await view.drawn();
    await view.issues().first().focus();

    await view.press("ArrowDown");
    expect((await view.focused()).name).toMatch(/^Check Measure 3/);
    await view.press("End");
    expect((await view.focused()).name).toMatch(/^Note 1 part recognized/);
    await view.press("ArrowUp");
    await view.press("Home");
    expect((await view.focused()).name).toMatch(/^Check Image is 150 DPI/);
    await view.press("ArrowDown");
    await view.press("Enter");

    await expect(view.selection()).toHaveText(/^Issue 2 of 3\. Check: Measure 3.*Showing bar 3 in the score\.$/);
    await expect(view.highlight()).toHaveCount(1);
    await expect(view.selection()).toHaveAttribute("aria-live", "polite");
  });

  test("Space presses Accept and focus stays on it", async ({ page }) => {
    const view = await ReviewFrame.open(page);
    await view.drawn();
    await view.button("Accept score").focus();

    await view.press("Space");

    await expect(view.status()).toHaveText(/^Score accepted/);
    expect((await view.focused()).name).toBe("Accepted");
  });
});
