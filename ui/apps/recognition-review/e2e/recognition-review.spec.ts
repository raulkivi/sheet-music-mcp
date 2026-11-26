import { expect, test, type Page } from "@playwright/test";
import { messages } from "../../../test/e2e/host-helpers.ts";
import { ReviewFrame } from "./review-frame.ts";

// U8 (docs/research/ui-and-sound-testing-plan.md): render, clean and error states, AC-O3 (the
// estimate against the detected parts), selecting an issue, the engine re-run and Accept through
// the host's call log. Sizes, themes, axe and Tab order are in u8-states-and-sizes.spec.ts.

const calls = async (page: Page) =>
  (await messages(page, "tools/call")).map((m) => m.params as { name: string; arguments: Record<string, unknown> });
const calledTools = async (page: Page) => (await calls(page)).map((c) => c.name);

test.describe("render", () => {
  test("shows the headline, the warnings as issues, the photo and the recognized score", async ({ page }) => {
    const view = await ReviewFrame.open(page);
    await view.drawn();

    await expect(view.headline()).toHaveText("Recognized with oemer: 1 part, 4 bars. 3 things to check.");
    await expect(view.issues()).toHaveCount(3);
    await expect(view.issue(/Image is 150 DPI/)).toContainText("Check");
    await expect(view.issue(/Measure 3 has no notes/)).toContainText("Bar 3, part P1");
    await expect(view.engine()).toHaveText("oemer");
    // The photo is the server's preview, decoded: a real image, not a broken one.
    expect(await view.photo().evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0);
    await expect(view.photo()).toHaveAttribute("alt", /sheet music page/);
    expect((await calledTools(page)).sort()).toEqual(["get_recognized_score", "get_source_preview"]);
  });

  test("draws the one-part score oemer produced", async ({ page }) => {
    const view = await ReviewFrame.open(page);
    await view.drawn();
    expect(await view.staves().count()).toBe(4);
  });
});

test.describe("AC-O3: staff estimate against the detected parts (G2)", () => {
  test("the page looks like 4 staves and 1 part was found: advice to try Audiveris", async ({ page }) => {
    const view = await ReviewFrame.open(page);
    await view.drawn();

    await expect(view.advice()).toHaveText(
      "Detected 1 part, but the page looks like it has 4 staves per system. Try the Audiveris engine, which keeps SATB voices apart.",
    );
    await expect(view.button("Recognize again with Audiveris")).toBeVisible();
  });

  test("no advice when the parts match the estimate", async ({ page }) => {
    const view = await ReviewFrame.open(page, { scenario: "review-clean" });
    await view.drawn();
    await expect(view.advice()).toBeHidden();
  });
});

test.describe("clean result (G1: no hard-coded issues)", () => {
  test("lists nothing the server did not report", async ({ page }) => {
    const view = await ReviewFrame.open(page, { scenario: "review-clean" });
    await view.drawn();

    await expect(view.headline()).toHaveText("Recognized with Audiveris: 4 parts, 4 bars. Nothing to check.");
    await expect(view.issues()).toHaveCount(0);
    await expect(view.noIssues()).toBeVisible();
    await expect(view.content.locator("#issue-count")).toHaveText("(0)");
    expect(await view.staves().count()).toBeGreaterThanOrEqual(4);
  });
});

test.describe("error", () => {
  test("shows the failure code, no list and nothing to accept", async ({ page }) => {
    const view = await ReviewFrame.open(page, { scenario: "review-error" });

    await expect(view.notices()).toHaveText("The recognition failed (INVALID_INPUT).");
    await expect(view.issues()).toHaveCount(0);
    await expect(view.button("Accept score")).toBeDisabled();
    await expect(view.content.locator("#rerun")).toBeDisabled();
    expect(await calledTools(page)).toEqual([]);
  });
});

