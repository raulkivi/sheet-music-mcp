import { describe, expect, it } from "vitest";
import { errorEnvelope } from "./toolErrors.ts";

describe("errorEnvelope", () => {
  it("reads the {error, error_code, hint} envelope from an isError result", () => {
    const result = {
      isError: true,
      content: [{ type: "text", text: '{"error":"Page 9 is out of range.","error_code":"INVALID_PARAMETER","hint":"h"}' }],
    };
    expect(errorEnvelope(result)).toEqual({ error: "Page 9 is out of range.", code: "INVALID_PARAMETER", hint: "h" });
  });

  it("skips blocks that are not the envelope", () => {
    const result = {
      isError: true,
      content: [{ type: "image" }, { type: "text", text: "plain" }, { type: "text", text: '{"error_code":"X"}' }],
    };
    expect(errorEnvelope(result)?.code).toBe("X");
  });

  it("names an error without an envelope UNKNOWN_ERROR", () => {
    expect(errorEnvelope({ isError: true, content: [] })).toEqual({ error: "", code: "UNKNOWN_ERROR" });
  });

  it("is undefined for a successful result", () => {
    expect(errorEnvelope({ content: [{ type: "text", text: '{"error_code":"X"}' }] })).toBeUndefined();
  });
});
