import { describe, expect, it } from "vitest";
import { ACCEPT_MESSAGE, acceptContext, rerunStatus } from "./messages.ts";

describe("the one message the page sends the model", () => {
  it("is fixed text: no score, path or warning text in it", () => {
    expect(ACCEPT_MESSAGE).toBe(
      "I checked the recognized score in the Recognition Review and accept it. Please continue with that score.",
    );
    expect(ACCEPT_MESSAGE).not.toMatch(/<|musicxml|\/tmp/i);
  });
});

describe("acceptContext", () => {
  it("is a template filled with counts and the engine name only", () => {
    expect(acceptContext({ engine: "audiveris", parts: 4, measures: 12, openIssues: 0 })).toBe(
      "Recognition Review: the user accepted the score recognized with audiveris (4 parts, 12 bars, 0 open issues).",
    );
  });

  it("leaves out a count the server did not give, and keeps the engine to a safe token", () => {
    expect(acceptContext({ engine: "oem er`\n<x>", parts: undefined, measures: undefined, openIssues: 1 })).toBe(
      "Recognition Review: the user accepted the score recognized with unknown (1 open issue).",
    );
  });
});

describe("rerunStatus", () => {
  it("announces the run and the result", () => {
    expect(rerunStatus.running("audiveris")).toBe("Recognizing again with Audiveris. This can take a few minutes.");
    expect(rerunStatus.done("audiveris", 4, 0)).toBe("Recognized again with Audiveris: 4 parts. Nothing to check.");
    expect(rerunStatus.done("oemer", 1, 2)).toBe("Recognized again with oemer: 1 part. 2 things to check.");
    expect(rerunStatus.failed("audiveris", "PROCESSING_FAILED")).toBe(
      "Recognizing again with Audiveris failed (PROCESSING_FAILED). The earlier result is still shown.",
    );
  });
});
