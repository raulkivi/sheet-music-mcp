import { expect, test, type Page } from "@playwright/test";
import { messages } from "../../../test/e2e/host-helpers.ts";
import { DoctorFrame, SIZES, type Scenario } from "./doctor-frame.ts";

// Setup Doctor (plan T3.6, U8): the page shows the health report of the server that serves it and
// nothing else. States: mixed (ok, warn, fail), ready, empty, error; both Claude themes; 360 px and
// desktop without sideways scroll; axe; Tab order with a ring; the call log (open-link, tool call).

const SCENARIOS: Scenario[] = ["health-mixed", "health-ready", "health-empty", "health-error"];

/** What proves the scenario has rendered. */
function shown(view: DoctorFrame, scenario: Scenario) {
  return scenario === "health-error" ? view.notice() : scenario === "health-empty" ? view.empty() : view.headline();
}

async function toolCalls(page: Page): Promise<string[]> {
  return (await messages(page, "tools/call")).map((m) => String(m.params?.name));
}

test("a mixed report lists failures first with a word, version, hint, fix and link for each", async ({ page }) => {
  const view = await DoctorFrame.open(page, "health-mixed");
  await expect(view.headline()).toHaveText("Not ready: 1 check must be fixed");
  await expect(view.summary()).toHaveText("Not ready");
  expect(await view.rowNames()).toEqual(["Soundfont", "PortAudio", "Verovio", "FluidSynth"]);

  const [soundfont, portaudio, verovio] = [view.rows().nth(0), view.rows().nth(1), view.rows().nth(2)];
  await expect(soundfont.locator(".badge")).toHaveText("Must fix");
  await expect(soundfont).toContainText("No General MIDI soundfont was found");
  await expect(soundfont.locator("pre")).toContainText("sudo apt install fluid-soundfont-gm");
  await expect(soundfont.locator("pre")).toContainText("SYNTH_SOUNDFONT_PATH");
  await expect(view.link("Read the setup notes for Soundfont")).toHaveAttribute("href", "https://example.org/setup#soundfont");
  await expect(portaudio.locator(".badge")).toHaveText("Needs attention");
  await expect(verovio.locator(".badge")).toHaveText("Ready");
  await expect(verovio).toContainText("Version 4.3.1");
});

test("a ready report says everything is ready", async ({ page }) => {
  const view = await DoctorFrame.open(page, "health-ready");
  await expect(view.headline()).toHaveText("Everything is ready");
  await expect(view.summary()).toHaveText("Ready");
  expect(await view.rowNames()).toEqual(["Verovio", "FluidSynth"]);
  await expect(view.button("Copy report")).toBeEnabled();
});

test("an empty report says no checks were reported and offers no copy", async ({ page }) => {
  const view = await DoctorFrame.open(page, "health-empty");
  await expect(view.empty()).toBeVisible();
  await expect(view.rows()).toHaveCount(0);
});

test("an error result shows the server's error and disables copying", async ({ page }) => {
  const view = await DoctorFrame.open(page, "health-error");
  await expect(view.notice()).toHaveText("The health check failed: The health probe crashed. (PROCESSING_ERROR).");
  await expect(view.button("Copy report")).toBeDisabled();
  await expect(view.headline()).toBeHidden();
});

test("Check again calls the server's own health_check and shows the new report", async ({ page }) => {
  const view = await DoctorFrame.open(page, "health-mixed");
  await expect(view.headline()).toHaveText("Not ready: 1 check must be fixed");
  await view.button("Check again").click();
  await expect(view.headline()).toHaveText("Everything is ready");
  expect(await toolCalls(page)).toEqual(["health_check"]);
  expect((await messages(page, "tools/call"))[0]!.params).toMatchObject({ name: "health_check", arguments: {} });
  await expect(view.button("Check again")).toHaveAttribute("aria-disabled", "false");
});

test("Copy report puts the plain-text report on the clipboard and confirms in the live region", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  const view = await DoctorFrame.open(page, "health-mixed");
  await view.button("Copy report").click();
  await expect(view.status()).toHaveText("Report copied to the clipboard.");
  const copied = await page.evaluate(() => navigator.clipboard.readText());
  expect(copied).toContain("Setup report: Not ready: 1 check must be fixed");
  expect(copied).toContain("[FAIL] Soundfont");
  expect(copied).toContain("[OK] Verovio (4.3.1)");
});

test("Copy fix copies just that snippet", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  const view = await DoctorFrame.open(page, "health-mixed");
  await view.button("Copy fix for Soundfont").click();
  await expect(view.status()).toHaveText("Fix for Soundfont copied to the clipboard.");
  const copied = await page.evaluate(() => navigator.clipboard.readText());
  expect(copied).toBe("sudo apt install fluid-soundfont-gm\nexport SYNTH_SOUNDFONT_PATH=/usr/share/sounds/sf2/FluidR3_GM.sf2");
});

