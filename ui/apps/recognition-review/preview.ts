// Reads the source page's preview (`get_source_preview`, base64 chunks of a JPEG) into a data
// URL the <img> can show: the host's default CSP allows `data:` images but not `blob:`.

import type { HostBridge, ToolResult } from "@sheet-music-mcp/ui-kit/host/HostBridge";
import { errorEnvelope } from "@sheet-music-mcp/ui-kit/host/toolErrors";

export const PREVIEW_TOOL = "get_source_preview";
const CHUNK_BYTES = 524_288;

export class PreviewError extends Error {
  override name = "PreviewError";
  constructor(message: string, readonly code: string) {
    super(message);
  }
}

function decode(base64: string): Uint8Array {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

/** The server sends JPEG; a PNG is recognized by its signature so a fixture or a change still shows. */
export function toDataUrl(bytes: Uint8Array): string {
  const png = bytes[0] === 0x89 && bytes[1] === 0x50 && bytes[2] === 0x4e && bytes[3] === 0x47;
  let binary = "";
  for (let i = 0; i < bytes.length; i += 8192) binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
  return `data:image/${png ? "png" : "jpeg"};base64,${btoa(binary)}`;
}

async function readChunk(bridge: HostBridge, args: Record<string, unknown>): Promise<ToolResult> {
  try {
    return await bridge.callTool(PREVIEW_TOOL, args);
  } catch (error) {
    throw new PreviewError(`${PREVIEW_TOOL} is not available: ${error instanceof Error ? error.message : String(error)}`, "TOOL_UNAVAILABLE");
  }
}

/** Pages through the preview and returns it as a data URL. Chunks are joined as bytes, not as base64. */
export async function loadPreview(bridge: HostBridge, jobId: string, page: number, chunkBytes = CHUNK_BYTES): Promise<string> {
  const parts: Uint8Array[] = [];
  let offset = 0;
  for (;;) {
    const result = await readChunk(bridge, { job_id: jobId, page, offset, length: chunkBytes });
    const failure = errorEnvelope(result);
    if (failure) throw new PreviewError(failure.error || "The server could not read the preview.", failure.code);
    const { length, eof, data_b64: encoded } = (result.structuredContent ?? {}) as Record<string, unknown>;
    if (typeof length !== "number" || typeof eof !== "boolean" || typeof encoded !== "string") {
      throw new PreviewError(`${PREVIEW_TOOL} returned no data.`, "INVALID_RESULT");
    }
    const bytes = decode(encoded);
    if (bytes.length !== length) throw new PreviewError(`${PREVIEW_TOOL} returned a chunk of the wrong size.`, "INVALID_RESULT");
    parts.push(bytes);
    offset += length;
    if (eof) break;
    if (length === 0) throw new PreviewError("The server stopped returning the preview.", "STALLED");
  }
  const all = new Uint8Array(offset);
  let at = 0;
  for (const part of parts) {
    all.set(part, at);
    at += part.length;
  }
  return toDataUrl(all);
}
