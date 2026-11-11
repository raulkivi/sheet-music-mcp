// Page object for the Score Viewer in the mock host's iframe, so specs read as the plan's rows do
// and hold no selectors. Shape after raulkivi/agent-cost-analyzer
// packages/mcp-apps/e2e/support/view-frame.ts (MIT, Raul Kivi).

import { expect, type Frame, type FrameLocator, type Locator, type Page } from "@playwright/test";
import { axeViolations } from "./axe.ts";
import { focusStop, type FocusStop } from "./focus.ts";
import { openHost } from "./host-helpers.ts";
import { frameWidth, scrollsSideways } from "./layout.ts";

export type Control =
  | "Previous page"
  | "Next page"
  | "Zoom out"
  | "Zoom in"
  | "Download SVG"
  | "Fullscreen"
  | "Exit fullscreen"
  | "Ask the assistant to open it";

/** A size the view is checked at (U4): a container width in the host, or the host's fullscreen. */
export interface Size {
  name: string;
  /** Container width in CSS pixels; absent for fullscreen. */
  width?: number;
  /** The browser window, wide enough that the host never narrows the container. */
  viewport: { width: number; height: number };
}

export const SIZES: Size[] = [
  { name: "1280 px", width: 1280, viewport: { width: 1360, height: 900 } },
  { name: "360 px", width: 360, viewport: { width: 1280, height: 900 } },
  { name: "fullscreen", viewport: { width: 1280, height: 800 } },
];

/** The score's SVG notation: not chrome, and not markup the page writes (plan R4). */
const NOTATION = "#score > svg";

export class ScoreViewerFrame {
  readonly content: FrameLocator;

  private constructor(private readonly page: Page) {
    this.content = page.frameLocator("iframe");
  }

  /** Opens the host with the query (test/mock-host/options.ts), sized to `size`. */
  static async open(page: Page, query: Record<string, string> = {}, size?: Size): Promise<ScoreViewerFrame> {
    if (size) await page.setViewportSize(size.viewport);
    const sized = size === undefined ? query : size.width === undefined ? { ...query, modes: "inline,fullscreen" } : { ...query, width: String(size.width) };
    await openHost(page, sized);
    const view = new ScoreViewerFrame(page);
    if (size && size.width === undefined) await view.enterFullscreen();
    return view;
  }

  button(name: Control): Locator {
    return this.content.getByRole("button", { name, exact: true });
  }

  async click(name: Control): Promise<void> {
    await this.button(name).click();
  }

  /** The first rendered score page. */
  scorePage(): Locator {
    return this.content.locator(NOTATION).first();
  }

  pageLabel(): Locator {
    return this.content.locator("#page-label");
  }

  zoomLabel(): Locator {
    return this.content.locator("#zoom-label");
  }

  notice(): Locator {
    return this.content.locator("#notice");
  }

  downloadFallback(): Locator {
    return this.content.locator("#fallback");
  }

  async enterFullscreen(): Promise<void> {
    await this.click("Fullscreen");
    await expect(this.button("Exit fullscreen")).toBeVisible();
    await expect.poll(() => this.width()).toBeGreaterThanOrEqual(this.page.viewportSize()!.width - 20);
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

  /** The control with focus in the view. */
  async focused(): Promise<FocusStop> {
    return focusStop(await this.frame());
  }

  async press(key: string): Promise<void> {
    await this.page.keyboard.press(key);
  }

  /** Tabs from before the view through it, as a keyboard user does, and returns each stop in order. */
  async tabThrough(limit = 20): Promise<FocusStop[]> {
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

  /** Tabs until the control named `name` has focus. */
  async tabTo(name: Control, limit = 20): Promise<void> {
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
