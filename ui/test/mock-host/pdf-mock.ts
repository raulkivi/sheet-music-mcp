// Stand-in for render-mcp's app-only get_pdf and read_pdf_chunk: a tiny PDF whose bytes start with
// %PDF, kept under an opaque id and read back in chunks, in the server's contract
// (structuredContent, error envelope). The PDF notes how many parts the posted score had, so a
// spec can tell which score a download was made from. Runs in the browser: no Node APIs.

import type { CallToolResult } from "@modelcontextprotocol/client";
import type { ToolBackend, ToolCall } from "./tool-backends.ts";

export const PDF_TOOLS: ReadonlySet<string> = new Set(["get_pdf", "read_pdf_chunk"]);

const MAX_CHUNK_BYTES = 1_048_576;
const PAGE_COUNT = 5;

function toolError(error: string, code: string): CallToolResult {
  return { isError: true, content: [{ type: "text", text: JSON.stringify({ error, error_code: code }) }] };
}

function base64(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

/** The bytes of a minimal one-page PDF, with the part count as a comment line. */
export function tinyPdf(partCount: number): Uint8Array {
  const text = `%PDF-1.4\n%mock-parts:${partCount}\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n`;
  return new TextEncoder().encode(text);
}

export function createPdfMock(): ToolBackend {
  const store = new Map<string, Uint8Array>();
  let counter = 0;

  function getPdf(args: Record<string, unknown>): CallToolResult {
    if (typeof args.musicxml !== "string" || !args.musicxml.includes("<score-partwise")) {
      return toolError("Not a MusicXML score", "INVALID_INPUT");
    }
    const parts = (args.musicxml.match(/<score-part[\s>]/g) ?? []).length;
    const bytes = tinyPdf(parts);
    const pdfId = `mock-pdf-${++counter}`;
    store.set(pdfId, bytes);
    return {
      content: [{ type: "text", text: `PDF of ${PAGE_COUNT} page(s) ready for the Score Viewer.` }],
      structuredContent: { pdf_id: pdfId, byte_length: bytes.length, page_count: PAGE_COUNT, backend: "verovio" },
    };
  }

  function readChunk(args: Record<string, unknown>): CallToolResult {
    const bytes = typeof args.pdf_id === "string" ? store.get(args.pdf_id) : undefined;
    if (!bytes) return toolError("Unknown or expired artifact id", "INVALID_PARAMETER");
    const offset = Number(args.offset);
    const length = Number(args.length);
    if (!Number.isInteger(offset) || offset < 0 || !Number.isInteger(length) || length < 0 || length > MAX_CHUNK_BYTES) {
      return toolError("offset and length must be non-negative integers within the chunk limit", "INVALID_PARAMETER");
    }
    const slice = bytes.slice(offset, offset + length);
    return {
      content: [{ type: "text", text: `PDF bytes ${offset}-${offset + slice.length} of ${bytes.length} sent to the Score Viewer.` }],
      structuredContent: {
        artifact_id: args.pdf_id,
        offset,
        length: slice.length,
        byte_length: bytes.length,
        eof: offset + slice.length >= bytes.length,
        data_b64: base64(slice),
      },
    };
  }

  return {
    async callTool(call: ToolCall) {
      return call.name === "get_pdf" ? getPdf(call.arguments ?? {}) : readChunk(call.arguments ?? {});
    },
  };
}
