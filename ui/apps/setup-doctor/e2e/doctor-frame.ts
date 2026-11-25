// Page object for the Setup Doctor in the mock host's iframe, so specs hold no selectors.
// Shape after test/e2e/view-frame.ts (the Score Viewer's).

import type { Frame, FrameLocator, Locator, Page } from "@playwright/test";
import { axeViolations } from "../../../test/e2e/axe.ts";
import { focusStop, type FocusStop } from "../../../test/e2e/focus.ts";
import { openHost } from "../../../test/e2e/host-helpers.ts";
import { frameWidth, scrollsSideways } from "../../../test/e2e/layout.ts";

export type Scenario = "health-mixed" | "health-ready" | "health-empty" | "health-error";

export interface Size {
  name: string;
  /** Container width in CSS pixels. */
  width: number;
}

export const SIZES: Size[] = [
  { name: "1280 px", width: 1280 },
  { name: "360 px", width: 360 },
];

export class DoctorFrame {
  readonly content: FrameLocator;

  private constructor(private readonly page: Page) {
    this.content = page.frameLocator("iframe");
  }

  /** Opens the host on the Setup Doctor with the scenario and any further host options. */
  static async open(page: Page, scenario: Scenario, query: Record<string, string> = {}, size?: Size): Promise<DoctorFrame> {
    if (size) await page.setViewportSize({ width: Math.max(size.width + 80, 440), height: 900 });
    await openHost(page, { app: "setup-doctor", scenario, ...(size ? { width: String(size.width) } : {}), ...query });
    return new DoctorFrame(page);
  }

  button(name: string): Locator {
    return this.content.getByRole("button", { name, exact: true });
  }

  link(name: string): Locator {
    return this.content.getByRole("link", { name, exact: true });
  }

  headline(): Locator {
    return this.content.locator("#headline");
  }

  summary(): Locator {
    return this.content.locator("#summary");
  }

  /** The check rows, worst first. */
  rows(): Locator {
    return this.content.locator("#checks > li");
  }

  async rowNames(): Promise<string[]> {
    return this.rows().locator("strong").allTextContents();
  }

  notice(): Locator {
    return this.content.locator("#notice");
  }

  /** The aria-live region that confirms copying and re-checking. */
  status(): Locator {
    return this.content.locator("#status");
  }

  manualCopy(): Locator {
    return this.content.locator("#manual");
  }

  empty(): Locator {
    return this.content.locator("#empty");
  }

  async press(key: string): Promise<void> {
    await this.page.keyboard.press(key);
  }

  async focused(): Promise<FocusStop> {
    return focusStop(await this.frame());
  }

  /** Moves keyboard focus to the host page, before the view, as if the user had just arrived. */
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

  /** Tabs from before the view through it and returns each stop in order. */
  async tabThrough(limit = 30): Promise<FocusStop[]> {
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

  async tabTo(name: string, limit = 30): Promise<void> {
    await this.focusBeforeView();
    for (let presses = 0; presses < limit; presses++) {
      await this.press("Tab");
      if ((await this.focused()).name === name) return;
    }
    throw new Error(`Tab did not reach "${name}" in ${limit} presses`);
  }

  async scrollsSideways(): Promise<boolean> {
    return scrollsSideways(await this.frame());
  }

  async width(): Promise<number> {
    return frameWidth(await this.frame());
  }

  async axeViolations(): Promise<string[]> {
    return axeViolations(await this.frame());
  }

  private async frame(): Promise<Frame> {
    const frame = await (await this.page.locator("iframe").elementHandle())?.contentFrame();
    if (!frame) throw new Error("The host has no view frame");
    return frame;
  }
}
