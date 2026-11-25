import { readFileSync } from "node:fs";
import { expect, test } from "../../../test/e2e/host-fixture.ts";
import { messages, openHost, pageLabel } from "../../../test/e2e/host-helpers.ts";
import { ScoreViewerFrame } from "../../../test/e2e/view-frame.ts";

// T4.3 (docs/research/mcp-apps-improvement-plan.md, C6b): a part filter re-renders only the chosen
// part, and a highlight dims the others. Both work on either render path, because the page cuts the
// MusicXML itself (ui/packages/kit/src/score/parts.ts) before it goes to Verovio or to the server.

// The staves of the first measure of the first system: one per part drawn.
const FIRST_MEASURE_STAVES = "#score svg g.system >> nth=0 >> g.measure >> nth=0 >> g.staff";

test("the part choices list the score's parts, all shown and none highlighted", async ({ page }) => {
  const view = await ScoreViewerFrame.open(page);
  await expect(view.scorePage()).toBeVisible();
  await expect(view.content.locator("#part-filter")).toHaveValue("");
  await expect(view.content.locator("#part-filter option")).toHaveText(["All parts", "Soprano", "Alto", "Tenor", "Bass"]);
  await expect(view.content.locator("#part-highlight option")).toHaveText(["No highlight", "Soprano", "Alto", "Tenor", "Bass"]);
  await expect(view.content.locator(FIRST_MEASURE_STAVES)).toHaveCount(4);
});

test("filtering to one part draws only its staff, and paging still stops at both ends (AC-R3)", async ({ page }) => {
  const view = await ScoreViewerFrame.open(page);
  await expect(view.scorePage()).toBeVisible();
  await view.content.locator("#part-filter").selectOption({ label: "Alto" });

  await expect(view.content.locator(FIRST_MEASURE_STAVES)).toHaveCount(1);
  await expect(view.content.locator("#status")).toHaveText("Showing Alto only");
  await expect(view.content.locator("#part-highlight option")).toHaveText(["No highlight", "Alto"]);

  const { count } = await pageLabel(view.content);
  expect(count).toBeGreaterThanOrEqual(1);
  const next = view.content.locator("#next");
  const prev = view.content.locator("#prev");
  await expect(prev).toBeDisabled();
  for (let i = 1; i < count; i++) await next.click();
  await expect(view.pageLabel()).toHaveText(`Page ${count} / ${count}`);
  await expect(next).toBeDisabled();
  for (let i = 1; i < count; i++) await prev.click();
  await expect(view.pageLabel()).toHaveText(`Page 1 / ${count}`);

  await view.content.locator("#part-filter").selectOption({ label: "All parts" });
  await expect(view.content.locator(FIRST_MEASURE_STAVES)).toHaveCount(4);
  await expect(view.content.locator("#status")).toHaveText("Showing all parts");
});

