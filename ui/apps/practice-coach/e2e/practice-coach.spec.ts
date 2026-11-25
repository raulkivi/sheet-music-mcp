import { expect, test } from "@playwright/test";
import { CoachFrame } from "../../../test/e2e/coach-frame.ts";
import { messages } from "../../../test/e2e/host-helpers.ts";

// The Practice Coach in the mock host (docs/research/mcp-apps-improvement-plan.md, T1.3 and T1.4).
// The host plays the model calling start_practice; the page then draws the score from
// get_score_for_session and polls get_current_position. The pitch tools are scripted
// (test/mock-host/pitch-backend.ts), so each take is the same every run.

test.describe("render, empty and error states", () => {
  test("a started practice draws the score and listens: the server microphone is the only choice", async ({ page }) => {
    const coach = await CoachFrame.open(page);
    await coach.ready();
    await expect(coach.content.locator("#score g.measure")).toHaveCount(4);
    await expect(coach.content.locator("#session-label")).toHaveText("Alto · 4 bars · 60 bpm");
    await expect(coach.badge()).toHaveText("Listening");
    await expect(coach.button("Stop and see summary")).toBeEnabled();
    await expect(coach.button("Start listening")).toBeDisabled();
    await expect(coach.microphone()).toBeChecked();
    await expect(coach.microphone()).toBeEnabled();
    await expect(coach.browserMicrophone()).toBeDisabled();
  });

  test("a session without an open microphone is ready: Start opens it and polling begins", async ({ page }) => {
    const coach = await CoachFrame.open(page, { scenario: "coach-loaded" });
    await coach.ready();
    await expect(coach.badge()).toHaveText("Ready");
    await expect(coach.button("Start listening")).toBeEnabled();
    expect(await coach.callCount("get_current_position")).toBe(0);
    await coach.button("Start listening").click();
    await expect(coach.badge()).toHaveText("Listening");
    await expect.poll(() => coach.callCount("get_current_position")).toBeGreaterThan(2);
    expect(await coach.callCount("start_monitoring")).toBe(1);
  });

  test("no session in the opening result: the empty state, no tool call, nothing to start", async ({ page }) => {
    const coach = await CoachFrame.open(page, { scenario: "coach-empty" });
    await expect(coach.empty()).toBeVisible();
    await expect(coach.notice()).toContainText("No practice session is open");
    await expect(coach.button("Start listening")).toBeDisabled();
    await expect(coach.button("Stop and see summary")).toBeDisabled();
    expect(await coach.toolCalls()).toEqual([]);
  });

  test("a failed start_practice shows the server's error code, not a blank page", async ({ page }) => {
    const coach = await CoachFrame.open(page, { scenario: "coach-error" });
    await expect(coach.notice()).toContainText("PROCESSING_FAILED");
    await expect(coach.empty()).toBeVisible();
    expect(await coach.toolCalls()).toEqual([]);
  });

  test("with no engine for the score (spec CSP, no WebAssembly) the server pages stand in and pitch feedback still works", async ({ page }) => {
    const coach = await CoachFrame.open(page, { csp: "spec" });
    await expect(coach.content.locator("#score svg[data-server-page]")).toBeVisible();
    await expect(coach.status()).toHaveText("On pitch");
    expect((await coach.toolCalls()).some((c) => c.name === "render_page_svg")).toBe(true);
  });
});

test.describe("call log", () => {
  test("the page fetches the score, asks the listing, then polls the session by id; it sends no chat message", async ({ page }) => {
    const coach = await CoachFrame.open(page);
    await coach.ready();
    await expect.poll(() => coach.callCount("get_current_position")).toBeGreaterThan(3);
    const calls = await coach.toolCalls();
    expect(calls.slice(0, 2).map((c) => c.name).sort()).toEqual(["get_score_for_session", "list_sessions"]);
    expect(calls.find((c) => c.name === "get_score_for_session")?.arguments).toEqual({ session_id: "mock-session" });
    for (const poll of calls.filter((c) => c.name === "get_current_position")) {
      expect(poll.arguments).toEqual({ session_id: "mock-session" });
    }
    // While listening nothing is sent to the model; the context update comes on Stop.
    expect(await messages(page, "ui/message")).toEqual([]);
    expect(await messages(page, "ui/update-model-context")).toEqual([]);
  });
});

test.describe("T1.5: Ask Claude for tips", () => {
  test("Stop sends one fixed context update; the tips button sends one fixed message, once", async ({ page }) => {
    const coach = await CoachFrame.open(page);
    await coach.ready();
    await expect.poll(() => coach.callCount("get_current_position")).toBeGreaterThan(8);
    await coach.button("Stop and see summary").click();
    await expect(coach.report()).toBeVisible();
    expect(await messages(page, "ui/message")).toEqual([]);
    const updates = await messages(page, "ui/update-model-context");
    expect(updates).toHaveLength(1);
    expect(JSON.stringify(updates[0])).toMatch(/Practice Coach: the singer stopped listening/);
    const tips = coach.button("Ask Claude for tips");
    await tips.focus();
    await page.keyboard.press("Enter");
    await expect(coach.notice()).toContainText("Asked Claude for tips");
    const sent = await messages(page, "ui/message");
    expect(sent).toHaveLength(1);
    const text = JSON.stringify(sent[0]);
    expect(text).toContain("My Practice Coach summary");
    expect(text).toContain("Please give me short tips");
    expect(text).not.toMatch(/<|musicxml/i);
    expect(await messages(page, "ui/update-model-context")).toHaveLength(1);
  });
});

