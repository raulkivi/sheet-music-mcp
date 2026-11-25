import { describe, expect, it } from "vitest";
import { ScoreFollower, type FollowerUi, type ScoreEngine } from "./follower.ts";
import type { PlayheadPoint, TimemapEntry } from "./playhead.ts";

const XML = '<score-partwise><part id="P1"><measure number="17"/><measure number="18"/><measure number="19"/></part></score-partwise>';

const TIMEMAP: TimemapEntry[] = [
  { tstamp: 0, measureOn: "m1", on: ["a"] },
  { tstamp: 500, off: ["a"], on: ["b"] },
  { tstamp: 1000, measureOn: "m2", off: ["b"], on: ["c"] },
  { tstamp: 2000, measureOn: "m3", off: ["c"], on: ["d"] },
  { tstamp: 3000, off: ["d"] },
];

class FakeEngine implements ScoreEngine {
  loaded: string[] = [];
  widths: number[] = [];
  pages: Record<string, number> = { a: 1, b: 1, c: 1, d: 2, m1: 1, m2: 1, m3: 2 };
  async load(xml: string) {
    this.loaded.push(xml);
  }
  layout(width: number) {
    this.widths.push(width);
  }
  page(page: number) {
    return { svg: `<svg data-page="${page}"/>`, page, pageCount: 2 };
  }
  timemap() {
    return TIMEMAP;
  }
  pageOf(id: string) {
    return this.pages[id] ?? 1;
  }
}

class FakeUi implements FollowerUi {
  pages: string[] = [];
  heads: (PlayheadPoint | null)[] = [];
  showPage(svg: string) {
    this.pages.push(svg);
  }
  showPlayhead(point: PlayheadPoint | null) {
    this.heads.push(point);
  }
}

async function open(reduced = false) {
  const engine = new FakeEngine();
  const ui = new FakeUi();
  const follower = new ScoreFollower(engine, ui, () => reduced);
  await follower.open(XML, 800);
  return { engine, ui, follower };
}

describe("ScoreFollower", () => {
  it("lays out for the width, loads the score and shows the first page", async () => {
    const { engine, ui } = await open();
    expect(engine.widths).toEqual([800]);
    expect(engine.loaded).toEqual([XML]);
    expect(ui.pages).toEqual(['<svg data-page="1"/>']);
  });

  it("knows the length of the music in seconds", async () => {
    expect((await open()).follower.musicSeconds).toBe(3);
  });

  it("marks the notes sounding and labels the bar with its printed number", async () => {
    const { ui, follower } = await open();
    expect(follower.update(0.6)).toBe("Bar 17");
    expect(ui.heads.at(-1)).toMatchObject({ notes: ["b"], measure: "m1" });
    expect(follower.update(1.2)).toBe("Bar 18");
    expect(ui.heads.at(-1)).toMatchObject({ notes: ["c"], measure: "m2" });
  });

  it("turns the page when the playhead moves to a bar on another one, and marks it again", async () => {
    const { ui, follower } = await open();
    follower.update(0.1);
    follower.update(2.1);
    expect(ui.pages).toEqual(['<svg data-page="1"/>', '<svg data-page="2"/>']);
    expect(ui.heads.at(-1)).toMatchObject({ notes: ["d"], measure: "m3" });
  });

  it("shows no marker during the count-in", async () => {
    const { ui, follower } = await open();
    follower.update(0.1);
    expect(follower.update(undefined)).toBeUndefined();
    expect(ui.heads.at(-1)).toBeNull();
  });

  it("does not repeat an update that changes nothing", async () => {
    const { ui, follower } = await open();
    follower.update(0.6);
    const count = ui.heads.length;
    follower.update(0.7);
    expect(ui.heads).toHaveLength(count);
  });

  it("with reduced motion jumps by bar: the bar is marked, the notes are not, and nothing moves within a bar", async () => {
    const { ui, follower } = await open(true);
    follower.update(0.1);
    follower.update(0.6);
    follower.update(0.9);
    expect(ui.heads).toEqual([{ notes: [], measure: "m1", bar: 0 }]);
    follower.update(1.2);
    expect(ui.heads.at(-1)).toEqual({ notes: [], measure: "m2", bar: 1 });
    expect(ui.heads).toHaveLength(2);
  });

  it("force shows the position again, for a seek that stays in the same bar", async () => {
    const { ui, follower } = await open(true);
    follower.update(0.1);
    follower.update(0.2, true);
    expect(ui.heads).toHaveLength(2);
  });

  it("re-flows for a new width and shows the page the playhead is on", async () => {
    const { engine, ui, follower } = await open();
    follower.update(2.1);
    follower.resize(400);
    expect(engine.widths).toEqual([800, 400]);
    expect(ui.pages.at(-1)).toBe('<svg data-page="2"/>');
    expect(ui.heads.at(-1)).toMatchObject({ measure: "m3" });
  });

  it("ignores a width that did not change", async () => {
    const { engine, follower } = await open();
    follower.resize(800);
    expect(engine.widths).toEqual([800]);
  });
});