test.describe("selecting an issue scrolls the score to its bar", () => {
  test("bar 3 is marked in the score and inside its visible area", async ({ page }) => {
    const view = await ReviewFrame.open(page);
    await view.drawn();
    await expect(view.highlight()).toHaveCount(0);

    await view.issue(/Measure 3 has no notes/).click();

    await expect(view.highlight()).toHaveCount(1);
    const { pane, mark } = await view.boxes();
    expect(mark.top).toBeGreaterThanOrEqual(pane.top - 1);
    expect(mark.bottom).toBeLessThanOrEqual(pane.bottom + 1);
    await expect(view.selection()).toHaveText("Issue 2 of 3. Check: Measure 3 has no notes or rests. Showing bar 3 in the score.");
    await expect(view.issue(/Measure 3 has no notes/)).toHaveAttribute("aria-current", "true");
  });

  test("an issue without a bar says it applies to the whole page and leaves the mark alone", async ({ page }) => {
    const view = await ReviewFrame.open(page);
    await view.drawn();
    await view.issue(/Measure 3 has no notes/).click();

    await view.issue(/Image is 150 DPI/).click();

    await expect(view.selection()).toContainText("This applies to the whole page.");
    await expect(view.highlight()).toHaveCount(1);
  });

  test("scrolls instantly, with or without a reduced-motion preference", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    const view = await ReviewFrame.open(page);
    await view.drawn();
    await view.issue(/Measure 3 has no notes/).click();
    await expect(view.highlight()).toHaveCount(1);
    expect(await view.score().evaluate((el) => getComputedStyle(el).scrollBehavior)).not.toBe("smooth");
  });
});

test.describe("engine switch", () => {
  test("one recognize_sheet call with the same image and the other engine, and the new result is shown", async ({ page }) => {
    const view = await ReviewFrame.open(page);
    await view.drawn();
    expect(await view.staves().count()).toBe(4);

    await view.button("Recognize again with Audiveris").click();

    await expect(view.headline()).toHaveText("Recognized with Audiveris: 4 parts, 4 bars. Nothing to check.");
    await expect(view.status()).toHaveText("Recognized again with Audiveris: 4 parts. Nothing to check.");
    await expect(view.issues()).toHaveCount(0);
    await expect(view.advice()).toBeHidden();
    await expect(view.engine()).toHaveText("Audiveris");
    await expect(view.button("Recognize again with oemer")).toBeVisible();
    await expect.poll(async () => view.staves().count()).toBeGreaterThan(4);
    const run = (await calls(page)).filter((c) => c.name === "recognize_sheet");
    expect(run.map((c) => c.arguments)).toEqual([{ image: "/home/user/scans/page1.png", engine: "audiveris" }]);
    expect(await calledTools(page)).toContain("get_recognized_score");
  });

  test("the status is announced politely and the button keeps keyboard focus while it runs", async ({ page }) => {
    const view = await ReviewFrame.open(page);
    await view.drawn();
    await expect(view.status()).toHaveAttribute("aria-live", "polite");

    await view.button("Recognize again with Audiveris").focus();
    await view.press("Enter");

    await expect(view.status()).toHaveText(/Recognized again with Audiveris/);
    expect((await view.focused()).name).toBe("Recognize again with oemer");
  });
});

test.describe("accept", () => {
  test("sends one fixed ui/message and one model-context update, once", async ({ page }) => {
    const view = await ReviewFrame.open(page);
    await view.drawn();

    await view.button("Accept score").click();
    await expect(view.button("Accepted")).toBeVisible();
    await view.button("Accepted").click({ force: true });

    const sent = await messages(page, "ui/message");
    expect(sent).toHaveLength(1);
    expect(JSON.stringify(sent[0]!.params)).toContain(
      "I checked the recognized score in the Recognition Review and accept it. Please continue with that score.",
    );
    const context = await messages(page, "ui/update-model-context");
    expect(context).toHaveLength(1);
    expect(JSON.stringify(context[0]!.params)).toContain("1 part, 4 bars, 3 open issues");
    expect(JSON.stringify([...sent, ...context])).not.toMatch(/score-partwise|\.png/);
  });
});
