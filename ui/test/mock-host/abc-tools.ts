// Stand-in for musicxml-abc-mcp's tools in the mock host, answering in the server's contract
// (structuredContent, error envelope). Test data lives here and in scenarios.ts, never in the page.

import type { CallToolResult } from "@modelcontextprotocol/client";
import type { ToolBackend } from "./tool-backends.ts";

export const ABC_SCENARIOS = ["abc-edit", "abc-edit-file", "abc-export", "abc-no-original", "abc-error"] as const;
export type AbcScenario = (typeof ABC_SCENARIOS)[number];

export const isAbcScenario = (name: string): name is AbcScenario => (ABC_SCENARIOS as readonly string[]).includes(name);

export const ABC_ORIGINAL = [
  "X:1",
  "T:Alto line",
  "M:4/4",
  "L:1/8",
  "K:Eb",
  'V:A name="Alto"',
  "|: d2 c2 B2 A2 | G4 z4 |",
  "   c2 d2 e2 f2 | g4 z4 |",
  "   d2 e2 f2 g2 | a4 z4 :|",
].join("\n");

export const ABC_PROPOSED = ABC_ORIGINAL.replace("B2 A2", "B2 G2").replace("a4 z4 :|", "a4 A4 :|");

export const STORED_ABC: CallToolResult = {
  content: [{ type: "text", text: "ABC export fetched for the ABC Workbench." }],
  structuredContent: {
    abc_id: "abc-1",
    abc: ABC_ORIGINAL,
    parts_included: ["P2"],
    warnings: ["Dynamics and complex articulations are not kept in ABC."],
  },
};

const PATH = "/tmp/sheet-music-output/scores/from-abc-1.musicxml";
const MUSICXML = '<score-partwise version="4.0"><part-list/></score-partwise>';

const text = (data: unknown): CallToolResult["content"] => [{ type: "text", text: JSON.stringify(data, null, 2) }];

function toolError(error: string, code: string): CallToolResult {
  return { isError: true, content: text({ error, error_code: code }) };
}

/** A line with a question mark is a syntax error on that line; a missing T: header is a warning. */
function validate(abc: string): CallToolResult {
  const lines = abc.split("\n");
  const errors = lines.flatMap((line, index) => (line.includes("?") ? [`Line ${index + 1}: unexpected "?"`] : []));
  const warnings = lines.some((line) => line.startsWith("T:")) ? [] : ["Missing T: (title) header — recommended by ABC standard."];
  const result = { valid: errors.length === 0, errors, warnings };
  return { content: text(result), structuredContent: result };
}

function convert(abc: string, delivery: "inline" | "path"): CallToolResult {
  if (!abc.split("\n").some((line) => line.startsWith("X:"))) return toolError("ABC has no X: header", "INVALID_INPUT");
  const summary = { warnings: [] as string[], delivery, musicxml_bytes: MUSICXML.length };
  const body = delivery === "inline" ? { musicxml: MUSICXML, warnings: [] } : { musicxml_path: PATH, warnings: [], score_summary: null };
  return { content: text(body), structuredContent: summary };
}

export function abcTools(scenario: AbcScenario): ToolBackend {
  return {
    async callTool(call) {
      const args = call.arguments ?? {};
      switch (call.name) {
        case "get_abc":
          return scenario === "abc-no-original" ? toolError("No ABC export with this id.", "INVALID_PARAMETER") : STORED_ABC;
        case "validate_abc":
          return validate(String(args.abc ?? ""));
        case "abc_to_musicxml":
          return convert(String(args.abc ?? ""), scenario === "abc-edit-file" ? "path" : "inline");
        default:
          throw Object.assign(new Error(`mock host has no fixture for tool ${call.name}`), { code: -32602 });
      }
    },
  };
}
