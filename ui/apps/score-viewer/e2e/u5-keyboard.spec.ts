import { expect, test, type Page } from "@playwright/test";
import { messages, pageLabel } from "../../../test/e2e/host-helpers.ts";
import { ScoreViewerFrame } from "../../../test/e2e/view-frame.ts";

// U5 (docs/research/ui-and-sound-testing-plan.md): Next, Prev, zoom and the other controls are
// reachable by Tab with a visible focus ring, and Enter or Space activates them. The viewer has
// no page-jump field; the arrow and Page keys move pages instead.

async function openOnPage2(page: Page): Promise<ScoreViewerFrame> {
  const view = await ScoreViewerFrame.open(page, { modes: "inline,fullscreen" });
  await expect(view.scorePage()).toBeVisible();
  await view.click("Next page");
  await expect(view.pageLabel()).toHaveText(/^Page 2 \//);
  return view;
}

test("U5 Tab reaches Prev, Next, zoom, Download and Fullscreen in order, each with a visible focus ring", async ({ page }) => {
  const view = await openOnPage2(page);

  const stops = await view.tabThrough();
  expect(stops.map((stop) => stop.name)).toEqual(["Previous page", "Next page", "Zoom out", "Zoom in", "Download SVG", "Fullscreen"]);
  for (const stop of stops) expect(stop, `focus ring on ${stop.name}`).toMatchObject({ ringVisible: true });
});

test("U5 Enter on Next and Space on Prev change the page", async ({ page }) => {
  const view = await openOnPage2(page);

  await view.tabTo("Next page");
  await view.press("Enter");
  await expect(view.pageLabel()).toHaveText(/^Page 3 \//);
  await view.tabTo("Previous page");
  await view.press("Space");
  await expect(view.pageLabel()).toHaveText(/^Page 2 \//);
});

test("U5 Enter on Zoom in and Space on Zoom out change the zoom", async ({ page }) => {
  const view = await openOnPage2(page);

  await view.tabTo("Zoom in");
  await view.press("Enter");
  await expect(view.zoomLabel()).toHaveText("125%");
  await view.tabTo("Zoom out");
  await view.press("Space");
  await expect(view.zoomLabel()).toHaveText("100%");
});

test("U5 Enter on Fullscreen asks the host for fullscreen, and Space leaves it", async ({ page }) => {
  const view = await openOnPage2(page);

  await view.tabTo("Fullscreen");
  await view.press("Enter");
  await expect(view.button("Exit fullscreen")).toBeVisible();
  expect((await messages(page, "ui/request-display-mode"))[0]!.params).toEqual({ mode: "fullscreen" });
  await view.tabTo("Exit fullscreen");
  await view.press("Space");
  await expect(view.button("Fullscreen")).toBeVisible();
  expect((await messages(page, "ui/request-display-mode")).at(-1)!.params).toEqual({ mode: "inline" });
});

test("U5 Enter on Download SVG saves the visible page", async ({ page }) => {
  const view = await openOnPage2(page);

  await view.tabTo("Download SVG");
  const [download] = await Promise.all([page.waitForEvent("download"), view.press("Enter")]);
  expect(download.suggestedFilename()).toBe("score-page-2.svg");
});

test("U5 when Next reaches the last page, focus moves to Prev instead of being lost", async ({ page }) => {
  const view = await openOnPage2(page);
  const { count } = await pageLabel(view.content);

  await view.tabTo("Next page");
  for (let shown = 2; shown < count; shown++) {
    await view.press("Enter");
    await expect(view.pageLabel()).toHaveText(`Page ${shown + 1} / ${count}`);
  }
  await expect(view.button("Next page")).toBeDisabled();
  expect(await view.focused()).toEqual({ name: "Previous page", ringVisible: true });

  // And back again: Prev at page 1 hands focus to Next.
  for (let shown = count; shown > 1; shown--) await view.press("Enter");
  await expect(view.pageLabel()).toHaveText(`Page 1 / ${count}`);
  expect(await view.focused()).toEqual({ name: "Next page", ringVisible: true });
});

test("U5 the arrow and Page keys move pages (no page-jump field)", async ({ page }) => {
  const view = await openOnPage2(page);

  await view.tabTo("Zoom in");
  await view.press("ArrowRight");
  await expect(view.pageLabel()).toHaveText(/^Page 3 \//);
  await view.press("PageUp");
  await expect(view.pageLabel()).toHaveText(/^Page 2 \//);
  await view.press("ArrowLeft");
  await expect(view.pageLabel()).toHaveText(/^Page 1 \//);
  await view.press("PageDown");
  await expect(view.pageLabel()).toHaveText(/^Page 2 \//);
});
