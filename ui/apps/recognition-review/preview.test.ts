import { describe, expect, it } from "vitest";
import { FakeBridge } from "@sheet-music-mcp/ui-kit/host/FakeBridge";
import type { ToolResult } from "@sheet-music-mcp/ui-kit/host/HostBridge";
import { loadPreview, toDataUrl } from "./preview.ts";

const PNG = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 1, 2, 3, 4, 5, 6, 7]);
const JPEG = new Uint8Array([0xff, 0xd8, 0xff, 1, 2, 3, 4]);
const b64 = (bytes: Uint8Array) => btoa(String.fromCharCode(...bytes));

function serve(bytes: Uint8Array) {
  return (args: Record<string, unknown>): ToolResult => {
    const offset = Number(args.offset);
    const length = Math.min(Number(args.length), bytes.length - offset);
    const slice = bytes.slice(offset, offset + length);
    return {
      structuredContent: {
        job_id: "j",
        page: args.page,
        artifact_id: "a",
        offset,
        length,
        byte_length: bytes.length,
        eof: offset + length >= bytes.length,
        data_b64: b64(slice),
      },
    };
  };
}

describe("toDataUrl", () => {
  it("sniffs PNG and JPEG and defaults to JPEG, the server's format", () => {
    expect(toDataUrl(PNG)).toMatch(/^data:image\/png;base64,/);
    expect(toDataUrl(JPEG)).toMatch(/^data:image\/jpeg;base64,/);
    expect(toDataUrl(new Uint8Array([1, 2, 3]))).toMatch(/^data:image\/jpeg;base64,/);
  });

  it("round-trips the bytes", () => {
    expect(toDataUrl(JPEG).split(",")[1]).toBe(b64(JPEG));
  });
});

describe("loadPreview", () => {
  it("joins chunks that do not end on a base64 boundary", async () => {
    const bridge = new FakeBridge({ toolAnswers: { get_source_preview: serve(PNG) } });
    const url = await loadPreview(bridge, "job-1", 1, 4);
    expect(url).toBe(toDataUrl(PNG));
    expect(bridge.calls.map((c) => (c.params as { arguments: { offset: number } }).arguments.offset)).toEqual([0, 4, 8]);
    expect(bridge.calls[0]!.params).toEqual({
      name: "get_source_preview",
      arguments: { job_id: "job-1", page: 1, offset: 0, length: 4 },
    });
  });

  it("fails with the server's error code", async () => {
    const failure: ToolResult = {
      isError: true,
      content: [{ type: "text", text: '{"error":"gone","error_code":"INVALID_PARAMETER"}' }],
    };
    const bridge = new FakeBridge({ toolAnswers: { get_source_preview: failure } });
    await expect(loadPreview(bridge, "j", 1)).rejects.toMatchObject({ code: "INVALID_PARAMETER" });
  });

  it("fails on a chunk without data and on a stalled server", async () => {
    const bad = new FakeBridge({ toolAnswers: { get_source_preview: { structuredContent: {} } } });
    await expect(loadPreview(bad, "j", 1)).rejects.toMatchObject({ code: "INVALID_RESULT" });
    const stalled = new FakeBridge({
      toolAnswers: { get_source_preview: { structuredContent: { length: 0, byte_length: 9, eof: false, data_b64: "" } } },
    });
    await expect(loadPreview(stalled, "j", 1)).rejects.toMatchObject({ code: "STALLED" });
  });
});
