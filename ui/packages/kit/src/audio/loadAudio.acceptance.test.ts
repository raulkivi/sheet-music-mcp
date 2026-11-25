import { describe, expect, it } from "vitest";
import { FakeBridge, type ToolAnswer } from "../host/FakeBridge.ts";
import type { ToolResult } from "../host/HostBridge.ts";
import { AudioLoadError, loadAudio } from "./loadAudio.ts";

function wav(n: number): Uint8Array {
  const b = new Uint8Array(n);
  for (let i = 0; i < n; i++) b[i] = (i * 31 + 7) % 256;
  return b;
}

function server(source: Uint8Array, id = "a1"): (args: Record<string, unknown>) => ToolResult {
  return (args) => {
    if (args.audio_id !== id) {
      return {
        isError: true,
        content: [{ type: "text", text: JSON.stringify({ error: "Unknown or expired artifact id", error_code: "INVALID_PARAMETER" }) }],
      };
    }
    const offset = args.offset as number;
    const length = Math.min(args.length as number, 1_048_576);
    const slice = source.slice(offset, offset + length);
    let bin = "";
    for (const c of slice) bin += String.fromCharCode(c);
    return {
      structuredContent: {
        artifact_id: id,
        offset,
        length: slice.length,
        byte_length: source.length,
        eof: offset + slice.length >= source.length,
        data_b64: btoa(bin),
      },
    };
  };
}

const bridgeFor = (answer: ToolAnswer) => new FakeBridge({ toolAnswers: { read_audio_chunk: answer } });
const bytes = async (b: Blob) => new Uint8Array(await b.arrayBuffer());

describe("loadAudio (AC-S3)", () => {
  it("concatenates many chunks byte for byte", async () => {
    const src = wav(2_500_000);
    const blob = await loadAudio(bridgeFor(server(src)), "a1");
    expect(blob.type).toBe("audio/wav");
    expect(await bytes(blob)).toEqual(src);
  });

  it("reads a small file in one call", async () => {
    const src = wav(1000);
    const bridge = bridgeFor(server(src));
    const blob = await loadAudio(bridge, "a1");
    expect(await bytes(blob)).toEqual(src);
    expect(bridge.calls).toHaveLength(1);
  });

  it("returns an empty blob for an empty file", async () => {
    const blob = await loadAudio(bridgeFor(server(new Uint8Array(0))), "a1");
    expect(blob.size).toBe(0);
    expect(blob.type).toBe("audio/wav");
  });

  it("honors a small chunkBytes", async () => {
    const src = wav(1000);
    const bridge = bridgeFor(server(src));
    const blob = await loadAudio(bridge, "a1", { chunkBytes: 300 });
    expect(await bytes(blob)).toEqual(src);
    expect(bridge.calls).toHaveLength(4);
  });

  it("rejects an unknown id with the server's code", async () => {
    const err = await loadAudio(bridgeFor(server(wav(10))), "nope").catch((e) => e);
    expect(err).toBeInstanceOf(AudioLoadError);
    expect(err.code).toBe("INVALID_PARAMETER");
  });

  it("rejects when the bridge call throws", async () => {
    const err = await loadAudio(
      bridgeFor(() => {
        throw new Error("host gone");
      }),
      "a1",
    ).catch((e) => e);
    expect(err).toBeInstanceOf(AudioLoadError);
  });

  it("stops on abort", async () => {
    const src = wav(2_500_000);
    const ctl = new AbortController();
    const inner = server(src);
    let n = 0;
    const bridge = bridgeFor((args) => {
      n++;
      if (n === 2) ctl.abort();
      return inner(args);
    });
    const err = await loadAudio(bridge, "a1", { signal: ctl.signal, chunkBytes: 100_000 }).catch((e) => e);
    expect(err.name).toBe("AbortError");
    expect(bridge.calls.length).toBe(2);
  });

  it("rejects at once when already aborted", async () => {
    const ctl = new AbortController();
    ctl.abort();
    const bridge = bridgeFor(server(wav(10)));
    const err = await loadAudio(bridge, "a1", { signal: ctl.signal }).catch((e) => e);
    expect(err.name).toBe("AbortError");
    expect(bridge.calls).toHaveLength(0);
  });

  it("errors instead of looping when the offset does not advance", async () => {
    const bridge = bridgeFor(() => ({
      structuredContent: { artifact_id: "a1", offset: 0, length: 0, byte_length: 100, eof: false, data_b64: "" },
    }));
    const err = await loadAudio(bridge, "a1").catch((e) => e);
    expect(err).toBeInstanceOf(AudioLoadError);
    expect(bridge.calls.length).toBeLessThanOrEqual(2);
  });

  it("errors on a malformed answer", async () => {
    const err = await loadAudio(bridgeFor(() => ({ structuredContent: { eof: true } })), "a1").catch((e) => e);
    expect(err).toBeInstanceOf(AudioLoadError);
  });

  it("reports progress", async () => {
    const src = wav(1000);
    const seen: Array<[number, number | undefined]> = [];
    await loadAudio(bridgeFor(server(src)), "a1", { chunkBytes: 400, onProgress: (l, t) => seen.push([l, t]) });
    expect(seen).toEqual([
      [400, 1000],
      [800, 1000],
      [1000, 1000],
    ]);
  });
});
