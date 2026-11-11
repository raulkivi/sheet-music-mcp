// The mock host's query parameters, parsed once. Pure, so it is unit-tested in Node.
//
//   scenario  inline-long | inline-satb | path-only        (default inline-long)
//   theme     light | dark                                 (default light)
//   csp       spec | spec-wasm                             (default spec-wasm; see server.mjs)
//   downloads 1 | 0   adds allow-downloads to the sandbox  (default 1)
//   modes     comma list of display modes the host offers  (default inline)
//   width     container width in CSS pixels                (default 1000)
//   server    1 | 0 | real   who answers the view's tools/call (default 1):
//             1 = five placeholder pages for render_page_svg, 0 = no tool at all,
//             real = the real render-mcp over stdio, through window.mcpHostRelay
//             (test/e2e/host-fixture.ts). With real, render_to_pdf runs there too.
//   host      default | claude   style variables the host sends (default default): a partial
//             set, or the recording of Claude Desktop (host-styles.ts); theme picks light or dark

import { HOSTS, type HostName } from "./host-styles.ts";

export const SCENARIOS = ["inline-long", "inline-satb", "path-only"] as const;
export type ScenarioName = (typeof SCENARIOS)[number];
export type ToolsMode = "placeholder" | "none" | "real";
export type DisplayMode = "inline" | "fullscreen" | "pip";

export interface HostOptions {
  scenario: ScenarioName;
  theme: "light" | "dark";
  csp: string;
  downloads: boolean;
  modes: DisplayMode[];
  width: number;
  tools: ToolsMode;
  host: HostName;
}

const TOOLS: Record<string, ToolsMode> = { "1": "placeholder", "0": "none", real: "real" };

export function hostOptions(search: string): HostOptions {
  const params = new URLSearchParams(search);
  const scenario = params.get("scenario") ?? "inline-long";
  if (!(SCENARIOS as readonly string[]).includes(scenario)) {
    throw new Error(`Unknown scenario ${scenario}; expected one of ${SCENARIOS.join(", ")}`);
  }
  const server = params.get("server") ?? "1";
  const tools = TOOLS[server];
  if (!tools) throw new Error(`Unknown server=${server}; expected 1, 0 or real`);
  const host = params.get("host") ?? "default";
  if (!(HOSTS as readonly string[]).includes(host)) throw new Error(`Unknown host=${host}; expected ${HOSTS.join(" or ")}`);
  return {
    scenario: scenario as ScenarioName,
    theme: params.get("theme") === "dark" ? "dark" : "light",
    csp: params.get("csp") ?? "spec-wasm",
    downloads: params.get("downloads") !== "0",
    modes: (params.get("modes") ?? "inline").split(",") as DisplayMode[],
    width: Number(params.get("width") ?? 1000),
    tools,
    host: host as HostName,
  };
}