test.describe("AC-P5: the cursor and the meter follow the take", () => {
  // coach-loaded + latency: the spec starts recording, then clicks Start, so no step is missed.
  test("the cursor visits the bars in order, on the right bar of the score", async ({ page }) => {
    const coach = await CoachFrame.open(page, { scenario: "coach-loaded", latency: "120" });
    await coach.ready();
    await coach.recordReadings();
    await coach.button("Start listening").click();
    await expect.poll(async () => (await coach.recorded()).some((r) => r.measure === 4 && r.beat === 3)).toBe(true);
    const readings = await coach.recorded();
    const bars = readings.map((r) => r.measure).filter((m, i, all) => i === 0 || m !== all[i - 1]);
    expect(bars).toEqual([1, 2, 3, 4]);
    for (const reading of readings) {
      expect(reading.cursorHidden).toBe(false);
      expect(reading.cursorIndex).toBe(String(reading.measure - 1));
      expect(reading.cursorHeight).toBeGreaterThan(10);
    }
    await expect(coach.where()).toContainText("Bar 4");
  });

  test("the meter takes the color of each state, and an uncertain or silent frame has no needle", async ({ page }) => {
    const coach = await CoachFrame.open(page, { scenario: "coach-loaded", latency: "120" });
    await coach.ready();
    await coach.recordReadings();
    await coach.button("Start listening").click();
    await expect.poll(async () => (await coach.recorded()).some((r) => r.status === "on_pitch" && r.measure === 4)).toBe(true);
    const readings = await coach.recorded();
    const toneOf = (status: string) => [...new Set(readings.filter((r) => r.status === status).map((r) => r.tone))];
    expect(toneOf("on_pitch")).toEqual(["ok"]);
    expect(toneOf("flat")).toEqual(["warn"]);
    // +32 cents is a near miss (warn), +70 a clear one (danger).
    expect(toneOf("sharp").sort()).toEqual(["danger", "warn"]);
    expect(toneOf("uncertain")).toEqual(["neutral"]);
    expect(toneOf("no_signal")).toEqual(["muted"]);
    for (const status of ["uncertain", "no_signal"]) {
      expect(readings.filter((r) => r.status === status).every((r) => r.needleHidden), status).toBe(true);
    }
    for (const status of ["on_pitch", "sharp", "flat"]) {
      expect(readings.filter((r) => r.status === status).every((r) => !r.needleHidden), status).toBe(true);
    }
    // The needle's color is the tone's: three different colors for ok, warn and danger.
    const colorOf = (tone: string) => readings.find((r) => r.tone === tone && !r.needleHidden)?.needleColor;
    expect(new Set([colorOf("ok"), colorOf("warn"), colorOf("danger")]).size).toBe(3);
  });

  test("an uncertain frame is worded as not graded, never as a flat, sharp or wrong note", async ({ page }) => {
    const coach = await CoachFrame.open(page, { scenario: "coach-loaded", latency: "120" });
    await coach.ready();
    await coach.recordReadings();
    await coach.button("Start listening").click();
    await expect.poll(async () => (await coach.recorded()).some((r) => r.status === "uncertain")).toBe(true);
    const uncertain = (await coach.recorded()).find((r) => r.status === "uncertain")!;
    expect(uncertain.label).toBe("Not sure");
    expect(uncertain.centsText).toBe("Not graded: the pitch was unclear");
    expect(uncertain.pillClass).toContain("tone-neutral");
    expect(uncertain.pillClass).not.toMatch(/tone-(warn|danger)/);
  });

  test("the status and the cents are live regions, and the meter says what it shows in words", async ({ page }) => {
    const coach = await CoachFrame.open(page);
    await coach.ready();
    await expect(coach.status()).toHaveAttribute("aria-live", "polite");
    await expect(coach.centsText()).toHaveAttribute("aria-live", "polite");
    await expect(coach.meter()).toHaveAttribute("role", "meter");
    await expect(coach.meter()).toHaveAttribute("aria-valuetext", /cents|Not graded|No sound|Waiting/);
  });
});

