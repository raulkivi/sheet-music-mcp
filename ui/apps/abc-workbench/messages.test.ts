import { describe, expect, it } from "vitest";
import type { ToolResult } from "@sheet-music-mcp/ui-kit/host/HostBridge";
import { acceptContext, readConversion, readProposal, readStoredAbc, reviseMessage, rejectContext } from "./messages.ts";

const text = (value: unknown): ToolResult["content"] => [{ type: "text", text: JSON.stringify(value) }];

describe("readProposal", () => {
  it("takes the model's ABC from the tool input", () => {
    expect(readProposal({ abc: "X:1\nK:C" })).toBe("X:1\nK:C");
  });
  it("is undefined when the call had no ABC (musicxml_to_abc)", () => {
    expect(readProposal({ musicxml_path: "/a.musicxml" })).toBeUndefined();
    expect(readProposal({ abc: "  " })).toBeUndefined();
  });
});

describe("readStoredAbc", () => {
  it("reads abc, abc_id and warnings from structuredContent", () => {
    const result: ToolResult = { structuredContent: { abc_id: "id1", abc: "X:1", parts_included: ["P1"], warnings: ["w"] } };
    expect(readStoredAbc(result)).toEqual({ abc: "X:1", abcId: "id1", warnings: ["w"] });
  });
  it("is undefined for a result without ABC, such as abc_to_musicxml's", () => {
    expect(readStoredAbc({ structuredContent: { warnings: [], delivery: "inline", musicxml_bytes: 3 } })).toBeUndefined();
  });
});

describe("readConversion", () => {
  it("reads an inline delivery: the score text from content, warnings from structuredContent", () => {
    const result: ToolResult = {
      content: text({ musicxml: "<score-partwise/>", warnings: ["w"] }),
      structuredContent: { warnings: ["w"], delivery: "inline", musicxml_bytes: 17 },
    };
    expect(readConversion(result)).toEqual({ kind: "inline", musicxml: "<score-partwise/>", bytes: 17, warnings: ["w"] });
  });
  it("reads a file delivery: the path from content", () => {
    const result: ToolResult = {
      content: text({ musicxml_path: "/out/from-abc-1.musicxml", warnings: [] }),
      structuredContent: { warnings: [], delivery: "path", musicxml_bytes: 90000 },
    };
    expect(readConversion(result)).toEqual({ kind: "file", path: "/out/from-abc-1.musicxml", bytes: 90000, warnings: [] });
  });
  it("reports the tool's error code", () => {
    const failed: ToolResult = { isError: true, content: text({ error: "bad", error_code: "INVALID_INPUT" }) };
    expect(readConversion(failed)).toEqual({ kind: "error", code: "INVALID_INPUT", message: "bad" });
  });
  it("reports a result it cannot read as an error", () => {
    expect(readConversion({ content: [] })).toMatchObject({ kind: "error", code: "MALFORMED_RESULT" });
  });
});

describe("texts for the model", () => {
  it("states what was accepted, with numbers and the file path only", () => {
    expect(acceptContext({ accepted: 2, total: 3, path: "/out/a.musicxml" })).toBe(
      "ABC Workbench: the user accepted 2 of 3 proposed changes and converted the result to MusicXML, saved at `/out/a.musicxml`.",
    );
    expect(acceptContext({ accepted: 1, total: 1 })).toBe("ABC Workbench: the user accepted 1 of 1 proposed changes and converted the result to MusicXML.");
  });
  it("strips control characters and backticks from the path", () => {
    expect(acceptContext({ accepted: 1, total: 1, path: "/o/`a`\n.musicxml" })).toContain("`/o/a.musicxml`");
  });
  it("says the user rejected the edit", () => {
    expect(rejectContext(3)).toBe("ABC Workbench: the user rejected all 3 proposed changes; the score is unchanged.");
  });
  it("asks for a revision naming the rejected changes by number and line", () => {
    expect(reviseMessage([{ number: 2, originalLine: 6 }, { number: 3, originalLine: 9 }], 3)).toBe(
      "I reviewed your ABC edit in the ABC Workbench and rejected 2 of 3 changes: change 2 (original line 6), change 3 (original line 9). Please revise it.",
    );
    expect(reviseMessage([], 2)).toBe("I reviewed your ABC edit in the ABC Workbench and kept all 2 changes, but I would like a revision. Please revise it.");
  });
});
