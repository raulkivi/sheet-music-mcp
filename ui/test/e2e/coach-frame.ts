// Page object for the Practice Coach in the mock host's iframe: selectors and waits live here, so
// the specs read as the plan's rows do. Same shape as view-frame.ts (the Score Viewer's).

import { expect, type Frame, type FrameLocator, type Locator, type Page } from "@playwright/test";
import { axeViolations } from "./axe.ts";
import { focusStop, type FocusStop } from "./focus.ts";
import { openHost, messages } from "./host-helpers.ts";
import { frameWidth, scrollsSideways } from "./layout.ts";
import type { Size } from "./view-frame.ts";

export type CoachControl = "Start listening" | "Stop and see summary" | "Server microphone" | "Practice again" | "Ask Claude for tips";

/** The score's SVG notation: not chrome, and not markup the page writes (plan R4). */
const NOTATION = "#score svg";

/** One change of what the singer sees, recorded in the page by `recordReadings`. */
export interface RecordedReading {
  measure: number;
  beat: number;
  status: string;
  /** The status pill's word and tone class, and the cents text, as shown at that moment. */
  label: string;
  pillClass: string;
  centsText: string;
  tone: string;
  needleHidden: boolean;
  needleColor: string;
  cursorIndex: string | undefined;
  cursorHidden: boolean;
  cursorHeight: number;
}

export class CoachFrame {
  readonly content: FrameLocator;

  private constructor(private readonly page: Page) {
    this.content = page.frameLocator("iframe");
  }

  /** Opens the host on the Practice Coach (`app=practice-coach`) with the query, sized to `size`. */
  static async open(page: Page, query: Record<string, string> = {}, size?: Size): Promise<CoachFrame> {
    if (size) await page.setViewportSize(size.viewport);
    const sized = size?.width === undefined ? query : { ...query, width: String(size.width) };
    await openHost(page, { app: "practice-coach", scenario: "coach", ...sized });
    return new CoachFrame(page);
  }

  button(name: CoachControl): Locator {
    return this.content.getByRole("button", { name, exact: true });
  }

  microphone(): Locator {
    return this.content.getByRole("radio", { name: "Server microphone", exact: true });
  }

  browserMicrophone(): Locator {
    return this.content.getByRole("radio", { name: /This device's browser/ });
  }

  notation(): Locator {
    return this.content.locator(NOTATION).first();
  }

  notice(): Locator {
    return this.content.locator("#notice");
  }

  empty(): Locator {
    return this.content.locator("#empty");
  }

  status(): Locator {
    return this.content.locator("#status");
  }

  centsText(): Locator {
    return this.content.locator("#cents-text");
  }

  meter(): Locator {
    return this.content.locator("#meter");
  }

  needle(): Locator {
    return this.content.locator("#needle");
  }

  cursor(): Locator {
    return this.content.locator("#cursor");
  }

  where(): Locator {
    return this.content.locator("#where");
  }

  report(): Locator {
    return this.content.locator("#report");
  }

  badge(): Locator {
    return this.content.locator("#listen-badge");
  }

  /** Waits for the score to be drawn, so the page is past its opening. */
  async ready(): Promise<void> {
    await expect(this.notation()).toBeVisible();
  }

  /** Every `tools/call` the page has made, by tool name, in order. */
  async toolCalls(): Promise<{ name: string; arguments: Record<string, unknown> }[]> {
    const calls = await messages(this.page, "tools/call");
    return calls.map((m) => m.params as { name: string; arguments: Record<string, unknown> });
  }

  async callCount(tool: string): Promise<number> {
    return (await this.toolCalls()).filter((c) => c.name === tool).length;
  }

  /**
   * Starts recording every change to what the singer sees (bar, status, meter color, needle,
   * cursor) inside the page. Call before the take starts; read with `recorded()`.
   */
  async recordReadings(): Promise<void> {
    await (await this.frame()).evaluate(() => {
      const w = window as unknown as { __readings: unknown[] };
      w.__readings = [];
      const el = (id: string) => document.getElementById(id) as HTMLElement;
      const snapshot = () => {
        const where = el("where");
        const cursor = el("cursor");
        const needle = el("needle");
        const last = w.__readings.at(-1) as { measure: number; beat: number; status: string } | undefined;
        const reading = {
          measure: Number(where.dataset.measure),
          beat: Number(where.dataset.beat),
          status: el("status").dataset.status ?? "",
          label: el("status").textContent ?? "",
          pillClass: el("status").className,
          centsText: el("cents-text").textContent ?? "",
          tone: el("meter").dataset.tone ?? "",
          needleHidden: needle.hidden,
          needleColor: getComputedStyle(needle).backgroundColor,
          cursorIndex: cursor.dataset.index,
          cursorHidden: cursor.hidden,
          cursorHeight: cursor.getBoundingClientRect().height,
        };
        if (Number.isNaN(reading.measure)) return;
        if (!last || last.measure !== reading.measure || last.beat !== reading.beat || last.status !== reading.status) w.__readings.push(reading);
      };
      new MutationObserver(snapshot).observe(el("meter-panel"), { attributes: true, subtree: true, characterData: true, childList: true });
      new MutationObserver(snapshot).observe(el("where"), { attributes: true });
    });
  }

  async recorded(): Promise<RecordedReading[]> {
    return (await this.frame()).evaluate(() => (window as unknown as { __readings: RecordedReading[] }).__readings);
  }

  /** Overrides the frame's document visibility, as a host hiding the tab would, and tells the page. */
  async setHidden(hidden: boolean): Promise<void> {
    await (await this.frame()).evaluate((value) => {
      Object.defineProperty(document, "hidden", { configurable: true, get: () => value });
      document.dispatchEvent(new Event("visibilitychange"));
    }, hidden);
  }

  async focusBeforeView(): Promise<void> {
    await this.page.evaluate(() => {
      (document.activeElement as HTMLElement | null)?.blur();
      const start = document.createElement("button");
      start.textContent = "Before the view";
      document.body.prepend(start);
      start.focus();
      start.addEventListener("blur", () => start.remove(), { once: true });
    });
  }

  async focused(): Promise<FocusStop> {
    return focusStop(await this.frame());
  }

  async press(key: string): Promise<void> {
    await this.page.keyboard.press(key);
  }

  /** Tabs from before the view through it and returns each stop in order. */
  async tabThrough(limit = 12): Promise<FocusStop[]> {
    await this.focusBeforeView();
    const stops: FocusStop[] = [];
    for (let presses = 0; presses < limit; presses++) {
      await this.press("Tab");
      const stop = await this.focused();
      if (stop.name === "" || stops.some((seen) => seen.name === stop.name)) return stops;
      stops.push(stop);
    }
    throw new Error(`Tab did not leave the view in ${limit} presses`);
  }

  async scrollsSideways(): Promise<boolean> {
    return scrollsSideways(await this.frame());
  }

  async width(): Promise<number> {
    return frameWidth(await this.frame());
  }

  /** WCAG 2.2 A/AA for the chrome around the score; the notation is excluded (plan R4). */
  async axeViolations(): Promise<string[]> {
    return axeViolations(await this.frame(), { exclude: [NOTATION] });
  }

  private async frame(): Promise<Frame> {
    const frame = await (await this.page.locator("iframe").elementHandle())?.contentFrame();
    if (!frame) throw new Error("The host has no view frame");
    return frame;
  }
}
