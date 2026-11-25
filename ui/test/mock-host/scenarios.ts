// The tool call that opens the view: its arguments (tool-input) and its result (tool-result).
// With placeholder tools the result is a canned render_to_pdf answer; with the real server the
// host plays the model and runs render_to_pdf there, so the view gets the server's own result.
// Practice Player scenarios: the host plays the model and runs synthesize on the backend it is given.

import type { CallToolResult } from "@modelcontextprotocol/client";
import type { ScenarioName } from "./options.ts";
import type { ToolBackend } from "./tool-backends.ts";

export const OPENING_TOOL = "render_to_pdf";
export const HEALTH_TOOL = "health_check";
export const SYNTH_OPENING_TOOL = "synthesize";

export const PDF_RESULT: CallToolResult = {
  content: [{ type: "text", text: "Rendered 5 page(s) to /tmp/sheet-music-output/score.pdf" }],
  structuredContent: { pdf_path: "/tmp/sheet-music-output/score.pdf", page_count: 5, backend: "verovio" },
};

export interface OpeningCall {
  /** The tool the host pretends the model called to open the view. */
  tool: string;
  input: Record<string, unknown>;
  result: CallToolResult;
}

// Health reports in the core's standard shape (sheet_music_mcp_core.health.health_report):
// optional fields are left out, never null.
export const HEALTH_REPORTS = {
  mixed: {
    status: "not_ready",
    checks: [
      { name: "Verovio", status: "ok", version: "4.3.1" },
      {
        name: "Soundfont",
        status: "fail",
        hint: "No General MIDI soundfont was found, so audio cannot be made.",
        fix_snippet: "sudo apt install fluid-soundfont-gm\nexport SYNTH_SOUNDFONT_PATH=/usr/share/sounds/sf2/FluidR3_GM.sf2",
        doc_url: "https://example.org/setup#soundfont",
      },
      { name: "PortAudio", status: "warn", hint: "No input device was found; only the microphone features need one." },
      { name: "FluidSynth", status: "ok", version: "2.3.4" },
    ],
  },
  ready: {
    status: "ready",
    checks: [
      { name: "Verovio", status: "ok", version: "4.3.1" },
      { name: "FluidSynth", status: "ok", version: "2.3.4" },
    ],
  },
  empty: { status: "ready", checks: [] },
} as const;

const HEALTH_SCENARIOS: Partial<Record<ScenarioName, CallToolResult>> = {
  "health-mixed": healthResult(HEALTH_REPORTS.mixed),
  "health-ready": healthResult(HEALTH_REPORTS.ready),
  "health-empty": healthResult(HEALTH_REPORTS.empty),
  "health-error": {
    isError: true,
    content: [{ type: "text", text: JSON.stringify({ error: "The health probe crashed.", error_code: "PROCESSING_ERROR" }) }],
  },
};

function healthResult(report: object): CallToolResult {
  return { content: [{ type: "text", text: "Health report" }], structuredContent: report as Record<string, unknown> };
}

async function fixture(name: string): Promise<string> {
  const res = await fetch(`/fixtures/${name}`);
  return res.text();
}

const INPUTS: Partial<Record<ScenarioName, () => Promise<Record<string, unknown>>>> = {
  "inline-long": async () => ({ musicxml: await fixture("satb-long.musicxml") }),
  "inline-satb": async () => ({ musicxml: await fixture("satb-4bars.musicxml") }),
  "path-only": async () => ({ musicxml_path: "/home/user/scores/satb.musicxml" }),
};

// Relative, so the server resolves it inside its SHEET_MUSIC_OUTPUT_ROOT (the test's own
// folder); without it render-mcp would write to its shared temp folder.
const REAL_OUTPUT_PATH = "score.pdf";

// A four-bar SATB score cut to its own bars with a one-bar count-in: what a singer asks for.
const PRACTICE_INPUT = { measures: [1, 4], count_in_bars: 1 };

const PRACTICE_SCENARIOS: readonly ScenarioName[] = ["practice", "practice-empty", "practice-unknown-audio"];

async function practiceCall(name: ScenarioName, model: ToolBackend | undefined): Promise<OpeningCall> {
  if (!model) throw new Error(`Scenario ${name} needs a tool backend to run synthesize on`);
  const input = { musicxml: await fixture("satb-4bars.musicxml"), ...PRACTICE_INPUT };
  const track = await model.callTool({ name: SYNTH_OPENING_TOOL, arguments: input });
  const tool = SYNTH_OPENING_TOOL;
  if (name === "practice-empty") return { tool, input, result: { content: [{ type: "text", text: "The track was written." }] } };
  if (name === "practice-unknown-audio") {
    const structuredContent = { ...(track.structuredContent as Record<string, unknown>), audio_id: "unknown-audio-id" };
    return { tool, input, result: { ...track, structuredContent } };
  }
  return { tool, input, result: track };
}

/** `model` runs the opening tool for real; without it the canned result stands in. */
export async function openingCall(name: ScenarioName, model?: ToolBackend): Promise<OpeningCall> {
  if (PRACTICE_SCENARIOS.includes(name)) return practiceCall(name, model);
  // Health scenarios are fixed: the Setup Doctor needs no score and the real render-mcp is not asked.
  const health = HEALTH_SCENARIOS[name];
  if (health) return { tool: HEALTH_TOOL, input: {}, result: health };
  const makeInput = INPUTS[name];
  if (!makeInput) throw new Error(`No scenario ${name}`);
  const score = await makeInput();
  if (!model) return { tool: OPENING_TOOL, input: score, result: PDF_RESULT };
  const input = { ...score, output_path: REAL_OUTPUT_PATH };
  return { tool: OPENING_TOOL, input, result: await model.callTool({ name: OPENING_TOOL, arguments: input }) };
}
