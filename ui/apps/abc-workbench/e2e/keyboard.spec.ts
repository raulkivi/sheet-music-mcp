import { expect, test } from "@playwright/test";
import { AbcWorkbenchFrame } from "../../../test/e2e/abc-frame.ts";

// X1: every control is reachable by keyboard with a visible ring; hunks are navigated with the
// arrow keys and decided with Space; status changes are announced through live regions.

test("Tab order: mode, layout, each change, then the decision buttons, each with a ring", async ({ page }) => {
  const view = await AbcWorkbenchFrame.open(page);
  await expect(view.validation()).toHaveText("Valid ABC");
  const stops = await view.tabThrough();
  expect(stops.map((stop) => stop.name)).toEqual([
    "Review",
    "Edit",
    "Changes only",
    "Full text",
    "Keep change 1",
    "Keep change 2",
    "Accept selected",
    "Accept all",
    "Reject all",
    "Ask the assistant to revise",
  ]);
  for (const stop of stops) expect(stop, `focus ring on ${stop.name}`).toMatchObject({ ringVisible: true });
});

test("Up and Down move between changes, Space keeps or drops one, focus stays on it", async ({ page }) => {
  const view = await AbcWorkbenchFrame.open(page);
  await view.tabTo("Keep change 1");
  await view.press("ArrowDown");
  expect((await view.focused()).name).toBe("Keep change 2");
  await view.press("Space");
  await expect(view.summary()).toHaveText("2 changes, 1 kept");
  expect((await view.focused()).name).toBe("Keep change 2");
  await view.press("ArrowUp");
  expect((await view.focused()).name).toBe("Keep change 1");
  await view.press("ArrowUp");
  expect((await view.focused()).name).toBe("Keep change 1");
});

test("Enter on Accept selected converts once", async ({ page }) => {
  const view = await AbcWorkbenchFrame.open(page);
  await expect(view.validation()).toHaveText("Valid ABC");
  await view.tabTo("Accept selected");
  await view.press("Enter");
  await expect(view.outcome()).toHaveText("Accepted 2 of 2: MusicXML ready.");
  expect(await view.toolCalls("abc_to_musicxml")).toHaveLength(1);
});

test("Space on Edit switches mode, and the editor is reachable by Tab", async ({ page }) => {
  const view = await AbcWorkbenchFrame.open(page);
  await view.tabTo("Edit");
  await view.press("Space");
  await expect(view.editor()).toBeVisible();
  const stops = await view.tabThrough();
  expect(stops.map((stop) => stop.name)).toContain("Proposed ABC");
});

test("the validation status and the outcome are live regions", async ({ page }) => {
  const view = await AbcWorkbenchFrame.open(page);
  await expect(view.validation()).toHaveAttribute("role", "status");
  await expect(view.validation()).toHaveAttribute("aria-live", "polite");
  await expect(view.outcome()).toHaveAttribute("aria-live", "polite");
});
