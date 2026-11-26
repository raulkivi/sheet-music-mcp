// Stand-in for omr-mcp's tools in the mock host (Recognition Review), answering in the server's
// contract (structuredContent, error envelope): a flattened one-part oemer result with warnings,
// and a clean four-part Audiveris result. Fixtures are in test/fixtures (recognition-*); the
// score and the photo are read from there. Test data lives here and in scenarios.ts, never in the page.

import type { CallToolResult } from "@modelcontextprotocol/client";
import type { ToolBackend } from "./tool-backends.ts";

export const OMR_SCENARIOS = ["review", "review-clean", "review-error"] as const;
export type OmrScenario = (typeof OMR_SCENARIOS)[number];

export const isOmrScenario = (name: string): name is OmrScenario => (OMR_SCENARIOS as readonly string[]).includes(name);

export const OMR_OPENING_TOOL = "recognize_sheet";
export const OMR_INPUT = { image: "/home/user/scans/page1.png" };

export const OEMER_JOB = "job-oemer";
export const AUDIVERIS_JOB = "job-audiveris";

const text = (data: unknown): CallToolResult["content"] => [{ type: "text", text: JSON.stringify(data, null, 2) }];

function recognition(engine: "oemer" | "audiveris"): CallToolResult {
  const flattened = engine === "oemer";
  const parts = flattened ? 1 : 4;
  const structuredContent = {
    job_id: flattened ? OEMER_JOB : AUDIVERIS_JOB,
    metadata: {
      engine,
      staves_detected: parts,
      measures: 4,
      processing_time_ms: flattened ? 41250 : 98400,
      page_count: 1,
      staff_systems_estimate: 4,
    },
    pages: [{ index: 1, staves_detected: parts, measures: 4, has_preview: true }],
    // The codes and messages are the ones recognition_warnings.py builds.
    warnings: flattened
      ? [
          { code: "LOW_RESOLUTION", severity: "warning", message: "Image is 150 DPI; 300 or more gives better recognition." },
          {
            code: "PARTS_FEWER_THAN_STAVES",
            severity: "info",
            message: "1 part recognized but the page has 4 staves per system; voices may be merged",
          },
          { code: "EMPTY_MEASURE", severity: "warning", message: "Measure 3 has no notes or rests", measure: 3, part: "P1" },
        ]
      : [],
  };
  return { content: text({ musicxml: "<score-partwise/>", metadata: structuredContent.metadata }), structuredContent };
}

export const OEMER_RESULT = recognition("oemer");
export const AUDIVERIS_RESULT = recognition("audiveris");

export const OMR_OPENING: Record<OmrScenario, CallToolResult> = {
  review: OEMER_RESULT,
  "review-clean": AUDIVERIS_RESULT,
  "review-error": toolError("The image could not be read.", "INVALID_INPUT"),
};

function toolError(error: string, code: string): CallToolResult {
  return { isError: true, content: text({ error, error_code: code }) };
}

async function fixtureBytes(name: string): Promise<Uint8Array> {
  return new Uint8Array(await (await fetch(`/fixtures/${name}`)).arrayBuffer());
}

const base64 = (bytes: Uint8Array): string => btoa(String.fromCharCode(...bytes));

async function recognizedScore(jobId: unknown): Promise<CallToolResult> {
  if (jobId !== OEMER_JOB && jobId !== AUDIVERIS_JOB) return toolError("Unknown or expired job_id", "INVALID_PARAMETER");
  const name = jobId === OEMER_JOB ? "recognition-flattened.musicxml" : "satb-4bars.musicxml";
  const musicxml = await (await fetch(`/fixtures/${name}`)).text();
  return {
    content: [{ type: "text", text: "Recognized score fetched for the Recognition Review." }],
    structuredContent: { job_id: jobId, musicxml },
  };
}

async function sourcePreview(args: Record<string, unknown>): Promise<CallToolResult> {
  if (args.job_id !== OEMER_JOB && args.job_id !== AUDIVERIS_JOB) return toolError("Unknown or expired job_id", "INVALID_PARAMETER");
  const page = Number(args.page ?? 1);
  if (page !== 1) return toolError(`Page ${page} has no preview.`, "INVALID_PARAMETER");
  const bytes = await fixtureBytes("recognition-photo.png");
  const offset = Number(args.offset ?? 0);
  const length = Math.min(Number(args.length ?? bytes.length), Math.max(0, bytes.length - offset));
  const chunk = {
    job_id: args.job_id,
    page,
    artifact_id: "mock-preview",
    offset,
    length,
    byte_length: bytes.length,
    eof: offset + length >= bytes.length,
    data_b64: base64(bytes.slice(offset, offset + length)),
  };
  return { content: [{ type: "text", text: "Source preview fetched for the Recognition Review." }], structuredContent: chunk };
}

/** `recognize_sheet` as the page calls it again: `engine` picks the result; no image is an input error. */
function recognizeAgain(args: Record<string, unknown>): CallToolResult {
  if (typeof args.image !== "string") return toolError("image is required", "INVALID_INPUT");
  return args.engine === "audiveris" ? AUDIVERIS_RESULT : OEMER_RESULT;
}

export const omrTools: ToolBackend = {
  async callTool(call) {
    const args = call.arguments ?? {};
    switch (call.name) {
      case "get_recognized_score":
        return recognizedScore(args.job_id);
      case "get_source_preview":
        return sourcePreview(args);
      case "recognize_sheet":
        return recognizeAgain(args);
      default:
        throw Object.assign(new Error(`mock host has no fixture for tool ${call.name}`), { code: -32602 });
    }
  },
};
