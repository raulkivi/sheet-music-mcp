// Streams an audio artifact into a Blob by paging the server's `read_audio_chunk` tool, so a
// score's audio never arrives as one oversized message. Shared by the practice pages.

import type { HostBridge, ToolResult } from "../host/HostBridge.ts";
import { errorEnvelope } from "../host/toolErrors.ts";

/** The tool every server exposes for reading an artifact in chunks. */
export const READ_AUDIO_CHUNK_TOOL = "read_audio_chunk";

/** Chunk size: well under the 1 MiB the tool allows, and a tidy multiple of the page size. */
export const DEFAULT_CHUNK_BYTES = 524_288;

/** Anything that stops the audio from arriving: a missing tool, a server error, a bad chunk. */
export class AudioLoadError extends Error {
  override name = "AudioLoadError";
  constructor(message: string, readonly code: string) {
    super(message);
  }
}

export interface LoadAudioOptions {
  /** Aborting stops the paging before the next call. */
  signal?: AbortSignal;
  /** Bytes asked for per call; capped by the tool at 1 MiB. */
  chunkBytes?: number;
  /** MIME type for the resulting Blob. */
  mimeType?: string;
  /** Called after every chunk, with the bytes read so far and the total when known. */
  onProgress?(loaded: number, total?: number): void;
}

/** One validated page of the artifact. */
interface Chunk {
  bytes: Uint8Array<ArrayBuffer>;
  length: number;
  byteLength: number;
  eof: boolean;
}

function decodeBase64(data: string): Uint8Array<ArrayBuffer> {
  const binary = atob(data);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

/** Fetches one chunk and checks the shape the server promises. */
async function readChunk(
  bridge: HostBridge,
  audioId: string,
  offset: number,
  length: number,
): Promise<Chunk> {
  let result: ToolResult;
  try {
    result = await bridge.callTool(READ_AUDIO_CHUNK_TOOL, { audio_id: audioId, offset, length });
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error);
    throw new AudioLoadError(`${READ_AUDIO_CHUNK_TOOL} is not available: ${reason}`, "TOOL_UNAVAILABLE");
  }

  const envelope = errorEnvelope(result);
  if (envelope) {
    throw new AudioLoadError(envelope.error || "The server could not read the audio.", envelope.code);
  }

  const data = (result.structuredContent ?? {}) as Record<string, unknown>;
  const { length: returned, byte_length: byteLength, eof, data_b64: encoded } = data;
  if (
    typeof returned !== "number" ||
    typeof byteLength !== "number" ||
    typeof eof !== "boolean" ||
    typeof encoded !== "string"
  ) {
    throw new AudioLoadError(`${READ_AUDIO_CHUNK_TOOL} returned no data.`, "INVALID_RESULT");
  }

  const bytes = decodeBase64(encoded);
  if (bytes.length !== returned) {
    throw new AudioLoadError(
      `${READ_AUDIO_CHUNK_TOOL} returned ${bytes.length} bytes for a chunk of ${returned}.`,
      "INVALID_RESULT",
    );
  }
  return { bytes, length: returned, byteLength, eof };
}

/** Reads every chunk of `audioId` and returns them as one Blob. */
export async function loadAudio(
  bridge: HostBridge,
  audioId: string,
  options: LoadAudioOptions = {},
): Promise<Blob> {
  const chunkBytes = options.chunkBytes ?? DEFAULT_CHUNK_BYTES;
  const mimeType = options.mimeType ?? "audio/wav";
  const parts: BlobPart[] = [];
  let offset = 0;

  for (;;) {
    if (options.signal?.aborted) throw new DOMException("Audio loading was aborted.", "AbortError");

    const chunk = await readChunk(bridge, audioId, offset, chunkBytes);
    if (chunk.bytes.length > 0) parts.push(chunk.bytes);
    offset += chunk.length;
    options.onProgress?.(offset, chunk.byteLength);

    if (chunk.eof) return new Blob(parts, { type: mimeType });
    if (chunk.length === 0) throw new AudioLoadError("The server stopped returning audio data.", "STALLED");
  }
}
