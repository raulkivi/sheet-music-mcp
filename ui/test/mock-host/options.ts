// The mock host's query parameters, parsed once. Pure, so it is unit-tested in Node.
//
//   scenario  inline-long | inline-satb | path-only        (default inline-long); these open with render_to_pdf
//             health-mixed | health-ready | health-empty | health-error   open with health_check (Setup Doctor)
//             practice | practice-empty | practice-unknown-audio   open with synthesize (Practice Player); the host
//             plays the model and runs it on the placeholder synth server
//             abc-edit | abc-edit-file | abc-export | abc-no-original | abc-error   open the ABC Workbench (abc-tools.ts)
//             diff | diff-identical | diff-error   open with compare_scores (Diff Viewer)
//   theme     light | dark                                 (default light)
//   csp       spec | spec-wasm                             (default spec-wasm; see server.mjs)
//   downloads 1 | 0   adds allow-downloads to the sandbox  (default 1)
//   modes     comma list of display modes the host offers  (default inline)
//   width     container width in CSS pixels                (default 1000)
//   server    1 | 0 | real   who answers the view's tools/call (default 1):
//             1 = five placeholder pages for render_page_svg, 0 = no tool at all,
//             real = the real render-mcp over stdio, through window.mcpHostRelay
//             (test/e2e/host-fixture.ts). With real, render_to_pdf runs there too.
//   take      steady | closed | lost    the scripted singing the Practice Coach's pitch tools
//             answer with (default steady; pitch-backend.ts). latency= is their delay in ms.
//             The coach scenarios: coach (a started practice), coach-loaded (microphone still
//             closed), coach-empty (a result with no session), coach-error (start_practice failed).
//   app       a registered app name (apps.config.mjs)   (default score-viewer); the frame loads
//             /app.html?app=<name>, which server.mjs resolves to dist/<name>.html or answers 404
//   clipboard 1 | 0   delegates clipboard-write to the frame, as a host honoring the
//             resource's clipboardWrite permission does (default 1)
//   host      default | claude   style variables the host sends (default default): a partial
//             set, or the recording of Claude Desktop (host-styles.ts); theme picks light or dark

import { ABC_SCENARIOS } from "./abc-tools.ts";
import { HOSTS, type HostName } from "./host-styles.ts";

export const SCENARIOS = [
  "inline-long",
  "inline-satb",
  "path-only",
  "diff",
  "diff-identical",
  "diff-error",
  "health-mixed",
  "health-ready",
  "health-empty",
  "health-error",
  "practice",
  "practice-empty",
  "practice-unknown-audio",
  ...ABC_SCENARIOS,
  "coach",
  "coach-loaded",
  "coach-empty",
  "coach-error",
] as const;
export type ScenarioName = (typeof SCENARIOS)[number];
export const TAKE_NAMES = ["steady", "closed", "lost"] as const;
export type TakeName = (typeof TAKE_NAMES)[number];
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
  app: string;
  take: TakeName;
  /** Delay of every pitch-tool answer, in ms. */
  latencyMs: number;
  clipboard: boolean;
}

// Only the shape is checked here (this module is bundled for the browser); server.mjs checks the registry.
const APP_NAME = /^[a-z][a-z0-9-]*$/;
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
  const app = params.get("app") ?? "score-viewer";
  if (!APP_NAME.test(app)) throw new Error(`Invalid app=${app}; expected a registered app name such as score-viewer`);
  const take = params.get("take") ?? "steady";
  if (!(TAKE_NAMES as readonly string[]).includes(take)) throw new Error(`Unknown take=${take}; expected one of ${TAKE_NAMES.join(", ")}`);
  const latency = Number(params.get("latency") ?? 0);
  if (!Number.isFinite(latency) || latency < 0) throw new Error(`Invalid latency=${params.get("latency")}; expected milliseconds, 0 or more`);
  return {
    scenario: scenario as ScenarioName,
    theme: params.get("theme") === "dark" ? "dark" : "light",
    csp: params.get("csp") ?? "spec-wasm",
    downloads: params.get("downloads") !== "0",
    modes: (params.get("modes") ?? "inline").split(",") as DisplayMode[],
    width: Number(params.get("width") ?? 1000),
    tools,
    host: host as HostName,
    app,
    take: take as TakeName,
    latencyMs: latency,
    clipboard: params.get("clipboard") !== "0",
  };
}