test.describe("Stop and the report", () => {
  test("Stop closes the session and shows the report from the server's summary and the bars the page saw", async ({ page }) => {
    const coach = await CoachFrame.open(page);
    await coach.ready();
    await expect.poll(() => coach.callCount("get_current_position")).toBeGreaterThan(8);
    await coach.button("Stop and see summary").click();
    await expect(coach.report()).toBeVisible();
    await expect(coach.badge()).toHaveText("Stopped");
    await expect(coach.content.locator("#report-avg")).toContainText("Average deviation:");
    await expect(coach.content.locator("#heat li")).toHaveCount(4);
    await expect(coach.content.locator("#heat li").first()).toContainText("Bar 1");
    await expect(coach.content.locator("#histogram li")).toHaveCount(5);
    await expect(coach.content.locator("#histogram li", { hasText: "Not sure (not graded)" })).toBeVisible();
    await expect(coach.content.locator("#highlights li").first()).not.toBeEmpty();
    await expect(coach.button("Practice again")).toBeVisible();
    await expect(coach.button("Ask Claude for tips")).toBeVisible();
    expect(await coach.callCount("stop_monitoring")).toBe(1);
    const polls = await coach.callCount("get_current_position");
    await page.waitForTimeout(500);
    expect(await coach.callCount("get_current_position")).toBe(polls);
  });

  test("Practice again starts the same practice with its original arguments", async ({ page }) => {
    const coach = await CoachFrame.open(page);
    await coach.ready();
    await coach.button("Stop and see summary").click();
    await coach.button("Practice again").click();
    await expect(coach.badge()).toHaveText("Listening");
    const start = (await coach.toolCalls()).filter((c) => c.name === "start_practice");
    expect(start).toHaveLength(1);
    expect(start[0]?.arguments).toMatchObject({ part: "Alto" });
    expect(String(start[0]?.arguments.musicxml)).toContain("<score-partwise");
  });

  test("a session closed by the idle timeout ends the take by itself, with the summary kept", async ({ page }) => {
    const coach = await CoachFrame.open(page, { take: "closed", latency: "30" });
    await expect(coach.report()).toBeVisible({ timeout: 10_000 });
    await expect(coach.content.locator("#report-timeout")).toBeVisible();
    await expect(coach.notice()).toContainText("This practice session has closed");
  });

  test("when the server stops answering the page says so and keeps trying", async ({ page }) => {
    const coach = await CoachFrame.open(page, { take: "lost" });
    await expect(coach.notice()).toContainText("Lost contact with the server", { timeout: 10_000 });
    await expect(coach.badge()).toHaveText("Listening");
    const polls = await coach.callCount("get_current_position");
    await expect.poll(() => coach.callCount("get_current_position")).toBeGreaterThan(polls);
  });
});

test.describe("T1.4 polling in a real page", () => {
  const rate = async (coach: CoachFrame, ms: number) => {
    const before = await coach.callCount("get_current_position");
    await new Promise((resolve) => setTimeout(resolve, ms));
    return (await coach.callCount("get_current_position")) - before;
  };

  test("about 10 Hz when the server answers quickly, backing off when the median round trip passes 80 ms", async ({ page }) => {
    const fast = await CoachFrame.open(page);
    await fast.ready();
    await rate(fast, 500);
    const fastCount = await rate(fast, 1500);

    const slow = await CoachFrame.open(page, { latency: "130" });
    await slow.ready();
    await rate(slow, 1500); // the median needs a few slow replies before it backs off
    const slowCount = await rate(slow, 1500);

    expect(fastCount).toBeGreaterThanOrEqual(11);
    expect(slowCount).toBeLessThanOrEqual(9);
    expect(slowCount).toBeLessThan(fastCount);
  });

  test("no request goes out while the document is hidden, and polling resumes when it is shown", async ({ page }) => {
    const coach = await CoachFrame.open(page);
    await coach.ready();
    await expect.poll(() => coach.callCount("get_current_position")).toBeGreaterThan(3);
    await coach.setHidden(true);
    await page.waitForTimeout(400); // a request in flight may still finish
    const paused = await coach.callCount("get_current_position");
    await page.waitForTimeout(1000);
    expect(await coach.callCount("get_current_position")).toBe(paused);
    await coach.setHidden(false);
    await expect.poll(() => coach.callCount("get_current_position")).toBeGreaterThan(paused + 3);
  });

  test("reduced motion: the cursor does not slide", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    const reduced = await CoachFrame.open(page);
    await reduced.ready();
    await expect(reduced.cursor()).toHaveCSS("transition-duration", "0s");
    await page.emulateMedia({ reducedMotion: "no-preference" });
    const normal = await CoachFrame.open(page);
    await normal.ready();
    await expect(normal.cursor()).toHaveCSS("transition-duration", "0.1s");
  });
});

test.describe("keyboard", () => {
  test("Enter and Space on Stop and Start work as on a mouse", async ({ page }) => {
    const coach = await CoachFrame.open(page, { scenario: "coach-loaded" });
    await coach.ready();
    await coach.button("Start listening").focus();
    await coach.press("Space");
    await expect(coach.badge()).toHaveText("Listening");
    // Focus moved on to Stop when Start disabled itself, so the keyboard user keeps their place.
    expect((await coach.focused()).name).toBe("Stop and see summary");
    await coach.press("Enter");
    await expect(coach.report()).toBeVisible();
  });
});
