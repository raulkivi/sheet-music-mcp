import { describe, expect, it } from "vitest";
import { createPdfMock, tinyPdf } from "./pdf-mock.ts";

const SCORE = "<score-partwise><part-list><score-part id='P1'/><score-part id='P2'/></part-list></score-partwise>";

async function made(mock = createPdfMock()) {
  const result = await mock.callTool({ name: "get_pdf", arguments: { musicxml: SCORE } });
  return { mock, data: result.structuredContent as { pdf_id: string; byte_length: number } };
}

describe("createPdfMock", () => {
  it("makes a PDF under an opaque id and reports its size", async () => {
    const { data } = await made();
    expect(data.pdf_id).toMatch(/^mock-pdf-/);
    expect(data.byte_length).toBe(tinyPdf(2).length);
  });

  it("reads it back in chunks that start with %PDF and carry the part count", async () => {
    const { mock, data } = await made();
    const first = await mock.callTool({ name: "read_pdf_chunk", arguments: { pdf_id: data.pdf_id, offset: 0, length: 20 } });
    const chunk = first.structuredContent as { data_b64: string; eof: boolean };
    expect(atob(chunk.data_b64).startsWith("%PDF")).toBe(true);
    expect(chunk.eof).toBe(false);
    const rest = await mock.callTool({ name: "read_pdf_chunk", arguments: { pdf_id: data.pdf_id, offset: 0, length: 4096 } });
    expect(atob((rest.structuredContent as { data_b64: string }).data_b64)).toContain("%mock-parts:2");
  });

  it("answers an unknown id and a non-score with the error envelope", async () => {
    const mock = createPdfMock();
    const unknown = await mock.callTool({ name: "read_pdf_chunk", arguments: { pdf_id: "nope", offset: 0, length: 5 } });
    expect(JSON.parse((unknown.content![0] as { text: string }).text)).toMatchObject({ error_code: "INVALID_PARAMETER" });
    const junk = await mock.callTool({ name: "get_pdf", arguments: { musicxml: "hi" } });
    expect(JSON.parse((junk.content![0] as { text: string }).text)).toMatchObject({ error_code: "INVALID_INPUT" });
  });
});
