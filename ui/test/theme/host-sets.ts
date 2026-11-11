// Host sets the contrast tests run against: what a host sends the view as theme and style
// variables. The Claude sets are the recording in recordings/claude-desktop.json (copied from
// raulkivi/agent-cost-analyzer, see that file); the fallback sets are a host that sends nothing,
// so the kit's own fallbacks (packages/kit/src/theme.ts) apply. Pure data, no file access, so the
// mock host can import the same recording.

import claudeRecording from "./recordings/claude-desktop.json";
import type { Theme } from "./css-vars.ts";

export interface HostSet {
  name: string;
  /** hostContext.theme. */
  theme: Theme;
  /** hostContext.styles.variables, exactly as the host sent them. */
  hostVars: Record<string, string>;
}

/** The variables Claude Desktop sent, the same pairs in a light and a dark session. */
export const CLAUDE_VARIABLES: Readonly<Record<string, string>> = claudeRecording.variables;

export const CLAUDE_SETS: HostSet[] = (["light", "dark"] as const).map((theme) => ({
  name: `Claude ${theme} (recorded)`,
  theme,
  hostVars: { ...CLAUDE_VARIABLES },
}));

export const FALLBACK_SETS: HostSet[] = (["light", "dark"] as const).map((theme) => ({
  name: `Fallback ${theme} (host sends nothing)`,
  theme,
  hostVars: {},
}));

export const ALL_HOST_SETS: HostSet[] = [...FALLBACK_SETS, ...CLAUDE_SETS];
