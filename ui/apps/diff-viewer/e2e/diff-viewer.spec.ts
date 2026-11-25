import { expect, test } from "@playwright/test";
import { messages } from "../../../test/e2e/host-helpers.ts";
import { DiffViewerFrame } from "./diff-frame.ts";

// U8 (docs/research/ui-and-sound-testing-plan.md): render, empty and error states, AC-C3, the
// report, export and "Open in Score Viewer" through the host's call log. Sizes, themes, axe and
// Tab order are in u8-states-and-sizes.spec.ts.

const calledTools = async (page: import("@playwright/test").Page) =>
  (await messages(page, "tools/call")).map((m) => (m.params as { name: string }).name);

test.describe("render", () => {
  test("shows the headline, the changes, the kinds present and both scores", async ({ page }) => {
    const view = await DiffViewerFrame.open(page);
    await view.scoresDrawn();

    await expect(view.headline()).toHaveText("99.5% similar, 4 changes");
    await expect(view.changes()).toHaveCount(4);
    await expect(view.change(/Alto, bar 7/)).toBeVisible();
    // Kinds come from the operations in the result: pitch and removed, nothing else.
    await expect(view.filter(/Pitch changed \(3\)/)).toBeVisible();
    await expect(view.filter(/Removed \(1\)/)).toBeVisible();
    await expect(view.filter(/Added|Replaced|Length/)).toHaveCount(0);
    expect(await calledTools(page)).toEqual(["get_diff_scores"]);
  });

  test("draws the differences in the legend colors (Verovio takes the MusicXML color)", async ({ page }) => {
    const view = await DiffViewerFrame.open(page);
    await view.scoresDrawn();

    const colored = view.pane("target").locator('[fill="#FF8800" i], [style*="#ff8800" i], [color="#FF8800" i]');
    await expect(colored.first()).toBeAttached();
  });
});

test.describe("AC-C3: selecting a change scrolls both panes to its bar", () => {
  test("clicking bar 19 marks and shows bar 19 in the reference and the target", async ({ page }) => {
    const view = await DiffViewerFrame.open(page);
    await view.scoresDrawn();
    expect(await view.scrollTop("reference")).toBe(0);
    expect(await view.scrollTop("target")).toBe(0);

    await view.change(/Soprano, bar 19/).click();

    for (const which of ["reference", "target"] as const) {
      await expect(view.highlight(which)).toHaveCount(1);
      const { pane, mark } = await view.boxes(which);
      expect(mark.top, `${which} mark top inside the pane`).toBeGreaterThanOrEqual(pane.top - 1);
      expect(mark.bottom, `${which} mark bottom inside the pane`).toBeLessThanOrEqual(pane.bottom + 1);
      expect(await view.scrollTop(which), `${which} scrolled`).toBeGreaterThan(0);
    }
    await expect(view.selection()).toHaveText(/^Change 3 of 4\. Soprano, bar 19, beat \d/);
    await expect(view.change(/Soprano, bar 19/)).toHaveAttribute("aria-current", "true");
  });

  test("another change moves the mark; it never leaves two", async ({ page }) => {
    const view = await DiffViewerFrame.open(page);
    await view.scoresDrawn();
    await view.change(/Soprano, bar 19/).click();
    await expect(view.highlight("target")).toHaveCount(1);
    const first = await view.scrollTop("target");

    await view.change(/Alto, bar 7/).click();

    await expect(view.highlight("target")).toHaveCount(1);
    await expect(view.highlight("reference")).toHaveCount(1);
    expect(await view.scrollTop("target")).toBeLessThan(first);
  });

  test("scrolls instantly, with or without a reduced-motion preference", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    const view = await DiffViewerFrame.open(page);
    await view.scoresDrawn();

    await view.change(/Soprano, bar 19/).click();

    // No animation: the position is final in the same frame as the click.
    expect(await view.scrollTop("target")).toBeGreaterThan(0);
    expect(await view.pane("target").evaluate((el) => getComputedStyle(el).scrollBehavior)).not.toBe("smooth");
  });
});

test.describe("filters", () => {
  test("a kind narrows the list and toggling it off restores it", async ({ page }) => {
    const view = await DiffViewerFrame.open(page);
    await view.scoresDrawn();

    await view.filter(/Removed/).click();
    await expect(view.changes()).toHaveCount(1);
    await expect(view.filter(/Removed/)).toHaveAttribute("aria-pressed", "true");
    await expect(view.change(/Bass, bar 12/)).toContainText("removed");

    await view.filter(/Removed/).click();
    await expect(view.changes()).toHaveCount(4);
  });
});

test.describe("report", () => {
  test("the Report tab shows the server's report", async ({ page }) => {
    const view = await DiffViewerFrame.open(page);
    await view.scoresDrawn();

    await view.tab("Report").click();

    await expect(view.report()).toContainText("Overall similarity");
    await expect(view.tab("Report")).toHaveAttribute("aria-selected", "true");
    await view.tab("Scores").click();
    await expect(view.pane("target")).toBeVisible();
  });
});

test.describe("export and Open in Score Viewer", () => {
  test("saving the scores calls the app-only export tool and shows a chip per file", async ({ page }) => {
    const view = await DiffViewerFrame.open(page);
    await view.scoresDrawn();

    await view.button("Save annotated scores").click();

    await expect(view.chips()).toHaveText([/reference.*\.musicxml$/, /target.*\.musicxml$/]);
    expect(await calledTools(page)).toEqual(["get_diff_scores", "export_diff_scores"]);
    expect(await messages(page, "ui/message")).toHaveLength(0);
  });

  test("Open in Score Viewer posts one ui/message and exports once", async ({ page }) => {
    const view = await DiffViewerFrame.open(page);
    await view.scoresDrawn();

    await view.button("Open in Score Viewer").click();
    await expect.poll(async () => (await messages(page, "ui/message")).length).toBe(1);
    await view.button("Open in Score Viewer").click();
    await expect.poll(async () => (await messages(page, "ui/message")).length).toBe(2);

    const sent = await messages(page, "ui/message");
    const first = JSON.stringify(sent[0]!.params);
    expect(first).toContain("Open the annotated target score");
    expect(first).toContain("annotated-target");
    expect(first).not.toContain("<score-partwise");
    // The second click reuses the saved files.
    expect((await calledTools(page)).filter((name) => name === "export_diff_scores")).toHaveLength(1);
  });
});

test.describe("states", () => {
  test("identical scores: says so, lists nothing", async ({ page }) => {
    const view = await DiffViewerFrame.open(page, { scenario: "diff-identical" });

    await expect(view.headline()).toHaveText("100% similar, no changes");
    await expect(view.notice()).toContainText("The scores are identical");
    await expect(view.changes()).toHaveCount(0);
    await expect(view.filter(/./)).toHaveCount(0);
  });

  test("a failed comparison shows its error code and calls nothing", async ({ page }) => {
    const view = await DiffViewerFrame.open(page, { scenario: "diff-error" });

    await expect(view.notice()).toContainText("The comparison failed (INVALID_INPUT).");
    await expect(view.changes()).toHaveCount(0);
    await expect(view.button("Save annotated scores")).toBeDisabled();
    expect(await calledTools(page)).toEqual([]);
  });

  test("without the notation engine the list and report still work", async ({ page }) => {
    const view = await DiffViewerFrame.open(page, { csp: "spec" });

    await expect(view.notice()).toContainText("could not start the notation engine");
    await expect(view.changes()).toHaveCount(4);
    await view.tab("Report").click();
    await expect(view.report()).toContainText("Overall similarity");
  });
});
