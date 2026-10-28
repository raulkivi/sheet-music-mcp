import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";
// @ts-expect-error -- plain .mjs script without type declarations
import { externalReferences } from "../../../scripts/check-html.mjs";

interface LoggedMessage {
  direction: "host->app" | "app->host";
  t: number;
  method?: string;
  params?: Record<string, unknown>;
}

async function openHost(page: Page, query: Record<string, string> = {}) {
  await page.goto(`/?${new URLSearchParams(query)}`);
  return page.frameLocator("iframe");
}

function messages(page: Page, method: string): Promise<LoggedMessage[]> {
  return page.evaluate(
    (m) => (window as unknown as { __host: { messages(m: string): LoggedMessage[] } }).__host.messages(m),
    method,
  );
}

async function pageLabel(frame: ReturnType<Page["frameLocator"]>) {
  const text = (await frame.locator("#page-label").textContent()) ?? "";
  const [, page, count] = text.match(/Page (\d+) \/ (\d+)/) ?? [];
  return { page: Number(page), count: Number(count) };
}

test("the built page has no off-origin references (AC-R1)", () => {
  const html = readFileSync(new URL("../../../dist/score-viewer.html", import.meta.url), "utf8");
  expect(externalReferences(html)).toEqual([]);
});

test("completes the ui/initialize handshake and renders page 1 after tool-input", async ({ page }) => {
  const frame = await openHost(page);
  await expect(frame.locator("#score svg").first()).toBeVisible();
  await expect(frame.locator("#page-label")).toHaveText(/^Page 1 \/ \d+$/);

  const init = await messages(page, "ui/initialize");
  expect(init).toHaveLength(1);
  expect(init[0]!.params).toMatchObject({
    protocolVersion: "2026-01-26",
    appInfo: { name: "sheet-music-score-viewer" },
    appCapabilities: { availableDisplayModes: ["inline", "fullscreen"] },
  });
  expect(await messages(page, "ui/notifications/initialized")).toHaveLength(1);
});

test("Next and Prev move through a five-page score and stop at both ends (AC-R3)", async ({ page }) => {
  const frame = await openHost(page);
  await expect(frame.locator("#score svg").first()).toBeVisible();
  const { count } = await pageLabel(frame);
  expect(count).toBeGreaterThanOrEqual(5);

  const next = frame.locator("#next");
  const prev = frame.locator("#prev");
  await expect(prev).toBeDisabled();
  for (let i = 1; i < count; i++) await next.click();
  await expect(frame.locator("#page-label")).toHaveText(`Page ${count} / ${count}`);
  await expect(next).toBeDisabled();
  await next.click({ force: true });
  await expect(frame.locator("#page-label")).toHaveText(`Page ${count} / ${count}`);

  for (let i = 1; i < count; i++) await prev.click();
  await expect(frame.locator("#page-label")).toHaveText(`Page 1 / ${count}`);
  await expect(prev).toBeDisabled();

  const context = await messages(page, "ui/update-model-context");
  expect(context.at(-1)!.params).toEqual({
    content: [{ type: "text", text: `Score Viewer: the user is looking at page 1 of ${count}.` }],
  });
});

test("zoom buttons change the zoom level and re-render", async ({ page }) => {
  const frame = await openHost(page);
  await expect(frame.locator("#score svg").first()).toBeVisible();
  // Zoom keeps the page as wide as the container but lays out fewer units across it.
  const layout = frame.locator("#score svg.definition-scale");
  const before = await layout.getAttribute("viewBox");
  await frame.locator("#zoom-in").click();
  await expect(frame.locator("#zoom-label")).toHaveText("125%");
  await expect(layout).not.toHaveAttribute("viewBox", before ?? "");
  await frame.locator("#zoom-out").click();
  await frame.locator("#zoom-out").click();
  await expect(frame.locator("#zoom-label")).toHaveText("80%");
});

test("follows a dark host theme", async ({ page }) => {
  const frame = await openHost(page, { theme: "dark" });
  await expect(frame.locator("#score svg").first()).toBeVisible();
  const background = await frame.locator("body").evaluate((el) => getComputedStyle(el).backgroundColor);
  expect(background).toBe("rgb(19, 19, 20)");
  await page.evaluate(() => (window as unknown as { __host: { setTheme(t: string): void } }).__host.setTheme("light"));
  await expect
    .poll(() => frame.locator("body").evaluate((el) => getComputedStyle(el).backgroundColor))
    .toBe("rgb(255, 255, 255)");
});

