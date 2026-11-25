import { expect, test } from "@playwright/test";
import { SIZES, ScoreViewerFrame } from "../../../test/e2e/view-frame.ts";

// T4.1 (docs/research/mcp-apps-improvement-plan.md): the Score Viewer's chrome follows the Kannel
// design system (docs/design/design-system.md): the tricolor bar (§7), the focus ring (§9) and
// 40 px touch targets on every control (§5).

const NARROW = SIZES[1]!;

test("the tricolor bar is the 3 px top edge: flag blue, black, white, top to bottom (§7)", async ({ page }) => {
  const view = await ScoreViewerFrame.open(page, {}, NARROW);
  await expect(view.scorePage()).toBeVisible();
  const bar = view.content.locator(".tricolor");
  await expect(bar).toHaveCount(1);
  await expect(bar).toHaveAttribute("aria-hidden", "true");
  const box = await bar.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.height).toBe(3);
  expect(box!.y).toBe((await view.content.locator("body").boundingBox())!.y);
  expect(box!.width).toBeGreaterThanOrEqual(NARROW.width! - 1);

  // The three bands, read as the painted gradient's stops in order.
  const image = await bar.evaluate((el) => getComputedStyle(el).backgroundImage);
  const colors = [...image.matchAll(/rgb\(\d+, \d+, \d+\)/g)].map((match) => match[0]);
  // A hard stop repeats its color at both ends of the band.
  const bands = colors.filter((color, index) => color !== colors[index - 1]);
  expect(bands).toEqual(["rgb(0, 114, 206)", "rgb(21, 23, 28)", "rgb(255, 255, 255)"]);
});

test("the white band follows the theme so it never glares on a dark host", async ({ page }) => {
  await ScoreViewerFrame.open(page, { theme: "dark" });
  const bar = page.frameLocator("iframe").locator(".tricolor");
  const image = await bar.evaluate((el) => getComputedStyle(el).backgroundImage);
  expect(image).toContain("rgb(16, 18, 23)");
});

test("every control shows the 2 px ring in the ring token when focused (§9)", async ({ page }) => {
  const view = await ScoreViewerFrame.open(page, { modes: "inline,fullscreen" });
  await expect(view.scorePage()).toBeVisible();
  const stops = await view.tabThrough();
  expect(stops.length).toBeGreaterThanOrEqual(4);
  for (const stop of stops) expect(stop.ringVisible, `ring on ${stop.name}`).toBe(true);

  const ring = await view.content.locator("#zoom-in").evaluate((el) => {
    (el as HTMLElement).focus();
    const style = getComputedStyle(el);
    return {
      width: style.outlineWidth,
      offset: style.outlineOffset,
      color: style.outlineColor,
      token: getComputedStyle(document.documentElement).getPropertyValue("--color-ring-primary").trim(),
    };
  });
  expect(ring.width).toBe("2px");
  expect(ring.offset).toBe("1px");
  expect(ring.token).toBe("#0072ce");
  expect(ring.color).toBe("rgb(0, 114, 206)");
});

test("every control is at least 40 x 40 px at 360 px, fallback buttons included", async ({ page }) => {
  const view = await ScoreViewerFrame.open(page, { modes: "inline,fullscreen" }, NARROW);
  await expect(view.scorePage()).toBeVisible();
  await view.click("Download SVG");
  await expect(view.downloadFallback()).toBeVisible();

  const sizes = await view.content.locator("button:visible, select:visible").evaluateAll((buttons) =>
    buttons.map((button) => {
      const { width, height } = button.getBoundingClientRect();
      return { name: button.getAttribute("aria-label") ?? button.textContent?.trim() ?? "", width, height };
    }),
  );
  expect(sizes.length).toBeGreaterThanOrEqual(6);
  for (const size of sizes) {
    expect(size.height, `${size.name} height`).toBeGreaterThanOrEqual(40);
    expect(size.width, `${size.name} width`).toBeGreaterThanOrEqual(40);
  }
  expect(await view.scrollsSideways()).toBe(false);
});
