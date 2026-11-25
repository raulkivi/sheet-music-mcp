// The tool call that opens the view: its arguments (tool-input) and its result (tool-result).
// With placeholder tools the result is a canned render_to_pdf answer; with the real server the
// host plays the model and runs render_to_pdf there, so the view gets the server's own result.

import type { CallToolResult } from "@modelcontextprotocol/client";
import type { ScenarioName } from "./options.ts";
import type { ToolBackend } from "./tool-backends.ts";

export const OPENING_TOOL = "render_to_pdf";
export const DIFF_OPENING_TOOL = "compare_scores";

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

const DIFF_INPUT = { reference_path: "/home/user/scores/v1.musicxml", target_path: "/home/user/scores/v2.musicxml", detail: "full" };

const INPUTS: Record<ScenarioName, () => Promise<Record<string, unknown>>> = {
  diff: async () => DIFF_INPUT,
  "diff-identical": async () => DIFF_INPUT,
  "diff-error": async () => DIFF_INPUT,
  "inline-long": async () => ({ musicxml: await fixture("satb-long.musicxml") }),
  "inline-satb": async () => ({ musicxml: await fixture("satb-4bars.musicxml") }),
  "path-only": async () => ({ musicxml_path: "/home/user/scores/satb.musicxml" }),
};

// Relative, so the server resolves it inside its SHEET_MUSIC_OUTPUT_ROOT (the test's own
// folder); without it render-mcp would write to its shared temp folder.
const REAL_OUTPUT_PATH = "score.pdf";

/** The tool whose call opens the scenario's view. */
export function openingToolName(name: ScenarioName): string {
  return name.startsWith("diff") ? DIFF_OPENING_TOOL : OPENING_TOOL;
}

const DIFF_ERROR: CallToolResult = {
  isError: true,
  content: [{ type: "text", text: '{"error":"reference_xml: not MusicXML","error_code":"INVALID_INPUT"}' }],
};

async function diffResult(name: ScenarioName): Promise<CallToolResult> {
  if (name === "diff-error") return DIFF_ERROR;
  const data = JSON.parse(await fixture("diff-result.json"));
  const structuredContent = name === "diff-identical" ? { ...data, similarity_score: 1, changes: [], count: 0 } : data;
  return { content: [{ type: "text", text: JSON.stringify(structuredContent) }], structuredContent };
}

/** `model` runs the opening tool for real; without it the canned result stands in. */
export async function openingCall(name: ScenarioName, model?: ToolBackend): Promise<OpeningCall> {
  const score = await INPUTS[name]();
  if (name.startsWith("diff")) return { input: score, result: await diffResult(name) };
  if (!model) return { input: score, result: PDF_RESULT };
  const input = { ...score, output_path: REAL_OUTPUT_PATH };
  return { input, result: await model.callTool({ name: OPENING_TOOL, arguments: input }) };
}
