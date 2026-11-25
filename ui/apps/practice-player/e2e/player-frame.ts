// Page object for the Practice Player in the mock host's iframe, so specs hold no selectors.

import { expect, type FrameLocator, type Locator, type Page } from "@playwright/test";
import { messages, openHost, type LoggedMessage } from "../../../test/e2e/host-helpers.ts";

export type Scenario = "practice" | "practice-empty" | "practice-unknown-audio";

export interface Size {
  name: string;
  /** Container width in CSS pixels. */
  width: number;
  viewport: { width: number; height: number };
}

export const SIZES: Size[] = [
  { name: "1280 px", width: 1280, viewport: { width: 1360, height: 900 } },
  { name: "360 px", width: 360, viewport: { width: 1280, height: 900 } },
];

export type Button = "Play" | "Pause" | "Restart" | "Count-in" | "Starting pitches";

export class PlayerFrame {
  readonly content: FrameLocator;

  private constructor(readonly page: Page) {
    this.content = page.frameLocator("iframe");
  }

  static async open(
    page: Page,
    query: Record<string, string> = {},
    scenario: Scenario = "practice",
    size?: Size,
  ): Promise<PlayerFrame> {
    if (size) await page.setViewportSize(size.viewport);
    await openHost(page, { app: "practice-player", scenario, ...(size ? { width: String(size.width) } : {}), ...query });
    return new PlayerFrame(page);
  }

  /** Opens the host and waits until the player has the track and the score. */
  static async ready(page: Page, query: Record<string, string> = {}, size?: Size): Promise<PlayerFrame> {
    const player = await PlayerFrame.open(page, query, "practice", size);
    await player.waitReady();
    return player;
  }

  async waitReady(): Promise<void> {
    await expect(this.content.locator("#state")).toHaveText("Ready");
    await expect(this.content.locator("#score svg").first()).toBeVisible();
  }

  button(name: Button): Locator {
    return this.content.getByRole("button", { name, exact: true });
  }

  loop(): Locator {
    return this.content.getByRole("button", { name: /^Loop/ });
  }

  solo(part: string): Locator {
    return this.content.getByRole("button", { name: `Solo ${part}`, exact: true });
  }

  mute(part: string): Locator {
    return this.content.getByRole("button", { name: `Mute ${part}`, exact: true });
  }

  volume(part: string): Locator {
    return this.content.getByRole("slider", { name: `${part} volume` });
  }

  tempo(): Locator {
    return this.content.getByRole("slider", { name: "Speed" });
  }

  seek(): Locator {
    return this.content.getByRole("slider", { name: "Position" });
  }

  preset(): Locator {
    return this.content.getByLabel("Preset", { exact: true });
  }

  focusPart(): Locator {
    return this.content.getByLabel("My part");
  }

  timbre(): Locator {
    return this.content.getByLabel("Sound");
  }

  notice(): Locator {
    return this.content.locator("#notice");
  }

  position(): Locator {
    return this.content.locator("#position");
  }

  score(): Locator {
    return this.content.locator("#score");
  }

  status(): Locator {
    return this.content.locator("#status");
  }

  /** The tool calls the page made, in order: name and arguments. */
  async toolCalls(): Promise<{ name: string; arguments: Record<string, unknown> }[]> {
    const calls = await messages(this.page, "tools/call");
    return calls
      .filter((message: LoggedMessage) => message.direction === "app->host")
      .map((message) => message.params as { name: string; arguments: Record<string, unknown> });
  }

  async callNames(): Promise<string[]> {
    return (await this.toolCalls()).map((call) => call.name);
  }

  async calls(name: string): Promise<Record<string, unknown>[]> {
    return (await this.toolCalls()).filter((call) => call.name === name).map((call) => call.arguments);
  }

  /** The audio element's state, read in the frame. */
  audioState(): Promise<{ duration: number; currentTime: number; paused: boolean; playbackRate: number; preservesPitch: boolean }> {
    return this.page.frames()[1]!.evaluate(() => {
      const audio = document.getElementById("audio") as HTMLAudioElement;
      return {
        duration: audio.duration,
        currentTime: audio.currentTime,
        paused: audio.paused,
        playbackRate: audio.playbackRate,
        preservesPitch: audio.preservesPitch,
      };
    });
  }
}
