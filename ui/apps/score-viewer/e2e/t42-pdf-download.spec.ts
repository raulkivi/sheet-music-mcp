import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
import { messages } from "../../../test/e2e/host-helpers.ts";
import { ScoreViewerFrame } from "../../../test/e2e/view-frame.ts";

// T4.2 (docs/research/mcp-apps-improvement-plan.md, DA2): the viewer offers the PDF beside the SVG.
// The page asks get_pdf for a handle and reads the bytes with read_pdf_chunk (the mock host's
// placeholder backend answers); with a sandbox that blocks downloads it falls back to ui/message (D6).

test("Download PDF saves score.pdf: bytes that start with %PDF, read through the app-only tools", async ({ page }) => {
  const view = await ScoreViewerFrame.open(page);
  await expect(view.scorePage()).toBeVisible();
  const [download] = await Promise.all([page.waitForEvent("download"), view.click("Download PDF")]);

  expect(download.suggestedFilename()).toBe("score.pdf");
  expect(readFileSync(await download.path()).subarray(0, 4).toString("latin1")).toBe("%PDF");

  const calls = await messages(page, "tools/call");
  expect(calls.map((message) => message.params!.name).filter((name) => name !== "render_page_svg")).toEqual(["get_pdf", "read_pdf_chunk"]);
  // No path ever reaches the page: the calls carry the score and an id only.
  const chunk = calls.find((message) => message.params!.name === "read_pdf_chunk")!;
  expect(Object.keys(chunk.params!.arguments as object).sort()).toEqual(["length", "offset", "pdf_id"]);
});

test("progress and result are announced in the polite status line (X1)", async ({ page }) => {
  const view = await ScoreViewerFrame.open(page);
  await expect(view.scorePage()).toBeVisible();
  const status = view.content.locator("#status");
  await expect(status).toHaveAttribute("aria-live", "polite");
  await expect(status).toHaveText("");
  await Promise.all([page.waitForEvent("download"), view.click("Download PDF")]);
  await expect(status).toHaveText("PDF ready: score.pdf");
});

test("Enter and Space on Download PDF start the download, and focus stays on the button (X1)", async ({ page }) => {
  const view = await ScoreViewerFrame.open(page);
  await expect(view.scorePage()).toBeVisible();
  await view.tabTo("Download PDF");
  const [first] = await Promise.all([page.waitForEvent("download"), view.press("Enter")]);
  expect(first.suggestedFilename()).toBe("score.pdf");
  await expect(view.content.locator("#status")).toHaveText("PDF ready: score.pdf");
  expect((await view.focused()).name).toBe("Download PDF");
  const [second] = await Promise.all([page.waitForEvent("download"), view.press("Space")]);
  expect(second.suggestedFilename()).toBe("score.pdf");
});

test("without allow-downloads no file is saved, and the D6 fallback asks the model for help", async ({ page }) => {
  const view = await ScoreViewerFrame.open(page, { downloads: "0" });
  await expect(view.scorePage()).toBeVisible();
  let downloaded = false;
  page.on("download", () => (downloaded = true));
  await view.click("Download PDF");
  await expect(view.downloadFallback()).toBeVisible();
  await page.waitForTimeout(500);
  expect(downloaded).toBe(false);

  await view.click("Ask the assistant to open it");
  await expect.poll(async () => (await messages(page, "ui/message")).length).toBe(1);
  expect(JSON.stringify((await messages(page, "ui/message"))[0]!.params)).toContain("/tmp/sheet-music-output/score.pdf");
});

test("a host without the PDF tools leaves a message in the status line and the fallback", async ({ page }) => {
  // server=0: the host answers no tool call, so get_pdf is refused; Verovio WASM still draws the page.
  const view = await ScoreViewerFrame.open(page, { server: "0" });
  await expect(view.scorePage()).toBeVisible();
  let downloaded = false;
  page.on("download", () => (downloaded = true));
  await view.click("Download PDF");
  await expect(view.content.locator("#status")).toContainText("could not make the PDF");
  await expect(view.downloadFallback()).toBeVisible();
  expect(downloaded).toBe(false);
});
