import { describe, expect, it } from "vitest";
import {
  fileName,
  measureIndex,
  openInScoreViewerMessage,
  readExported,
  readScores,
} from "./messages.ts";

describe("readScores", () => {
  it("reads both annotated scores and the legend", () => {
    expect(
      readScores({
        structuredContent: {
          diff_id: "d",
          reference_musicxml: "<a/>",
          target_musicxml: "<b/>",
          legend: { PITCH_CHANGE: "#FF8800" },
        },
      }),
    ).toEqual({ ok: true, reference: "<a/>", target: "<b/>", legend: { PITCH_CHANGE: "#FF8800" } });
  });

  it("reports an error envelope with its code", () => {
    expect(
      readScores({ isError: true, content: [{ type: "text", text: '{"error":"x","error_code":"INVALID_PARAMETER"}' }] }),
    ).toEqual({ ok: false, code: "INVALID_PARAMETER" });
  });

  it("reports a result without scores", () => {
    expect(readScores({ structuredContent: {} })).toEqual({ ok: false, code: "UNEXPECTED_RESULT" });
  });
});

describe("readExported", () => {
  it("reads the two file paths", () => {
    expect(
      readExported({
        structuredContent: {
          reference_annotated_musicxml_path: "/out/scores/annotated-reference.musicxml",
          target_annotated_musicxml_path: "/out/scores/annotated-target.musicxml",
        },
      }),
    ).toEqual({
      ok: true,
      reference: "/out/scores/annotated-reference.musicxml",
      target: "/out/scores/annotated-target.musicxml",
    });
  });

  it("reports an error envelope with its code", () => {
    expect(
      readExported({ isError: true, content: [{ type: "text", text: '{"error":"x","error_code":"FILE_NOT_FOUND"}' }] }),
    ).toEqual({ ok: false, code: "FILE_NOT_FOUND" });
  });

  it("reports a result without paths", () => {
    expect(readExported({ structuredContent: { similarity_score: 1 } })).toEqual({
      ok: false,
      code: "UNEXPECTED_RESULT",
    });
  });
});

describe("fileName", () => {
  it("is the last path segment", () => {
    expect(fileName("/out/scores/annotated-target.musicxml")).toBe("annotated-target.musicxml");
    expect(fileName("C:\\out\\a.musicxml")).toBe("a.musicxml");
    expect(fileName("a.musicxml")).toBe("a.musicxml");
  });
});

describe("openInScoreViewerMessage", () => {
  it("is a fixed template naming the two saved files", () => {
    expect(openInScoreViewerMessage("/out/ref.musicxml", "/out/tgt.musicxml")).toBe(
      "Open the annotated target score `/out/tgt.musicxml` (and the annotated reference " +
        "`/out/ref.musicxml`) from the Diff Viewer in the Score Viewer: render it with " +
        "render-mcp, passing the path as musicxml_path.",
    );
  });

  it("strips control characters and backticks from the paths and caps their length", () => {
    const message = openInScoreViewerMessage("/o/`r`\n.musicxml", `/o/${"x".repeat(900)}`);
    expect(message).not.toMatch(/[\u0000-\u001f]/);
    expect(message).toContain("`/o/r.musicxml`");
    expect(message.length).toBeLessThan(1300);
  });
});

describe("measureIndex", () => {
  const xml = (numbers: string[]) =>
    `<score-partwise><part id="P1">${numbers.map((n) => `<measure number="${n}"><note/></measure>`).join("")}</part>` +
    `<part id="P2"><measure number="1"/></part></score-partwise>`;

  it("is the position of the measure in the first part", () => {
    expect(measureIndex(xml(["1", "2", "3"]), 3)).toBe(2);
  });

  it("counts a pickup measure numbered 0", () => {
    expect(measureIndex(xml(["0", "1", "2"]), 1)).toBe(1);
  });

  it("finds a measure whose number has an attribute order or extra attributes", () => {
    const text = `<part id="P1"><measure width="10" number="7" implicit="no"/></part>`;
    expect(measureIndex(text, 7)).toBe(0);
  });

  it("is undefined for a measure the score does not have", () => {
    expect(measureIndex(xml(["1", "2"]), 9)).toBeUndefined();
    expect(measureIndex("<score-partwise/>", 1)).toBeUndefined();
  });
});
