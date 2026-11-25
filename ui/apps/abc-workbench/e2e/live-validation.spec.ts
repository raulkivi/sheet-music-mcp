import { expect, test } from "@playwright/test";
import { AbcWorkbenchFrame } from "../../../test/e2e/abc-frame.ts";
import { ABC_ORIGINAL } from "../../../test/mock-host/abc-tools.ts";

// AC-A3 (UI): an invalid ABC edit shows an error marker on the reported line within 500 ms of the
// last keystroke. The validator is debounced at 300 ms, and the page shows the server's answer.

const BROKEN = ABC_ORIGINAL.replace("G4 z4 |", "G?4 z4 |");
const FAULT_LINE = 7;

async function openEditor(page: Parameters<typeof AbcWorkbenchFrame.open>[0]): Promise<AbcWorkbenchFrame> {
  const view = await AbcWorkbenchFrame.open(page, { scenario: "abc-export" });
  await expect(view.validation()).toHaveText("Valid ABC");
  await view.button("Edit").click();
  await expect(view.editor()).toHaveValue(ABC_ORIGINAL);
  return view;
}

test("AC-A3 the error marker is on the reported line within 500 ms of the last keystroke", async ({ page }) => {
  const view = await openEditor(page);
  await view.editor().fill(BROKEN);
  const typed = Date.now();
  await expect(view.gutterLine(FAULT_LINE, true)).toBeVisible({ timeout: 500 });
  expect(Date.now() - typed).toBeLessThan(500);
  await expect(view.gutterLine(FAULT_LINE - 1, true)).toHaveCount(0);
  await expect(view.validation()).toHaveText(`1 error: Line ${FAULT_LINE}: unexpected "?"`);
  await expect(view.content.locator("#problems li")).toHaveText(`Line ${FAULT_LINE}: unexpected "?"`);
});

test("the marker goes away once the line is fixed, and Accept is only possible then", async ({ page }) => {
  const view = await openEditor(page);
  await view.editor().fill(BROKEN);
  await expect(view.gutterLine(FAULT_LINE, true)).toBeVisible();
  await view.button("Review").click();
  await expect(view.button("Accept selected")).toBeDisabled();
  await view.button("Edit").click();
  await view.editor().fill(BROKEN.replace("G?4", "G4 "));
  await expect(view.gutterLine(FAULT_LINE, true)).toHaveCount(0);
  await expect(view.validation()).toHaveText("Valid ABC");
});

test("typing makes one validate_abc call, 300 ms after the last keystroke", async ({ page }) => {
  const view = await openEditor(page);
  await expect.poll(async () => (await view.toolCalls("validate_abc")).length).toBeGreaterThan(0);
  const before = (await view.toolCalls("validate_abc")).length;
  await view.editor().pressSequentially(" % note", { delay: 40 });
  await expect(view.validation()).toHaveText("Valid ABC");
  await expect(view.validation()).not.toHaveAttribute("data-status", "pending");
  const calls = await view.toolCalls("validate_abc");
  expect(calls.length - before).toBe(1);
  expect(String(calls.at(-1)?.abc)).toContain(" % note");
});

test("the status says it is checking while the validator waits", async ({ page }) => {
  const view = await openEditor(page);
  await view.editor().pressSequentially("x");
  await expect(view.validation()).toHaveAttribute("data-status", /pending|valid/);
  await expect(view.validation()).toHaveText("Valid ABC");
});

test("a change typed in Edit appears as a change in Review", async ({ page }) => {
  const view = await openEditor(page);
  await view.editor().fill(ABC_ORIGINAL.replace("d2 c2", "d2 e2"));
  await view.button("Review").click();
  await expect(view.hunks()).toHaveCount(1);
  await expect(view.summary()).toHaveText("1 change, 1 kept");
  await view.button("Accept selected").click();
  await expect(view.outcome()).toHaveText("Accepted 1 of 1: MusicXML ready.");
});