test("re-flows on container resize and reports the new size", async ({ page }) => {
  const frame = await openHost(page, { scenario: "inline-satb" });
  const svg = frame.locator("#score > svg");
  await expect(svg).toBeVisible();
  const wide = Number((await svg.getAttribute("width"))?.replace("px", ""));
  const sizesBefore = (await messages(page, "ui/notifications/size-changed")).length;

  await page.evaluate(() => (window as unknown as { __host: { resize(w: number): void } }).__host.resize(640));
  await expect.poll(async () => Number((await svg.getAttribute("width"))?.replace("px", ""))).toBeLessThan(wide);
  const narrow = Number((await svg.getAttribute("width"))?.replace("px", ""));
  expect(narrow).toBeLessThanOrEqual(640);

  await expect.poll(async () => (await messages(page, "ui/notifications/size-changed")).length).toBeGreaterThan(sizesBefore);
  const last = (await messages(page, "ui/notifications/size-changed")).at(-1)!;
  expect(last.params).toMatchObject({ width: expect.any(Number), height: expect.any(Number) });
  expect(last.params!.width as number).toBeLessThanOrEqual(640);
});

test("Download SVG saves the visible page and offers the D6 fallback", async ({ page }) => {
  const frame = await openHost(page);
  await expect(frame.locator("#score svg").first()).toBeVisible();
  const [download] = await Promise.all([page.waitForEvent("download"), frame.locator("#download").click()]);
  expect(download.suggestedFilename()).toBe("score-page-1.svg");
  const saved = readFileSync(await download.path(), "utf8");
  expect(saved).toContain("<svg");

  await expect(frame.locator("#fallback")).toBeVisible();
  await expect(frame.locator("#saved-path")).toHaveText("/tmp/sheet-music-output/score.pdf");
  await frame.locator("#ask").click();
  await expect.poll(async () => (await messages(page, "ui/message")).length).toBe(1);
  expect((await messages(page, "ui/message"))[0]!.params).toEqual({
    role: "user",
    content: [
      {
        type: "text",
        text:
          "I could not download the file from the Score Viewer. Please help me open or share the " +
          "rendered score saved at `/tmp/sheet-music-output/score.pdf`.",
      },
    ],
  });
});

test("without allow-downloads no download happens, and the fallback still shows", async ({ page }) => {
  const frame = await openHost(page, { downloads: "0" });
  await expect(frame.locator("#score svg").first()).toBeVisible();
  let downloaded = false;
  page.on("download", () => (downloaded = true));
  await frame.locator("#download").click();
  await expect(frame.locator("#fallback")).toBeVisible();
  await page.waitForTimeout(500);
  expect(downloaded).toBe(false);
});

test("a path-only call shows the inline-score notice and the saved path", async ({ page }) => {
  const frame = await openHost(page, { scenario: "path-only" });
  await expect(frame.locator("#notice")).toContainText("needs the score inline");
  await expect(frame.locator("#saved-path")).toHaveText("/tmp/sheet-music-output/score.pdf");
  await expect(frame.locator("#score svg")).toHaveCount(0);
});

test("offers fullscreen only when the host does, and requests it", async ({ page }) => {
  const inlineOnly = await openHost(page, { scenario: "inline-satb" });
  await expect(inlineOnly.locator("#score svg").first()).toBeVisible();
  await expect(inlineOnly.locator("#fullscreen")).toBeHidden();

  const frame = await openHost(page, { scenario: "inline-satb", modes: "inline,fullscreen" });
  await expect(frame.locator("#fullscreen")).toBeVisible();
  await frame.locator("#fullscreen").click();
  await expect(frame.locator("#fullscreen")).toHaveText("Exit fullscreen");
  expect((await messages(page, "ui/request-display-mode"))[0]!.params).toEqual({ mode: "fullscreen" });
});

test("under the spec's default CSP (no wasm-unsafe-eval) the viewer explains it cannot render", async ({ page }) => {
  const frame = await openHost(page, { csp: "spec" });
  await expect(frame.locator("#notice")).toContainText("could not start the notation engine");
  await expect(frame.locator("#saved-path")).toHaveText("/tmp/sheet-music-output/score.pdf");
});
