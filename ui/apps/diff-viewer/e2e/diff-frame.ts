// Page object for the Diff Viewer in the mock host's iframe: specs read as the plan's rows do and
// hold no selectors.

import { expect, type Frame, type FrameLocator, type Locator, type Page } from "@playwright/test";
import { axeViolations } from "../../../test/e2e/axe.ts";
import { focusStop, type FocusStop } from "../../../test/e2e/focus.ts";
import { openHost } from "../../../test/e2e/host-helpers.ts";
import { frameWidth, scrollsSideways } from "../../../test/e2e/layout.ts";

export const SIZES = [
  { name: "1280 px", width: 1280, viewport: { width: 1360, height: 900 } },
  { name: "360 px", width: 360, viewport: { width: 1280, height: 900 } },
] as const;

export type Size = (typeof SIZES)[number];

export interface Box {
  top: number;
  bottom: number;
  left: number;
  right: number;
}

/** The score notation: not chrome, and not markup the page writes (plan R4). */
const NOTATION = ".pane-body > svg";

export class DiffViewerFrame {
  readonly content: FrameLocator;

  private constructor(private readonly page: Page) {
    this.content = page.frameLocator("iframe");
  }

  static async open(page: Page, query: Record<string, string> = {}, size?: Size): Promise<DiffViewerFrame> {
    if (size) await page.setViewportSize(size.viewport);
    await openHost(page, { app: "diff-viewer", scenario: "diff", ...query, ...(size ? { width: String(size.width) } : {}) });
    return new DiffViewerFrame(page);
  }

  /** Waits until both panes have drawn their scores. */
  async scoresDrawn(): Promise<void> {
    await expect(this.content.locator(`#pane-reference > svg`).first()).toBeVisible();
    await expect(this.content.locator(`#pane-target > svg`).first()).toBeVisible();
  }

  headline(): Locator {
    return this.content.locator("#headline");
  }

  notice(): Locator {
    return this.content.locator("#notice");
  }

  changes(): Locator {
    return this.content.locator("#changes button");
  }

  change(text: string | RegExp): Locator {
    return this.content.locator("#changes button").filter({ hasText: text });
  }

  filter(label: string | RegExp): Locator {
    return this.content.locator("#filters button").filter({ hasText: label });
  }

  selection(): Locator {
    return this.content.locator("#selection");
  }

  pane(which: "reference" | "target"): Locator {
    return this.content.locator(`#pane-${which}`);
  }

  highlight(which: "reference" | "target"): Locator {
    return this.pane(which).locator(".measure-highlight");
  }

  button(name: string): Locator {
    return this.content.getByRole("button", { name, exact: true });
  }

  tab(name: "Scores" | "Report"): Locator {
    return this.content.getByRole("tab", { name });
  }

  report(): Locator {
    return this.content.locator("#report");
  }

  chips(): Locator {
    return this.content.locator("#exported li");
  }

  /** Bounding boxes of the pane's visible area and of its highlight, in the iframe's viewport. */
  async boxes(which: "reference" | "target"): Promise<{ pane: Box; mark: Box }> {
    const read = (el: Element | null): Box => {
      const r = el!.getBoundingClientRect();
      return { top: r.top, bottom: r.bottom, left: r.left, right: r.right };
    };
    const pane = await this.pane(which).evaluate(read);
    const mark = await this.highlight(which).evaluate(read);
    return { pane, mark };
  }

  async scrollTop(which: "reference" | "target"): Promise<number> {
    return this.pane(which).evaluate((el) => el.scrollTop);
  }

  /** Keyboard focus to the host page, before the view. */
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

  async scrollsSideways(): Promise<boolean> {
    return scrollsSideways(await this.frame());
  }

  async width(): Promise<number> {
    return frameWidth(await this.frame());
  }

  async axeViolations(): Promise<string[]> {
    return axeViolations(await this.frame(), { exclude: [NOTATION] });
  }

  private async frame(): Promise<Frame> {
    const frame = await (await this.page.locator("iframe").elementHandle())?.contentFrame();
    if (!frame) throw new Error("The host has no view frame");
    return frame;
  }
}
