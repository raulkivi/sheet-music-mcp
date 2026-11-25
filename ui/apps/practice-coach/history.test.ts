import { describe, expect, it } from "vitest";
import { HistoryBuffer, type Sample } from "./history.ts";

function sample(measure: number, status: string, cents: number | null, beat = 1): Sample {
  return { measure, beat, expected_note: "A3", status, accuracy_cents: cents };
}

describe("HistoryBuffer", () => {
  it("keeps samples in order and drops the oldest past its limit", () => {
    const buffer = new HistoryBuffer(3);
    for (let m = 1; m <= 5; m++) buffer.push(sample(m, "on_pitch", 0));
    expect(buffer.samples().map((s) => s.measure)).toEqual([3, 4, 5]);
  });

  it("clears", () => {
    const buffer = new HistoryBuffer();
    buffer.push(sample(1, "on_pitch", 0));
    buffer.clear();
    expect(buffer.samples()).toEqual([]);
    expect(buffer.byMeasure()).toEqual([]);
  });

  describe("byMeasure", () => {
    it("summarizes each bar in the order the singer reached it", () => {
      const buffer = new HistoryBuffer();
      buffer.push(sample(2, "on_pitch", 5));
      buffer.push(sample(2, "on_pitch", -5));
      buffer.push(sample(3, "sharp", 40));
      buffer.push(sample(3, "sharp", 30));
      expect(buffer.byMeasure()).toEqual([
        { measure: 2, status: "on_pitch", avgCents: 0, samples: 2 },
        { measure: 3, status: "sharp", avgCents: 35, samples: 2 },
      ]);
    });

    it("grades a bar by the mean of its graded samples, the sign giving the direction", () => {
      const buffer = new HistoryBuffer();
      buffer.push(sample(1, "flat", -40));
      buffer.push(sample(1, "flat", -35));
      buffer.push(sample(1, "on_pitch", -2));
      expect(buffer.byMeasure()[0]).toMatchObject({ status: "flat", avgCents: -26 });
    });

    it("ignores uncertain and no-signal samples when a bar has graded ones", () => {
      const buffer = new HistoryBuffer();
      buffer.push(sample(1, "uncertain", null));
      buffer.push(sample(1, "no_signal", null));
      buffer.push(sample(1, "on_pitch", 4));
      expect(buffer.byMeasure()[0]).toMatchObject({ status: "on_pitch", avgCents: 4, samples: 3 });
    });

    it("marks a bar with nothing graded uncertain if any frame was, else no signal, with no cents", () => {
      const buffer = new HistoryBuffer();
      buffer.push(sample(1, "uncertain", null));
      buffer.push(sample(1, "no_signal", null));
      buffer.push(sample(2, "no_signal", null));
      expect(buffer.byMeasure()).toEqual([
        { measure: 1, status: "uncertain", avgCents: null, samples: 2 },
        { measure: 2, status: "no_signal", avgCents: null, samples: 1 },
      ]);
    });

    it("keeps a bar's place when the singer returns to it", () => {
      const buffer = new HistoryBuffer();
      buffer.push(sample(1, "on_pitch", 0));
      buffer.push(sample(2, "on_pitch", 0));
      buffer.push(sample(1, "on_pitch", 0));
      expect(buffer.byMeasure().map((m) => [m.measure, m.samples])).toEqual([
        [1, 2],
        [2, 1],
      ]);
    });
  });

  it("lastMeasures returns the most recent n bars", () => {
    const buffer = new HistoryBuffer();
    for (let m = 1; m <= 5; m++) buffer.push(sample(m, "on_pitch", 0));
    expect(buffer.lastMeasures(3).map((m) => m.measure)).toEqual([3, 4, 5]);
    expect(buffer.lastMeasures(9)).toHaveLength(5);
  });
});
