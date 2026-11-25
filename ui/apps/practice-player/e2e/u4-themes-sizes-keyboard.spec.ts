import { expect, test, type Frame } from "@playwright/test";
import { axeViolations } from "../../../test/e2e/axe.ts";
import { focusStop } from "../../../test/e2e/focus.ts";
import { frameWidth, scrollsSideways } from "../../../test/e2e/layout.ts";
import { PlayerFrame, SIZES } from "./player-frame.ts";

// U8 (ui/README.md): themes, 360 px and desktop, axe, Tab order with a visible ring, reduced motion.
// The score's SVG notation is not chrome and not markup the page writes (plan R4), so axe skips it.

const NOTATION = "#score > svg";
const BACKGROUND = { light: "rgb(255, 255, 255)", dark: "rgb(48, 48, 46)" } as const;

function appFrame(player: PlayerFrame): Frame {
  const frame = player.page.frames().find((candidate) => candidate !== player.page.mainFrame());
  if (!frame) throw new Error("the app frame is missing");
  return frame;
}

for (const theme of ["light", "dark"] as const) {
  for (const size of SIZES) {
    test(`U3/U4 Claude ${theme}, ${size.name}: painted with the host's colors, axe clean, no sideways scroll`, async ({ page }) => {
      const player = await PlayerFrame.ready(page, { host: "claude", theme }, size);
      const frame = appFrame(player);
      await expect(player.content.locator("body")).toHaveCSS("background-color", BACKGROUND[theme]);
      await expect(player.content.locator("html")).toHaveAttribute("data-theme", theme);
      expect(await axeViolations(frame, { exclude: [NOTATION] })).toEqual([]);
      expect(await scrollsSideways(frame)).toBe(false);
      expect(await frameWidth(frame)).toBeLessThanOrEqual(size.width);
    });
  }
}

test("U4 axe is clean in the states too: playing, the empty state and the error state", async ({ page }) => {
  const player = await PlayerFrame.ready(page);
  await player.button("Play").click();
  await expect(player.button("Pause")).toBeVisible();
  expect(await axeViolations(appFrame(player), { exclude: [NOTATION] })).toEqual([]);

  for (const scenario of ["practice-empty", "practice-unknown-audio"] as const) {
    const other = await PlayerFrame.open(page, { host: "claude", theme: "dark" }, scenario);
    await expect(other.notice()).toBeVisible();
    expect(await axeViolations(appFrame(other), { exclude: [NOTATION] }), scenario).toEqual([]);
  }
});

test("at 360 px every mixer control sits inside the frame", async ({ page }) => {
  const player = await PlayerFrame.ready(page, {}, SIZES[1]);
  for (const control of [player.solo("Bass"), player.mute("Bass"), player.volume("Bass"), player.button("Starting pitches"), player.tempo()]) {
    const box = await control.boundingBox();
    expect(box && box.x >= 0 && box.x + box.width <= SIZES[1]!.width + 1).toBe(true);
  }
});

// X1: keyboard for every control.
test("X1 Tab reaches every control in reading order, each with a visible ring", async ({ page }) => {
  const player = await PlayerFrame.ready(page);
  const frame = appFrame(player);
  await frame.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  await player.content.locator("body").click({ position: { x: 1, y: 1 } });

  const stops: string[] = [];
  for (let i = 0; i < 40; i++) {
    await page.keyboard.press("Tab");
    const stop = await focusStop(frame);
    if (!stop.name) break;
    expect(stop.ringVisible, `ring on ${stop.name}`).toBe(true);
    stops.push(stop.name);
  }
  expect(stops.slice(0, 14)).toEqual([
    "Play",
    "Restart",
    "Speed",
    "Count-in",
    "Loop bars 1 to 4",
    "Sound",
    "Starting pitches",
    "Position",
    "Preset",
    "My part",
    "Solo Soprano",
    "Mute Soprano",
    "Soprano volume",
    "Solo Alto",
  ]);
  expect(stops).toHaveLength(new Set(stops).size);
  expect(stops).toContain("Bass volume");
});

test("X1 Enter and Space press the buttons", async ({ page }) => {
  const player = await PlayerFrame.ready(page);
  await player.loop().focus();
  await page.keyboard.press("Enter");
  await expect(player.loop()).toHaveAttribute("aria-pressed", "false");
  await page.keyboard.press("Space");
  await expect(player.loop()).toHaveAttribute("aria-pressed", "true");
  await player.button("Play").focus();
  await page.keyboard.press("Space");
  await expect(player.button("Pause")).toBeVisible();
});

test("X1 play state, tempo and mixer changes are announced in a polite live region", async ({ page }) => {
  const player = await PlayerFrame.ready(page);
  await expect(player.status()).toHaveAttribute("aria-live", "polite");
  await player.mute("Alto").click();
  await expect(player.status()).toHaveText("Mix updated");
});

test.describe("reduced motion (G20)", () => {
  test("the playhead marks the bar only, and does not move within a bar", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    const player = await PlayerFrame.ready(page);
    await player.seek().evaluate((input: HTMLInputElement) => {
      input.value = "3.5"; // 0.8 s into bar 1, after the 2.7 s count-in
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await expect(player.score()).toHaveAttribute("data-bar", "0");
    await expect(player.content.locator("#score .bar-marker")).toHaveCount(1);
    await expect(player.content.locator("#score .note.playing")).toHaveCount(0);

    await player.button("Play").click();
    for (let i = 0; i < 6; i++) {
      await page.waitForTimeout(150);
      await expect(player.content.locator("#score .note.playing")).toHaveCount(0);
    }
    await player.seek().evaluate((input: HTMLInputElement) => {
      input.value = "8.2"; // bar 3
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await expect(player.score()).toHaveAttribute("data-bar", "2");
  });

  test("with motion allowed, the notes sounding are marked", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "no-preference" });
    const player = await PlayerFrame.ready(page);
    await player.seek().evaluate((input: HTMLInputElement) => {
      input.value = "3.5";
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await expect(player.content.locator("#score .note.playing").first()).toBeVisible();
  });

  test("no element animates or transitions", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    const player = await PlayerFrame.ready(page);
    const durations = await appFrame(player).evaluate(() =>
      [...document.querySelectorAll("button, input, select")].map((element) => getComputedStyle(element).transitionDuration),
    );
    expect(new Set(durations)).toEqual(new Set(["0s"]));
  });
});
