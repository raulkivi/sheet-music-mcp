// Stand-in for comparer-mcp's two app-only tools, answered from the fixtures in test/fixtures
// (a real comparison of two 24-bar SATB scores, made with the real server): the same contract
// (structuredContent, error envelope), no Python.

import type { CallToolResult } from "@modelcontextprotocol/client";
import type { ToolBackend } from "./tool-backends.ts";

export const DIFF_ID = "fixture-diff-1";

async function fixture(name: string): Promise<string> {
  return (await fetch(`/fixtures/${name}`)).text();
}

function unknownId(): CallToolResult {
  const envelope = {
    error: "Unknown or expired diff_id",
    error_code: "INVALID_PARAMETER",
    hint: "Run compare_scores again.",
  };
  return { isError: true, content: [{ type: "text", text: JSON.stringify(envelope) }] };
}

async function diffScores(): Promise<CallToolResult> {
  const [reference, target, legend] = await Promise.all([
    fixture("diff-reference-annotated.musicxml"),
    fixture("diff-target-annotated.musicxml"),
    fixture("diff-legend.json"),
  ]);
  return {
    content: [{ type: "text", text: "Both scores sent to the Diff Viewer." }],
    structuredContent: {
      diff_id: DIFF_ID,
      reference_musicxml: reference,
      target_musicxml: target,
      legend: JSON.parse(legend),
    },
  };
}

function exportedScores(): CallToolResult {
  const structuredContent = {
    reference_annotated_musicxml_path: "/tmp/sheet-music-output/scores/annotated-reference_annotated_musicxml.musicxml",
    target_annotated_musicxml_path: "/tmp/sheet-music-output/scores/annotated-target_annotated_musicxml.musicxml",
  };
  return { content: [{ type: "text", text: JSON.stringify(structuredContent) }], structuredContent };
}

export const diffTools: ToolBackend = {
  async callTool(call) {
    const known = call.name === "get_diff_scores" || call.name === "export_diff_scores";
    if (!known) throw new Error(`mock host has no fixture for tool ${call.name}`);
    if (call.arguments?.diff_id !== DIFF_ID) return unknownId();
    return call.name === "get_diff_scores" ? diffScores() : exportedScores();
  },
};
