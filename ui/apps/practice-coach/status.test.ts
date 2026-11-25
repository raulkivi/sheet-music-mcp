import { describe, expect, it } from "vitest";
import { readingText, statusView } from "./status.ts";

describe("statusView", () => {
  it("names every server grading state", () => {
    expect(statusView("on_pitch", 3)).toEqual({ label: "On pitch", tone: "ok", graded: true });
    expect(statusView("sharp", 32)).toEqual({ label: "Sharp", tone: "warn", graded: true });
    expect(statusView("flat", -32)).toEqual({ label: "Flat", tone: "warn", graded: true });
    expect(statusView("no_signal", null)).toEqual({ label: "No sound", tone: "muted", graded: false });
  });

  it("calls a large miss danger, still by its direction", () => {
    expect(statusView("sharp", 80)).toEqual({ label: "Sharp", tone: "danger", graded: true });
    expect(statusView("flat", -51)).toEqual({ label: "Flat", tone: "danger", graded: true });
  });

  it("never reports an uncertain frame as an error: neutral, not graded", () => {
    expect(statusView("uncertain", null)).toEqual({ label: "Not sure", tone: "neutral", graded: false });
    // Even if a cents value were attached, an uncertain frame stays ungraded.
    expect(statusView("uncertain", 700).tone).toBe("neutral");
  });

  it("treats a state this page does not know as neutral, not as an error", () => {
    expect(statusView("brand_new", 10)).toEqual({ label: "Unknown", tone: "neutral", graded: false });
  });

  it("tolerates a flat or sharp status without cents", () => {
    expect(statusView("flat", null).tone).toBe("warn");
  });
});

describe("readingText", () => {
  it("is what a screen reader hears: signed cents and the word", () => {
    expect(readingText("sharp", 12)).toBe("+12 cents, sharp");
    expect(readingText("flat", -14)).toBe("-14 cents, flat");
    expect(readingText("on_pitch", 0)).toBe("0 cents, on pitch");
  });

  it("explains the states that carry no cents", () => {
    expect(readingText("uncertain", null)).toBe("Not graded: the pitch was unclear");
    expect(readingText("no_signal", null)).toBe("No sound heard");
  });

  it("says nothing was graded when cents are missing", () => {
    expect(readingText("flat", null)).toBe("flat, no cents value");
  });
});
