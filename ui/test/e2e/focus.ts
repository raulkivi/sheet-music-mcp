// Keyboard focus as a user sees it, read inside one frame. The focus-ring test follows
// raulkivi/agent-cost-analyzer packages/mcp-apps/e2e/support/view-frame.ts (MIT, Raul Kivi).

import type { Frame } from "@playwright/test";

export interface FocusStop {
  /** The focused control's accessible name: its aria-label, else its text. Empty if none is focused. */
  name: string;
  /** Whether it draws a ring (an outline or a shadow). */
  ringVisible: boolean;
}

/** The control that has focus in this frame, if any. */
export function focusStop(frame: Frame): Promise<FocusStop> {
  return frame.evaluate(() => {
    const active = document.activeElement;
    if (!active || active === document.body || !document.hasFocus()) return { name: "", ringVisible: false };
    const style = getComputedStyle(active);
    const ring = (style.outlineStyle !== "none" && Number.parseFloat(style.outlineWidth) > 0) || style.boxShadow !== "none";
    return { name: active.getAttribute("aria-label") ?? active.textContent?.trim() ?? "", ringVisible: ring };
  });
}
