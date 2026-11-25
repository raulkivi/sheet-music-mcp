// Page object for the ABC Workbench in the mock host's iframe, so specs hold no selectors.
// The scenarios are the mock host's (test/mock-host/abc-tools.ts).

import { expect, type Frame, type FrameLocator, type Locator, type Page } from "@playwright/test";
import { axeViolations } from "./axe.ts";
import { focusStop, type FocusStop } from "./focus.ts";
import { messages, openHost, type LoggedMessage } from "./host-helpers.ts";
import { frameWidth, scrollsSideways } from "./layout.ts";

export interface Size {
  name: string;
  width: number;
}

export const SIZES: Size[] = [
  { name: "1280 px", width: 1280 },
  { name: "360 px", width: 360 },
];

export class AbcWorkbenchFrame {
  readonly content: FrameLocator;

  private constructor(private readonly page: Page) {
    this.content = page.frameLocator("iframe");
  }

  /** Opens the host on the ABC Workbench and waits until the page has drawn its first state. */
  static async open(page: Page, query: Record<string, string> = {}, width?: number): Promise<AbcWorkbenchFrame> {
    if (width !== undefined) await page.setViewportSize({ width: Math.max(width + 80, 400), height: 900 });
    await openHost(page, { app: "abc-workbench", scenario: "abc-edit", ...(width === undefined ? {} : { width: String(width) }), ...query });
    const view = new AbcWorkbenchFrame(page);
    await expect(view.content.locator("#summary")).not.toHaveText("");
    return view;
  }

  button(name: string): Locator {
    return this.content.getByRole("button", { name, exact: true });
  }

  hunks(): Locator {
    return this.content.locator("article.hunk");
  }

  keepBox(number: number): Locator {
    return this.content.getByRole("checkbox", { name: `Keep change ${number}`, exact: true });
  }

  validation(): Locator {
    return this.content.locator("#validation");
  }

  summary(): Locator {
    return this.content.locator("#summary");
  }

  notice(): Locator {
    return this.content.locator("#notice");
  }

  outcome(): Locator {
    return this.content.locator("#outcome");
  }

  fileChip(): Locator {
    return this.content.locator("#file");
  }

  editor(): Locator {
    return this.content.getByRole("textbox", { name: "Proposed ABC", exact: true });
  }

  /** The gutter line, and with `error` only if it carries an error marker. */
  gutterLine(line: number, error = false): Locator {
    return this.content.locator(`#gutter [data-line="${line}"]${error ? "[data-error]" : ""}`);
  }

  /** Tool calls the page made, by tool name, in order. */
  async toolCalls(name: string): Promise<Record<string, unknown>[]> {
    const calls: LoggedMessage[] = await messages(this.page, "tools/call");
    return calls
      .filter((m) => m.direction === "app->host" && m.params?.name === name)
      .map((m) => (m.params?.arguments ?? {}) as Record<string, unknown>);
  }

  async hostMessages(method: string): Promise<LoggedMessage[]> {
    return (await messages(this.page, method)).filter((m) => m.direction === "app->host");
  }

  async focused(): Promise<FocusStop> {
    return focusStop(await this.frame());
  }

  async press(key: string): Promise<void> {
    await this.page.keyboard.press(key);
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