test("without the host's clipboard permission the page falls back and still tells the user what happened", async ({ page }) => {
  const view = await DoctorFrame.open(page, "health-mixed", { clipboard: "0" });
  await view.button("Copy report").click();
  // Either the legacy copy worked, or the text is offered selected for the user to copy.
  await expect(view.status()).toHaveText(/^Report (copied to the clipboard\.|could not be copied here\. Select the text below and copy it\.)$/);
  if ((await view.status().textContent())?.includes("could not")) {
    await expect(view.manualCopy()).toBeVisible();
    await expect(view.manualCopy()).toHaveValue(/\[FAIL\] Soundfont/);
  }
});

test("a doc link asks the host to open it (ui/open-link) instead of navigating the frame", async ({ page }) => {
  const view = await DoctorFrame.open(page, "health-mixed");
  await view.link("Read the setup notes for Soundfont").click();
  await expect.poll(async () => (await messages(page, "ui/open-link")).length).toBe(1);
  expect((await messages(page, "ui/open-link"))[0]!.params).toEqual({ url: "https://example.org/setup#soundfont" });
  await expect(view.headline()).toBeVisible();
});

test("the page makes no tool call of its own on open and sends only the handshake and size", async ({ page }) => {
  const view = await DoctorFrame.open(page, "health-mixed");
  await expect(view.headline()).toBeVisible();
  expect(await toolCalls(page)).toEqual([]);
  expect(await messages(page, "ui/open-link")).toEqual([]);
});

for (const scenario of SCENARIOS) {
  for (const theme of ["light", "dark"] as const) {
    test(`Claude ${theme} ${scenario}: the recorded colors are painted and axe finds nothing`, async ({ page }) => {
      const view = await DoctorFrame.open(page, scenario, { host: "claude", theme });
      await expect(view.content.locator("html")).toHaveAttribute("data-theme", theme);
      await expect(view.content.locator("body")).toHaveCSS("background-color", theme === "light" ? "rgb(255, 255, 255)" : "rgb(48, 48, 46)");
      await expect(shown(view, scenario)).toBeVisible();
      expect(await view.axeViolations()).toEqual([]);
    });
  }
}

for (const size of SIZES) {
  for (const scenario of SCENARIOS) {
    test(`${size.name} ${scenario}: no sideways scroll, axe clean`, async ({ page }) => {
      const view = await DoctorFrame.open(page, scenario, { host: "claude" }, size);
      await expect(shown(view, scenario)).toBeVisible();
      expect(await view.width()).toBeLessThanOrEqual(size.width);
      expect(await view.scrollsSideways()).toBe(false);
      expect(await view.axeViolations()).toEqual([]);
    });
  }
}

test("Tab reaches every control in reading order, each with a visible focus ring", async ({ page }) => {
  const view = await DoctorFrame.open(page, "health-mixed");
  await expect(view.headline()).toBeVisible();
  const stops = await view.tabThrough();
  expect(stops.map((s) => s.name)).toEqual([
    "Check again",
    "Copy report",
    "Copy fix for Soundfont",
    "Read the setup notes for Soundfont",
  ]);
  for (const stop of stops) expect(stop, `focus ring on ${stop.name}`).toMatchObject({ ringVisible: true });
});

test("Enter and Space activate the buttons and the link", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  const view = await DoctorFrame.open(page, "health-mixed");
  await expect(view.headline()).toBeVisible();

  await view.tabTo("Copy fix for Soundfont");
  await view.press("Space");
  await expect(view.status()).toHaveText("Fix for Soundfont copied to the clipboard.");

  await view.tabTo("Read the setup notes for Soundfont");
  await view.press("Enter");
  await expect.poll(async () => (await messages(page, "ui/open-link")).length).toBe(1);

  await view.tabTo("Copy report");
  await view.press("Enter");
  await expect(view.status()).toHaveText("Report copied to the clipboard.");

  await view.tabTo("Check again");
  await view.press("Enter");
  await expect(view.headline()).toHaveText("Everything is ready");
});

test("Check again keeps keyboard focus on itself while it runs and after", async ({ page }) => {
  const view = await DoctorFrame.open(page, "health-mixed");
  await expect(view.headline()).toBeVisible();
  await view.tabTo("Check again");
  await view.press("Enter");
  await expect(view.headline()).toHaveText("Everything is ready");
  expect(await view.focused()).toEqual({ name: "Check again", ringVisible: true });
});

test("the status line is an aria-live region, and copy confirmation changes it", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  const view = await DoctorFrame.open(page, "health-mixed");
  await expect(view.status()).toHaveAttribute("aria-live", "polite");
  await expect(view.status()).toHaveAttribute("role", "status");
  await view.button("Copy report").click();
  await expect(view.status()).toHaveText("Report copied to the clipboard.");
});

test("reduced motion: the page runs no animation or transition", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  const view = await DoctorFrame.open(page, "health-mixed");
  await expect(view.headline()).toBeVisible();
  for (const selector of ["button", ".badge", ".check"]) {
    const css = await view.content.locator(selector).first().evaluate((el) => {
      const style = getComputedStyle(el);
      return { transition: style.transitionDuration, animation: style.animationName };
    });
    expect(css.transition, selector).toMatch(/^0s(, 0s)*$/);
    expect(css.animation, selector).toBe("none");
  }
});