test("highlighting a part dims the other staves and labels, and keeps doing so on the next page", async ({ page }) => {
  const view = await ScoreViewerFrame.open(page);
  await expect(view.scorePage()).toBeVisible();
  await view.content.locator("#part-highlight").selectOption({ label: "Alto" });

  const staves = view.content.locator(FIRST_MEASURE_STAVES);
  await expect(staves.nth(1)).not.toHaveClass(/dimmed/);
  for (const index of [0, 2, 3]) await expect(staves.nth(index)).toHaveClass(/dimmed/);
  await expect(staves.nth(0)).toHaveCSS("opacity", "0.25");
  await expect(staves.nth(1)).toHaveCSS("opacity", "1");
  await expect(view.content.locator("#score svg .system > g.label.dimmed").first()).toBeAttached();
  await expect(view.content.locator("#status")).toHaveText("Highlighting Alto");

  await view.click("Next page");
  await expect(view.pageLabel()).toHaveText(/^Page 2 \//);
  await expect(staves.nth(0)).toHaveClass(/dimmed/);
  await expect(staves.nth(1)).not.toHaveClass(/dimmed/);

  await view.content.locator("#part-highlight").selectOption({ label: "No highlight" });
  await expect(view.content.locator("#score svg .dimmed")).toHaveCount(0);
});

test("the model hears the highlighted part's ID, never its name", async ({ page }) => {
  const view = await ScoreViewerFrame.open(page);
  await expect(view.scorePage()).toBeVisible();
  await view.content.locator("#part-highlight").selectOption({ label: "Alto" });
  await expect
    .poll(async () => JSON.stringify((await messages(page, "ui/update-model-context")).at(-1)?.params))
    .toContain("Highlighted part ID: P2");
  expect(JSON.stringify((await messages(page, "ui/update-model-context")).at(-1)?.params)).not.toContain("Alto");
});

test("the PDF is made from the part that is shown", async ({ page }) => {
  const view = await ScoreViewerFrame.open(page);
  await expect(view.scorePage()).toBeVisible();
  await view.content.locator("#part-filter").selectOption({ label: "Tenor" });
  await expect(view.content.locator(FIRST_MEASURE_STAVES)).toHaveCount(1);
  const [download] = await Promise.all([page.waitForEvent("download"), view.click("Download PDF")]);
  expect(readFileSync(await download.path()).toString("latin1")).toContain("%mock-parts:1");
});

test("on the server render path the filtered score is what render_page_svg receives", async ({ page }) => {
  const view = await ScoreViewerFrame.open(page, { csp: "spec" });
  await expect(view.scorePage()).toHaveAttribute("data-server-page", "1");
  await view.content.locator("#part-filter").selectOption({ label: "Bass" });
  await expect(view.content.locator("#status")).toHaveText("Showing Bass only");
  await expect
    .poll(async () => {
      const calls = (await messages(page, "tools/call")).filter((call) => call.params!.name === "render_page_svg");
      const xml = (calls.at(-1)!.params!.arguments as { musicxml: string }).musicxml;
      return [xml.match(/<score-part /g)?.length, xml.includes("Bass"), xml.includes("Soprano")];
    })
    .toEqual([1, true, false]);
});

test("X1 keyboard: Tab reaches both selects with a ring, and arrow keys change the choice", async ({ page }) => {
  const view = await ScoreViewerFrame.open(page);
  await expect(view.scorePage()).toBeVisible();
  await view.tabTo("Show parts");
  expect((await view.focused()).ringVisible).toBe(true);
  await view.press("ArrowDown");
  await expect(view.content.locator("#part-filter")).toHaveValue("P1");
  await expect(view.content.locator(FIRST_MEASURE_STAVES)).toHaveCount(1);
  await view.press("Tab");
  expect(await view.focused()).toEqual({ name: "Highlight part", ringVisible: true });
  await view.press("ArrowDown");
  await expect(view.content.locator("#part-highlight")).toHaveValue("P1");
  // Focus stays on the select the user is working in.
  expect((await view.focused()).name).toBe("Highlight part");
});

test("X1 reduced motion: the dimming does not fade", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  const view = await ScoreViewerFrame.open(page);
  await expect(view.scorePage()).toBeVisible();
  await expect(view.content.locator(FIRST_MEASURE_STAVES).first()).toHaveCSS("transition-duration", "0s");
});

test("without reduced motion the dimming fades in 120 ms", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
  const view = await ScoreViewerFrame.open(page);
  await expect(view.scorePage()).toBeVisible();
  await expect(view.content.locator(FIRST_MEASURE_STAVES).first()).toHaveCSS("transition-duration", "0.12s");
});

test("a one-part score offers no part choice", async ({ page }) => {
  const view = await ScoreViewerFrame.open(page, { scenario: "path-only" });
  await expect(view.notice()).toBeVisible();
  await expect(view.content.locator("#parts")).toBeHidden();
});

test("the real render-mcp pages the filtered score and the highlight dims the real staves", async ({ page, renderMcp }) => {
  const frame = await openHost(page, { scenario: "inline-satb", csp: "spec", server: "real" });
  await expect(frame.locator("#score svg .staff").first()).toBeVisible();
  await expect(frame.locator(FIRST_MEASURE_STAVES)).toHaveCount(4);

  await frame.locator("#part-filter").selectOption({ label: "Tenor" });
  await expect(frame.locator(FIRST_MEASURE_STAVES)).toHaveCount(1);
  await expect(frame.locator("#page-label")).toHaveText(/^Page 1 \/ \d+$/);

  await frame.locator("#part-filter").selectOption({ label: "All parts" });
  await expect(frame.locator(FIRST_MEASURE_STAVES)).toHaveCount(4);
  await frame.locator("#part-highlight").selectOption({ label: "Bass" });
  await expect(frame.locator(`${FIRST_MEASURE_STAVES}.dimmed`)).toHaveCount(3);
  expect(renderMcp.calls.filter((call) => call.name === "render_page_svg").length).toBeGreaterThanOrEqual(3);
});
