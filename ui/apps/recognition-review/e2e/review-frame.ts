// Page object for the Recognition Review in the mock host's iframe: specs read as the plan's rows
// do and hold no selectors. Shape after the Diff Viewer's.

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

/** The score notation: not chrome, and not markup the page writes (plan R4). */
const NOTATION = "#score > svg";

export class ReviewFrame {
  readonly content: FrameLocator;

  private constructor(private readonly page: Page) {
    this.content = page.frameLocator("iframe");
  }

  static async open(page: Page, query: Record<string, string> = {}, size?: Size): Promise<ReviewFrame> {
    if (size) await page.setViewportSize(size.viewport);
    await openHost(page, { app: "recognition-review", scenario: "review", ...query, ...(size ? { width: String(size.width) } : {}) });
    return new ReviewFrame(page);
  }

  /** Waits until the score is drawn and the photo has loaded. */
  async drawn(): Promise<void> {
    await expect(this.score().locator("svg").first()).toBeVisible();
    await expect(this.photo()).toBeVisible();
  }

  headline(): Locator {
    return this.content.locator("#headline");
  }

  advice(): Locator {
    return this.content.locator("#advice");
  }

  notices(): Locator {
    return this.content.locator("#notices");
  }

  status(): Locator {
    return this.content.locator("#status");
  }

  engine(): Locator {
    return this.content.locator("#engine");
  }

  issues(): Locator {
    return this.content.locator("#issues button");
  }

  issue(text: string | RegExp): Locator {
    return this.issues().filter({ hasText: text });
  }

  noIssues(): Locator {
    return this.content.locator("#no-issues");
  }

  selection(): Locator {
    return this.content.locator("#selection");
  }

  photo(): Locator {
    return this.content.locator("#photo-img");
  }

  photoPane(): Locator {
    return this.content.locator("#photo");
  }

  score(): Locator {
    return this.content.locator("#score");
  }

  staves(): Locator {
    return this.score().locator("g.staff");
  }

  highlight(): Locator {
    return this.score().locator(".measure-highlight");
  }

  button(name: string): Locator {
    return this.content.getByRole("button", { name, exact: true });
  }

  /** Bounding boxes of the score's visible area and of its highlight, in the iframe's viewport. */
  async boxes(): Promise<{ pane: DOMRectLike; mark: DOMRectLike }> {
    const read = (el: Element | null): DOMRectLike => {
      const r = el!.getBoundingClientRect();
      return { top: r.top, bottom: r.bottom, left: r.left, right: r.right };
    };
    return { pane: await this.score().evaluate(read), mark: await this.highlight().evaluate(read) };
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

interface DOMRectLike {
  top: number;
  bottom: number;
  left: number;
  right: number;
}
