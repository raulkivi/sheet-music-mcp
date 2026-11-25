// The tool call that opens the view: its arguments (tool-input) and its result (tool-result).
// With placeholder tools the result is a canned render_to_pdf answer; with the real server the
// host plays the model and runs render_to_pdf there, so the view gets the server's own result.

import type { CallToolResult } from "@modelcontextprotocol/client";
import type { ScenarioName } from "./options.ts";
import { SESSION_VIEW } from "./pitch-backend.ts";
import { toolError, type ToolBackend } from "./tool-backends.ts";

const OPENING_TOOL = "render_to_pdf";

export const PDF_RESULT: CallToolResult = {
  content: [{ type: "text", text: "Rendered 5 page(s) to /tmp/sheet-music-output/score.pdf" }],
  structuredContent: { pdf_path: "/tmp/sheet-music-output/score.pdf", page_count: 5, backend: "verovio" },
};

export interface OpeningCall {
  input: Record<string, unknown>;
  result: CallToolResult;
}

async function fixture(name: string): Promise<string> {
  const res = await fetch(`/fixtures/${name}`);
  return res.text();
}

const COACH_INPUT = async () => ({ musicxml: await fixture("satb-4bars.musicxml"), part: "Alto" });

const INPUTS: Record<ScenarioName, () => Promise<Record<string, unknown>>> = {
  "inline-long": async () => ({ musicxml: await fixture("satb-long.musicxml") }),
  "inline-satb": async () => ({ musicxml: await fixture("satb-4bars.musicxml") }),
  "path-only": async () => ({ musicxml_path: "/home/user/scores/satb.musicxml" }),
  coach: COACH_INPUT,
  "coach-loaded": COACH_INPUT,
  "coach-empty": async () => ({}),
  "coach-error": COACH_INPUT,
};

const START_PRACTICE = "start_practice";

/** The tool a scenario plays the model calling to open the view. */
export function openingTool(name: ScenarioName): string {
  return name.startsWith("coach") ? START_PRACTICE : OPENING_TOOL;
}

const COACH_RESULTS: Partial<Record<ScenarioName, CallToolResult>> = {
  coach: { content: [{ type: "text", text: JSON.stringify({ ...SESSION_VIEW, status: "started" }, null, 2) }], structuredContent: SESSION_VIEW },
  "coach-loaded": { content: [{ type: "text", text: JSON.stringify(SESSION_VIEW, null, 2) }], structuredContent: SESSION_VIEW },
  "coach-empty": { content: [{ type: "text", text: "{}" }] },
  "coach-error": toolError("Could not open the microphone.", "PROCESSING_FAILED"),
};

// Relative, so the server resolves it inside its SHEET_MUSIC_OUTPUT_ROOT (the test's own
// folder); without it render-mcp would write to its shared temp folder.
const REAL_OUTPUT_PATH = "score.pdf";

/** `model` runs the opening tool for real; without it the canned result stands in. */
export async function openingCall(name: ScenarioName, model?: ToolBackend): Promise<OpeningCall> {
  const score = await INPUTS[name]();
  const coach = COACH_RESULTS[name];
  if (coach) return { input: score, result: coach };
  if (!model) return { input: score, result: PDF_RESULT };
  const input = { ...score, output_path: REAL_OUTPUT_PATH };
  return { input, result: await model.callTool({ name: OPENING_TOOL, arguments: input }) };
}
