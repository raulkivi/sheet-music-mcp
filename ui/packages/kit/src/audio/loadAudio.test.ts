import { describe, expect, it } from "vitest";
import { FakeBridge } from "../host/FakeBridge.ts";
import type { ToolResult } from "../host/HostBridge.ts";
import {
  AudioLoadError,
  DEFAULT_CHUNK_BYTES,
  loadAudio,
  READ_AUDIO_CHUNK_TOOL,
} from "./loadAudio.ts";

/** Encodes bytes as standard base64, the same wire format the server sends. */
function b64(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

/** A fake `read_audio_chunk` over a fixed source, paging by offset/length. */
function fakeAudio(source: Uint8Array) {
  return (args: Record<string, unknown>): ToolResult => {
    const offset = args.offset as number;
    const requested = args.length as number;
    const slice = source.slice(offset, offset + requested);
    return {
      structuredContent: {
        artifact_id: "art-1",
        offset,
        length: slice.length,
        byte_length: source.length,
        eof: offset + slice.length >= source.length,
        data_b64: b64(slice),
      },
    };
  };
}

async function blobBytes(blob: Blob): Promise<Uint8Array> {
  return new Uint8Array(await blob.arrayBuffer());
}

const source = Uint8Array.from(Array.from({ length: 1000 }, (_, i) => (i * 37 + 11) & 0xff));

describe("loadAudio", () => {
  it("pages through several chunks and returns the exact bytes", async () => {
    const bridge = new FakeBridge({ toolAnswers: { [READ_AUDIO_CHUNK_TOOL]: fakeAudio(source) } });
    const blob = await loadAudio(bridge, "art-1", { chunkBytes: 64 });

    expect(await blobBytes(blob)).toStrictEqual(source);
    const calls = bridge.calls.map((call) => (call.params as { arguments: Record<string, unknown> }).arguments);
    expect(calls.length).toBe(Math.ceil(source.length / 64));
    expect(new Set(calls.map((a) => a.audio_id))).toStrictEqual(new Set(["art-1"]));
    expect(calls.map((a) => a.offset)).toStrictEqual(Array.from({ length: 16 }, (_, i) => i * 64));
    expect(calls.map((a) => a.length)).toStrictEqual(new Array(16).fill(64));
  });

  it("returns a typed blob from a single chunk", async () => {
    const bridge = new FakeBridge({ toolAnswers: { read_audio_chunk: fakeAudio(source) } });
    const blob = await loadAudio(bridge, "art-1", { chunkBytes: 2000, mimeType: "audio/mpeg" });

    expect(blob.type).toBe("audio/mpeg");
    expect((await blobBytes(blob)).length).toBe(1000);
    expect(bridge.calls).toHaveLength(1);
  });

  it("defaults the chunk size and mime type", async () => {
    expect(DEFAULT_CHUNK_BYTES).toBe(524_288);
    const bridge = new FakeBridge({ toolAnswers: { read_audio_chunk: fakeAudio(source) } });
    const blob = await loadAudio(bridge, "art-1");

    expect(blob.type).toBe("audio/wav");
    expect((bridge.calls[0]!.params as { arguments: Record<string, unknown> }).arguments.length).toBe(DEFAULT_CHUNK_BYTES);
  });

  it("returns an empty blob for an empty file", async () => {
    const bridge = new FakeBridge({
      toolAnswers: {
        read_audio_chunk: () => ({
          structuredContent: {
            artifact_id: "art-1",
            offset: 0,
            length: 0,
            byte_length: 0,
            eof: true,
            data_b64: "",
          },
        }),
      },
    });
    const blob = await loadAudio(bridge, "art-1");

    expect(blob.size).toBe(0);
    expect(bridge.calls).toHaveLength(1);
  });

  it("reports an unknown audio id as INVALID_PARAMETER", async () => {
    const bridge = new FakeBridge({
      toolAnswers: {
        read_audio_chunk: () => ({
          isError: true,
          content: [{ type: "text", text: JSON.stringify({ error: "Unknown audio id.", error_code: "INVALID_PARAMETER" }) }],
        }),
      },
    });

    await expect(loadAudio(bridge, "nope")).rejects.toMatchObject({
      name: "AudioLoadError",
      code: "INVALID_PARAMETER",
      message: "Unknown audio id.",
    });
  });

  it("throws before any call when the signal is already aborted", async () => {
    const bridge = new FakeBridge({ toolAnswers: { read_audio_chunk: fakeAudio(source) } });
    const controller = new AbortController();
    controller.abort();

    const error = await loadAudio(bridge, "art-1", { signal: controller.signal }).catch((error) => error);
    expect(error).toBeInstanceOf(DOMException);
    expect(error.name).toBe("AbortError");
    expect(bridge.calls).toHaveLength(0);
  });

  it("stops at the first chunk after an abort mid-loop", async () => {
    const bridge = new FakeBridge({ toolAnswers: { read_audio_chunk: fakeAudio(source) } });
    const controller = new AbortController();
    const error = await loadAudio(bridge, "art-1", {
      chunkBytes: 64,
      signal: controller.signal,
      onProgress: () => controller.abort(),
    }).catch((error) => error);

    expect(error.name).toBe("AbortError");
    expect(bridge.calls).toHaveLength(1);
  });

  it("throws STALLED when the server stops advancing the offset", async () => {
    const bridge = new FakeBridge({
      toolAnswers: {
        read_audio_chunk: () => ({
          structuredContent: {
            artifact_id: "art-1",
            offset: 0,
            length: 0,
            byte_length: 1000,
            eof: false,
            data_b64: "",
          },
        }),
      },
    });

    await expect(loadAudio(bridge, "art-1")).rejects.toMatchObject({
      name: "AudioLoadError",
      code: "STALLED",
    });
    expect(bridge.calls).toHaveLength(1);
  });

  it("reports a host that cannot answer the tool as TOOL_UNAVAILABLE", async () => {
    const bridge = new FakeBridge({});
    await expect(loadAudio(bridge, "art-1")).rejects.toMatchObject({
      name: "AudioLoadError",
      code: "TOOL_UNAVAILABLE",
    });
  });

  it("rejects a chunk whose decoded length does not match the reported length", async () => {
    const bridge = new FakeBridge({
      toolAnswers: {
        read_audio_chunk: () => ({
          structuredContent: {
            artifact_id: "art-1",
            offset: 0,
            length: 8,
            byte_length: 8,
            eof: true,
            data_b64: b64(Uint8Array.from([1, 2, 3])),
          },
        }),
      },
    });

    await expect(loadAudio(bridge, "art-1")).rejects.toMatchObject({ code: "INVALID_RESULT" });
  });

  it("rejects a result without the expected fields", async () => {
    const bridge = new FakeBridge({ toolAnswers: { read_audio_chunk: () => ({ content: [] }) } });
    await expect(loadAudio(bridge, "art-1")).rejects.toMatchObject({ code: "INVALID_RESULT" });
  });

  it("reports progress after every chunk, including the last", async () => {
    const bridge = new FakeBridge({ toolAnswers: { read_audio_chunk: fakeAudio(source) } });
    const progress: Array<[number, number | undefined]> = [];
    const blob = await loadAudio(bridge, "art-1", {
      chunkBytes: 400,
      onProgress: (loaded, total) => progress.push([loaded, total]),
    });

    expect(blob.size).toBe(1000);
    expect(progress).toStrictEqual([
      [400, 1000],
      [800, 1000],
      [1000, 1000],
    ]);
  });
});
