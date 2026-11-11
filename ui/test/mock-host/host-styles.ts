// The style variables the mock host sends, by host. "default" is a partial set, as many hosts
// send (the type lists every variable, the protocol requires none); "claude" is the recording of
// Claude Desktop (test/theme/recordings/claude-desktop.json), light-dark() values and all, which
// the theme picks the branch of. Pure, so it is unit-tested in Node.

import { CLAUDE_VARIABLES } from "../theme/host-sets.ts";

export type HostName = "default" | "claude";
export const HOSTS: readonly HostName[] = ["default", "claude"];

export function hostStyleVariables(host: HostName, theme: "light" | "dark"): Record<string, string> {
  if (host === "claude") return { ...CLAUDE_VARIABLES };
  return theme === "dark" ? { "--color-background-primary": "#131314", "--color-text-primary": "#f2f2f2" } : {};
}
