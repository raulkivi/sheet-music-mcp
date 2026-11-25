import { expect, test } from "@playwright/test";
import { AbcWorkbenchFrame } from "../../../test/e2e/abc-frame.ts";
import { ABC_ORIGINAL, ABC_PROPOSED } from "../../../test/mock-host/abc-tools.ts";

// ABC Workbench in the mock host (plan T2.7; U8 rows: render, empty, error, call log).
// The page shows what the tools return; the mock host's data lives in test/mock-host/abc-tools.ts.

test.describe("render: the model's edit against the original", () => {
  test("shows each change with the original and proposed lines side by side", async ({ page }) => {
    const view = await AbcWorkbenchFrame.open(page);
    await expect(view.hunks()).toHaveCount(2);
    const first = view.hunks().first();
    await expect(first.locator(".col.del .text")).toHaveText("|: d2 c2 B2 A2 | G4 z4 |");
    await expect(first.locator(".col.add .text")).toHaveText("|: d2 c2 B2 G2 | G4 z4 |");
    await expect(view.summary()).toHaveText("2 changes, 2 kept");
  });

  test("fetches the original with get_abc once and lists the server's warnings", async ({ page }) => {
    const view = await AbcWorkbenchFrame.open(page);
    await expect(view.content.locator("#warnings li")).toHaveText("Dynamics and complex articulations are not kept in ABC.");
    expect(await view.toolCalls("get_abc")).toEqual([{}]);
  });

  test("shows the validator's own answer, not a fixed text", async ({ page }) => {
    const view = await AbcWorkbenchFrame.open(page);
    await expect(view.validation()).toHaveText("Valid ABC");
    expect(await view.toolCalls("validate_abc")).toEqual([{ abc: ABC_PROPOSED }]);
  });

  test("Full text shows the unchanged lines too", async ({ page }) => {
    const view = await AbcWorkbenchFrame.open(page);
    await view.button("Full text").click();
    await expect(view.content.locator(".context")).toHaveCount(7);
    await view.button("Changes only").click();
    await expect(view.content.locator(".context")).toHaveCount(0);
  });
});

test.describe("empty and error states", () => {
  test("an export without an edit says nothing is proposed and cannot be accepted", async ({ page }) => {
    const view = await AbcWorkbenchFrame.open(page, { scenario: "abc-export" });
    await expect(view.content.locator(".empty")).toHaveText("The assistant has not proposed a change yet. Choose Edit to change the ABC yourself.");
    await expect(view.button("Accept selected")).toBeDisabled();
    await expect(view.button("Accept all")).toBeDisabled();
  });

  test("a failed tool call is reported with its error code", async ({ page }) => {
    const view = await AbcWorkbenchFrame.open(page, { scenario: "abc-error" });
    await expect(view.notice()).toHaveText("The tool call failed (INVALID_INPUT).");
  });

  test("a lost original export is explained, and the proposal is still shown", async ({ page }) => {
    const view = await AbcWorkbenchFrame.open(page, { scenario: "abc-no-original" });
    await expect(view.notice()).toContainText("original ABC");
    await expect(view.hunks()).toHaveCount(1);
  });
});

test.describe("deciding", () => {
  test("Accept selected converts the kept hunks once with return auto, then tells the model", async ({ page }) => {
    const view = await AbcWorkbenchFrame.open(page);
    await view.keepBox(2).uncheck();
    await expect(view.summary()).toHaveText("2 changes, 1 kept");
    await view.button("Accept selected").click();
    await expect(view.outcome()).toHaveText("Accepted 1 of 2: MusicXML ready.");
    const kept = ABC_ORIGINAL.replace("B2 A2", "B2 G2");
    await expect.poll(() => view.toolCalls("abc_to_musicxml")).toEqual([{ abc: kept, return: "auto" }]);
    const context = await view.hostMessages("ui/update-model-context");
    expect(JSON.stringify(context[0]?.params)).toContain("accepted 1 of 2 proposed changes");
    await expect(view.button("Download MusicXML")).toBeVisible();
  });

  test("Accept all converts the whole proposal", async ({ page }) => {
    const view = await AbcWorkbenchFrame.open(page);
    await view.keepBox(1).uncheck();
    await view.button("Accept all").click();
    await expect(view.outcome()).toHaveText("Accepted 2 of 2: MusicXML ready.");
    expect(await view.toolCalls("abc_to_musicxml")).toEqual([{ abc: ABC_PROPOSED, return: "auto" }]);
  });

  test("a file delivery shows a file chip with the server's path", async ({ page }) => {
    const view = await AbcWorkbenchFrame.open(page, { scenario: "abc-edit-file" });
    await view.button("Accept all").click();
    await expect(view.fileChip()).toContainText("/tmp/sheet-music-output/scores/from-abc-1.musicxml");
    await expect(view.button("Download MusicXML")).toBeHidden();
    const context = await view.hostMessages("ui/update-model-context");
    expect(JSON.stringify(context[0]?.params)).toContain("from-abc-1.musicxml");
  });

  test("Reject all makes no conversion and tells the model", async ({ page }) => {
    const view = await AbcWorkbenchFrame.open(page);
    await view.button("Reject all").click();
    await expect(view.outcome()).toHaveText("Rejected: the original score stays as it is.");
    expect(await view.toolCalls("abc_to_musicxml")).toEqual([]);
    const context = await view.hostMessages("ui/update-model-context");
    expect(JSON.stringify(context[0]?.params)).toContain("rejected all 2 proposed changes");
  });

  test("Ask the assistant to revise posts a fixed message naming the rejected change", async ({ page }) => {
    const view = await AbcWorkbenchFrame.open(page);
    await view.keepBox(2).uncheck();
    await view.button("Ask the assistant to revise").click();
    await expect.poll(async () => (await view.hostMessages("ui/message")).length).toBe(1);
    const [message] = await view.hostMessages("ui/message");
    expect(JSON.stringify(message?.params)).toContain("rejected 1 of 2 changes: change 2 (original line 9)");
  });
});
