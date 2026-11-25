import { describe, expect, it } from "vitest";
import { ABC_ORIGINAL, ABC_PROPOSED, abcTools, isAbcScenario } from "./abc-tools.ts";

const structured = (result: { structuredContent?: unknown }) => result.structuredContent as Record<string, unknown>;
const body = (result: { content?: unknown[] }) => JSON.parse((result.content![0] as { text: string }).text) as Record<string, unknown>;

describe("abcTools", () => {
  it("get_abc answers the export in the server's contract", async () => {
    const result = await abcTools("abc-edit").callTool({ name: "get_abc", arguments: {} });
    expect(structured(result)).toMatchObject({ abc: ABC_ORIGINAL, parts_included: ["P2"] });
    expect(typeof structured(result).abc_id).toBe("string");
  });

  it("get_abc fails with INVALID_PARAMETER (an unknown or expired id) in the no-original scenario", async () => {
    const result = await abcTools("abc-no-original").callTool({ name: "get_abc", arguments: {} });
    expect(result.isError).toBe(true);
    expect(body(result)).toMatchObject({ error_code: "INVALID_PARAMETER" });
  });

  it("validate_abc reports a line with a question mark as an error on that line", async () => {
    const tools = abcTools("abc-edit");
    expect(structured(await tools.callTool({ name: "validate_abc", arguments: { abc: "X:1\nT:t\nK:C\nab?c|" } }))).toEqual({
      valid: false,
      errors: ['Line 4: unexpected "?"'],
      warnings: [],
    });
    expect(structured(await tools.callTool({ name: "validate_abc", arguments: { abc: ABC_PROPOSED } })).valid).toBe(true);
  });

  it("abc_to_musicxml delivers inline, or as a file in the file scenario", async () => {
    const inline = await abcTools("abc-edit").callTool({ name: "abc_to_musicxml", arguments: { abc: ABC_PROPOSED, return: "auto" } });
    expect(structured(inline)).toMatchObject({ delivery: "inline" });
    expect(body(inline).musicxml).toContain("score-partwise");
    const file = await abcTools("abc-edit-file").callTool({ name: "abc_to_musicxml", arguments: { abc: ABC_PROPOSED, return: "auto" } });
    expect(structured(file)).toMatchObject({ delivery: "path" });
    expect(body(file).musicxml_path).toMatch(/\.musicxml$/);
  });

  it("abc_to_musicxml refuses text without an X: header", async () => {
    const result = await abcTools("abc-edit").callTool({ name: "abc_to_musicxml", arguments: { abc: "junk" } });
    expect(result.isError).toBe(true);
  });

  it("knows only the ABC tools", async () => {
    await expect(abcTools("abc-edit").callTool({ name: "render_page_svg", arguments: {} })).rejects.toThrow(/render_page_svg/);
  });
});

describe("isAbcScenario", () => {
  it("is true for the abc scenarios only", () => {
    expect(isAbcScenario("abc-export")).toBe(true);
    expect(isAbcScenario("inline-long")).toBe(false);
  });
});
