import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ToolResult } from "@sheet-music-mcp/ui-kit/host/HostBridge";
import { DEBOUNCE_MS, LiveValidator, problemsOf, readValidation, type ValidationState } from "./validation.ts";

const ok = (valid: boolean, errors: string[] = [], warnings: string[] = []): ToolResult => ({
  content: [],
  structuredContent: { valid, errors, warnings },
});

describe("readValidation", () => {
  it("reads the server's structuredContent as it is", () => {
    expect(readValidation(ok(false, ["Line 2: bad"], ["w"]))).toEqual({ valid: false, errors: ["Line 2: bad"], warnings: ["w"] });
  });

  it("reports an error envelope or a malformed result as unavailable", () => {
    const failed: ToolResult = { isError: true, content: [{ type: "text", text: '{"error":"x","error_code":"PROCESSING_FAILED"}' }] };
    expect(readValidation(failed)).toEqual({ unavailable: "PROCESSING_FAILED" });
    expect(readValidation({ content: [] })).toEqual({ unavailable: "MALFORMED_RESULT" });
  });
});

describe("problemsOf", () => {
  it("takes the line number from a message that names one", () => {
    expect(problemsOf(["Line 3: unexpected ?", "line 12 - bad bar", "no position"])).toEqual([
      { line: 3, message: "Line 3: unexpected ?" },
      { line: 12, message: "line 12 - bad bar" },
      { message: "no position" },
    ]);
  });
});

describe("LiveValidator", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  function setup(answer: (abc: string) => ToolResult = () => ok(true)) {
    const calls: string[] = [];
    const states: ValidationState[] = [];
    const validator = new LiveValidator(
      async (abc) => {
        calls.push(abc);
        return answer(abc);
      },
      (state) => states.push(state),
    );
    return { validator, calls, states };
  }

  it("shows pending at once and makes one call, DEBOUNCE_MS after the last keystroke", async () => {
    const { validator, calls, states } = setup();
    validator.input("X:1");
    await vi.advanceTimersByTimeAsync(200);
    validator.input("X:1\nK:C");
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS - 1);
    expect(calls).toEqual([]);
    expect(states.map((s) => s.status)).toEqual(["pending", "pending"]);
    await vi.advanceTimersByTimeAsync(1);
    expect(calls).toEqual(["X:1\nK:C"]);
    expect(states.at(-1)).toMatchObject({ status: "valid", errors: [], problems: [] });
  });

  it("debounces at 300 ms (the plan's figure)", () => {
    expect(DEBOUNCE_MS).toBe(300);
  });

  it("reports the server's errors with their lines", async () => {
    const { validator, states } = setup(() => ok(false, ["Line 2: nope"], ["careful"]));
    validator.input("a\nb");
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    expect(states.at(-1)).toEqual({
      status: "invalid",
      errors: ["Line 2: nope"],
      warnings: ["careful"],
      problems: [{ line: 2, message: "Line 2: nope" }],
    });
  });

  it("ignores a slow answer that a newer input has superseded", async () => {
    let release: (r: ToolResult) => void = () => {};
    const calls: string[] = [];
    const states: ValidationState[] = [];
    const validator = new LiveValidator(
      (abc) => {
        calls.push(abc);
        return calls.length === 1 ? new Promise<ToolResult>((resolve) => (release = resolve)) : Promise.resolve(ok(true));
      },
      (s) => states.push(s),
    );
    validator.input("first");
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    validator.input("second");
    release(ok(false, ["Line 1: stale"]));
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    expect(calls).toEqual(["first", "second"]);
    expect(states.map((s) => s.status)).not.toContain("invalid");
    expect(states.at(-1)?.status).toBe("valid");
  });

  it("does not call again for the text it last validated", async () => {
    const { validator, calls, states } = setup();
    validator.input("same");
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    validator.input("other");
    validator.input("same");
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    expect(calls).toEqual(["same"]);
    expect(states.at(-1)?.status).toBe("valid");
  });

  it("goes unavailable when the call fails or the tool answers with an error", async () => {
    const failing = new LiveValidator(
      async () => {
        throw new Error("down");
      },
      (s) => states.push(s),
    );
    const states: ValidationState[] = [];
    failing.input("x");
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    expect(states.at(-1)).toEqual({ status: "unavailable", message: "The validator could not be reached." });
  });

  it("an empty text is idle, with no call", async () => {
    const { validator, calls, states } = setup();
    validator.input("   ");
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS * 2);
    expect(calls).toEqual([]);
    expect(states.at(-1)).toEqual({ status: "idle" });
  });
});
