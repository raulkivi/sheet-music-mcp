import { describe, expect, it } from "vitest";
import { IN_TUNE_CENTS, METER_RANGE_CENTS, centsToNeedle, needleAt, shouldRefreshText } from "./meter.ts";

describe("centsToNeedle", () => {
  it("puts 0 cents in the middle and the range ends at the edges", () => {
    expect(centsToNeedle(0)).toBe(50);
    expect(centsToNeedle(-METER_RANGE_CENTS)).toBe(0);
    expect(centsToNeedle(METER_RANGE_CENTS)).toBe(100);
  });

  it("is linear in between: sharp to the right, flat to the left", () => {
    expect(centsToNeedle(25)).toBe(75);
    expect(centsToNeedle(-10)).toBe(40);
  });

  it("pins readings beyond the range to the edge", () => {
    expect(centsToNeedle(180)).toBe(100);
    expect(centsToNeedle(-1200)).toBe(0);
  });

  it("has no position without a reading", () => {
    expect(centsToNeedle(null)).toBeNull();
    expect(centsToNeedle(Number.NaN)).toBeNull();
  });

  it("keeps the in-tune zone inside the range", () => {
    expect(IN_TUNE_CENTS).toBeLessThan(METER_RANGE_CENTS);
  });
});

describe("needleAt", () => {
  it("moves linearly from the old to the new position over the duration", () => {
    expect(needleAt(40, 60, 0, 100, false)).toBe(40);
    expect(needleAt(40, 60, 50, 100, false)).toBe(50);
    expect(needleAt(40, 60, 100, 100, false)).toBe(60);
  });

  it("does not overshoot after the duration", () => {
    expect(needleAt(40, 60, 500, 100, false)).toBe(60);
  });

  it("jumps straight to the new position under reduced motion", () => {
    expect(needleAt(40, 60, 0, 100, true)).toBe(60);
  });

  it("jumps when there is no duration", () => {
    expect(needleAt(40, 60, 0, 0, false)).toBe(60);
  });
});

describe("shouldRefreshText", () => {
  it("refreshes the first time", () => {
    expect(shouldRefreshText(undefined, "on_pitch", 0)).toBe(true);
  });

  it("refreshes at once when the status changes, so a screen reader hears it", () => {
    expect(shouldRefreshText({ status: "on_pitch", at: 0 }, "sharp", 10)).toBe(true);
  });

  it("holds the cents text between refreshes while the status stays", () => {
    expect(shouldRefreshText({ status: "sharp", at: 0 }, "sharp", 400)).toBe(false);
    expect(shouldRefreshText({ status: "sharp", at: 0 }, "sharp", 1000)).toBe(true);
  });
});
