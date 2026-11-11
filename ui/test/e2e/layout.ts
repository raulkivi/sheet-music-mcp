// Layout facts about one frame's document. The checks follow raulkivi/agent-cost-analyzer
// packages/mcp-apps/e2e/support/view-frame.ts (MIT, Raul Kivi).

import type { Frame } from "@playwright/test";

/** True when the document is wider than its frame, so the user would scroll sideways. */
export function scrollsSideways(frame: Frame): Promise<boolean> {
  return frame.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
}

/** The frame's own width in CSS pixels, to prove a narrow stop really was narrow. */
export function frameWidth(frame: Frame): Promise<number> {
  return frame.evaluate(() => document.documentElement.clientWidth);
}
