import { describe, expect, it } from "vitest";
import { FakeBridge, type ToolAnswer } from "@sheet-music-mcp/ui-kit/host/FakeBridge";
import type { HostContext, ToolResult } from "@sheet-music-mcp/ui-kit/host/HostBridge";
import type { RenderedPage } from "@sheet-music-mcp/ui-kit/score/ScoreRenderer";
import type { ScoreEngine } from "./follower.ts";
import type { PlayheadPoint, TimemapEntry } from "./playhead.ts";
import { PracticePlayer } from "./player.ts";
import type { AudioPort, FrameClock, PlayerPosition, PlayerUi, PlayerView } from "./ports.ts";

const XML =
  '<score-partwise><part id="P1"><measure number="17"><attributes><time><beats>4</beats><beat-type>4</beat-type></time></attributes><sound tempo="120"/></measure><measure number="18"/></part></score-partwise>';

const PARTS = [
  { id: "P1", name: "Soprano", included: true, gain: 1 },
  { id: "P2", name: "Alto", included: true, gain: 1 },
  { id: "P3", name: "Tenor", included: true, gain: 1 },
];

const TIMEMAP: TimemapEntry[] = [
  { tstamp: 0, measureOn: "m1", on: ["a"] },
  { tstamp: 2000, measureOn: "m2", off: ["a"], on: ["b"] },
  { tstamp: 4000, off: ["b"] },
];

function track(overrides: Record<string, unknown> = {}): ToolResult {
  return {
    content: [{ type: "text", text: "{}" }],
    structuredContent: {
      audio_id: "a1",
      duration_seconds: 4,
      sample_rate: 8000,
      channels: 1,
      byte_length: 6,
      parts: PARTS,
      tempo_factor: 1,
      ...overrides,
    },
  };
}

function chunk(): ToolAnswer {
  return (args) => {
    if (args.audio_id !== "a1" && args.audio_id !== "a2") {
      return {
        isError: true,
        content: [{ type: "text", text: JSON.stringify({ error: "Unknown audio id", error_code: "INVALID_PARAMETER" }) }],
      };
    }
    return {
      content: [],
      structuredContent: { artifact_id: String(args.audio_id), offset: 0, length: 6, byte_length: 6, eof: true, data_b64: btoa("RIFFxx") },
    };
  };
}

class FakeAudio implements AudioPort {
  blobs: Blob[] = [];
  position = 0;
  rate = 1;
  playing = false;
  failLoad = false;
  private ended: (() => void)[] = [];
  async load(blob: Blob) {
    if (this.failLoad) throw new Error("decode");
    this.blobs.push(blob);
    this.position = 0;
    this.playing = false;
  }
  async play() {
    this.playing = true;
  }
  pause() {
    this.playing = false;
  }
  seek(seconds: number) {
    this.position = seconds;
  }
  setRate(rate: number) {
    this.rate = rate;
  }
  onEnded(listener: () => void) {
    this.ended.push(listener);
  }
  finish() {
    this.playing = false;
    for (const listener of this.ended) listener();
  }
}

class FakeFrames implements FrameClock {
  private queue: (() => void)[] = [];
  request(callback: () => void) {
    this.queue.push(callback);
  }
  tick() {
    const run = this.queue;
    this.queue = [];
    for (const callback of run) callback();
  }
}

class FakeUi implements PlayerUi {
  views: PlayerView[] = [];
  positions: PlayerPosition[] = [];
  announcements: string[] = [];
  heads: (PlayheadPoint | null)[] = [];
  pages: string[] = [];
  clips: string[] = [];
  reduced = false;
  render(view: PlayerView) {
    this.views.push(view);
  }
  showPosition(position: PlayerPosition) {
    this.positions.push(position);
  }
  announce(text: string) {
    this.announcements.push(text);
  }
  showPage(svg: string) {
    this.pages.push(svg);
  }
  showPlayhead(point: PlayheadPoint | null) {
    this.heads.push(point);
  }
  applyHostContext(_context: HostContext) {}
  containerWidth() {
    return 900;
  }
  prefersReducedMotion() {
    return this.reduced;
  }
  playClip(url: string) {
    this.clips.push(url);
  }
  get view(): PlayerView {
    return this.views.at(-1) as PlayerView;
  }
}

class FakeEngine implements ScoreEngine {
  load() {}
  layout() {}
  page(page: number): RenderedPage {
    return { svg: `<svg data-page="${page}"/>`, page, pageCount: 1 };
  }
  timemap() {
    return TIMEMAP;
  }
  pageOf() {
    return 1;
  }
}

function toolCalls(bridge: FakeBridge): number {
  return bridge.calls.filter((call) => call.method === "tools/call").length;
}

interface Setup {
  input?: Record<string, unknown>;
  result?: ToolResult;
  answers?: Record<string, ToolAnswer>;
  score?: () => Promise<ScoreEngine>;
}

async function open(setup: Setup = {}) {
  const input = setup.input ?? { musicxml: XML, measures: [17, 18], count_in_bars: 1 };
  const bridge = new FakeBridge({
    toolInput: { arguments: input },
    toolResult: setup.result ?? track(),
    toolAnswers: {
      read_audio_chunk: chunk(),
      get_score_xml: { content: [], structuredContent: { audio_id: "a1", musicxml: XML } },
      synthesize: () => track({ audio_id: "a2" }),
      ...setup.answers,
    },
  });
  const ui = new FakeUi();
  const audio = new FakeAudio();
  const frames = new FakeFrames();
  const player = new PracticePlayer(bridge, { ui, audio, frames, openScore: setup.score ?? (async () => new FakeEngine()) });
  await player.start();
  await bridge.settled();
  await player.idle();
  const calls = (name: string) => bridge.calls.filter((call) => (call.params as { name: string }).name === name);
  const args = (name: string) => calls(name).map((call) => (call.params as { arguments: Record<string, unknown> }).arguments);
  return { bridge, ui, audio, frames, player, calls, args };
}

describe("opening", () => {
  it("loads the audio and the score of the track the tool returned", async () => {
    const { ui, audio, calls, args } = await open();
    expect(args("read_audio_chunk")).toEqual([{ audio_id: "a1", offset: 0, length: 524288 }]);
    expect(args("get_score_xml")).toEqual([{ audio_id: "a1" }]);
    expect(audio.blobs).toHaveLength(1);
    expect(calls("synthesize")).toHaveLength(0);
    expect(ui.pages).toEqual(['<svg data-page="1"/>']);
    expect(ui.view).toMatchObject({
      phase: "ready",
      busy: false,
      playing: false,
      tempoPercent: 100,
      durationSeconds: 4,
      countInOn: true,
      loop: true,
      loopLabel: "bars 17 to 18",
      timbre: "score",
    });
    expect(ui.view.parts.map((part) => part.name)).toEqual(["Soprano", "Alto", "Tenor"]);
  });

  it("shows the empty state when the call returned no track", async () => {
    const { ui, calls } = await open({ result: { content: [{ type: "text", text: "hi" }] } });
    expect(ui.view.phase).toBe("empty");
    expect(ui.view.notice).toMatch(/did not return a practice track/);
    expect(calls("read_audio_chunk")).toHaveLength(0);
  });

  it("shows the server's error code when synthesize failed", async () => {
    const failed = {
      isError: true,
      content: [{ type: "text", text: JSON.stringify({ error: "No soundfont", error_code: "PROCESSING_FAILED" }) }],
    };
    const { ui } = await open({ result: failed });
    expect(ui.view).toMatchObject({ phase: "error" });
    expect(ui.view.notice).toContain("PROCESSING_FAILED");
    expect(ui.view.notice).toContain("No soundfont");
  });

  it("shows INVALID_PARAMETER for an audio id the server does not know", async () => {
    const { ui } = await open({ result: track({ audio_id: "nope" }) });
    expect(ui.view.phase).toBe("error");
    expect(ui.view.notice).toContain("INVALID_PARAMETER");
  });

  it("keeps the audio when the score cannot be drawn", async () => {
    const { ui } = await open({ score: async () => Promise.reject(new Error("wasm blocked")) });
    expect(ui.view.phase).toBe("ready");
    expect(ui.view.notice).toMatch(/score could not be drawn/);
  });

  it("reports audio the browser cannot decode", async () => {
    const bridge = new FakeBridge({
      toolInput: { arguments: { musicxml: XML } },
      toolResult: track(),
      toolAnswers: { read_audio_chunk: chunk(), get_score_xml: { structuredContent: { musicxml: XML } } },
    });
    const ui = new FakeUi();
    const audio = new FakeAudio();
    audio.failLoad = true;
    const player = new PracticePlayer(bridge, { ui, audio, frames: new FakeFrames(), openScore: async () => new FakeEngine() });
    await player.start();
    await bridge.settled();
    await player.idle();
    expect(ui.view.phase).toBe("error");
    expect(ui.view.notice).toMatch(/could not play/);
  });

  it("starts at the tempo the track was rendered at", async () => {
    const { ui, audio } = await open({ result: track({ tempo_factor: 0.75 }) });
    expect(ui.view.tempoPercent).toBe(75);
    expect(audio.rate).toBe(1);
  });
});

describe("tempo", () => {
  it("changes the playback rate locally, with no tool call", async () => {
    const { player, audio, ui, bridge } = await open();
    const before = toolCalls(bridge);
    player.setTempo(0.5);
    expect(audio.rate).toBe(0.5);
    expect(ui.view.tempoPercent).toBe(50);
    expect(toolCalls(bridge)).toBe(before);
  });

  it("is relative to the tempo the track was rendered at", async () => {
    const { player, audio } = await open({ result: track({ tempo_factor: 0.5 }) });
    player.setTempo(1);
    expect(audio.rate).toBe(2);
  });

  it("stays inside the server's range", async () => {
    const { player, ui } = await open();
    player.setTempo(9);
    expect(ui.view.tempoPercent).toBe(400);
    player.setTempo(0);
    expect(ui.view.tempoPercent).toBe(25);
  });

  it("tells the model and the screen reader once the change is committed", async () => {
    const { player, ui, bridge } = await open();
    const context: string[] = [];
    bridge.updateModelContext = async (text) => void context.push(text);
    player.setTempo(0.75);
    player.setTempo(0.8);
    expect(ui.announcements).toEqual([]);
    player.commitTempo();
    await player.idle();
    expect(ui.announcements).toEqual(["Tempo 80 %"]);
    expect(context).toEqual(["Practice Player: tempo 80 %, loop on (bars 17 to 18), count-in 1 bar, parts playing: P1, P2, P3."]);
  });
});

describe("transport", () => {
  it("plays and pauses, and announces the state", async () => {
    const { player, audio, ui } = await open();
    await player.togglePlay();
    expect(audio.playing).toBe(true);
    expect(ui.view.playing).toBe(true);
    await player.togglePlay();
    expect(audio.playing).toBe(false);
    expect(ui.view.playing).toBe(false);
    expect(ui.announcements).toEqual(["Playing", "Paused"]);
  });

  it("restarts from the start of the track, count-in included", async () => {
    const { player, audio } = await open();
    audio.position = 3;
    player.restart();
    expect(audio.position).toBe(0);
  });

  it("follows the audio: label the count-in, then the bars", async () => {
    const { player, audio, frames, ui } = await open();
    await player.togglePlay();
    audio.position = 1; // the 1-bar count-in at 120 BPM is 2 s
    frames.tick();
    expect(ui.positions.at(-1)).toEqual({ seconds: 1, duration: 4, label: "Count-in" });
    audio.position = 2.5; // 0.5 s into the music
    frames.tick();
    expect(ui.positions.at(-1)).toEqual({ seconds: 2.5, duration: 4, label: "Bar 17" });
    audio.position = 4.5; // 2.5 s into the music: bar 18
    frames.tick();
    expect(ui.positions.at(-1)?.label).toBe("Bar 18");
    expect(ui.heads.at(-1)).toMatchObject({ notes: ["b"] });
  });

  it("maps a slowed-down track back to score time (AC-S5)", async () => {
    const { player, audio, frames, ui } = await open({
      result: track({ tempo_factor: 0.5, duration_seconds: 12 }),
      input: { musicxml: XML, tempo_factor: 0.5 },
    });
    await player.togglePlay();
    audio.position = 3; // 3 s at half tempo is 1.5 s of music: bar 17
    frames.tick();
    expect(ui.positions.at(-1)?.label).toBe("Bar 17");
    audio.position = 4.5; // 2.25 s of music: bar 18
    frames.tick();
    expect(ui.positions.at(-1)?.label).toBe("Bar 18");
  });

  it("stops following when paused", async () => {
    const { player, audio, frames, ui } = await open();
    await player.togglePlay();
    await player.togglePlay();
    const count = ui.positions.length;
    audio.position = 3;
    frames.tick();
    expect(ui.positions).toHaveLength(count);
  });

  it("seeks and shows the new position at once", async () => {
    const { player, audio, ui } = await open();
    player.seek(2.5);
    expect(audio.position).toBe(2.5);
    expect(ui.positions.at(-1)?.label).toBe("Bar 17");
  });

  it("with reduced motion, shows the position only when the bar changes", async () => {
    const { player, audio, frames, ui } = await open();
    ui.reduced = true;
    await player.togglePlay();
    const before = ui.heads.length;
    audio.position = 2.5;
    frames.tick();
    audio.position = 3;
    frames.tick();
    audio.position = 3.5;
    frames.tick();
    expect(ui.heads.length - before).toBe(1);
    audio.position = 4.5;
    frames.tick();
    expect(ui.heads.length - before).toBe(2);
  });
});

describe("loop", () => {
  it("is bound to the measures of the tool call: the end of the track returns to the music, not the count-in", async () => {
    const { player, audio } = await open();
    await player.togglePlay();
    audio.position = 4;
    audio.finish();
    await player.idle();
    expect(audio.position).toBe(2);
    expect(audio.playing).toBe(true);
  });

  it("off, the end of the track stops playback", async () => {
    const { player, audio, ui } = await open();
    player.toggleLoop();
    await player.togglePlay();
    audio.finish();
    expect(ui.view.playing).toBe(false);
    expect(audio.playing).toBe(false);
  });

  it("starts off for the whole piece and names it", async () => {
    const { ui } = await open({ input: { musicxml: XML } });
    expect(ui.view).toMatchObject({ loop: false, loopLabel: "the whole piece" });
  });

  it("toggling it makes no tool call", async () => {
    const { player, bridge } = await open();
    const before = toolCalls(bridge);
    player.toggleLoop();
    expect(toolCalls(bridge)).toBe(before);
  });
});

describe("mixer", () => {
  it("one mute makes exactly one synthesize call with the new gains and the original options", async () => {
    const { player, calls, args } = await open();
    player.toggleMute("P2");
    await player.idle();
    expect(calls("synthesize")).toHaveLength(1);
    expect(args("synthesize")).toEqual([
      {
        musicxml: XML,
        measures: [17, 18],
        repeat: 1,
        part_gains: { P1: 1, P2: 0, P3: 1 },
        tempo_factor: 1,
        count_in_bars: 1,
        timbre: "score",
      },
    ]);
  });

  it("a solo silences the other parts in the call", async () => {
    const { player, args } = await open();
    player.toggleSolo("P3");
    await player.idle();
    expect(args("synthesize")[0]?.part_gains).toEqual({ P1: 0, P2: 0, P3: 1 });
  });

  it("a volume change is one call", async () => {
    const { player, calls, args } = await open();
    player.setVolume("P1", 1.5);
    await player.idle();
    expect(calls("synthesize")).toHaveLength(1);
    expect(args("synthesize")[0]?.part_gains).toEqual({ P1: 1.5, P2: 1, P3: 1 });
  });

  it("a preset sets every part in one call", async () => {
    const { player, calls, args, ui } = await open();
    player.applyPreset("learning", "P2");
    await player.idle();
    expect(calls("synthesize")).toHaveLength(1);
    expect(args("synthesize")[0]?.part_gains).toEqual({ P1: 0.5, P2: 1.5, P3: 0.5 });
    expect(ui.view).toMatchObject({ preset: "learning", focus: "P2" });
  });

  it("changing a part after a preset makes the mix custom again", async () => {
    const { player, ui } = await open();
    player.applyPreset("karaoke", "P1");
    player.toggleMute("P2");
    expect(ui.view.preset).toBe("");
  });

  it("loads the new audio, keeps the place in the music and keeps playing", async () => {
    const { player, audio, ui, args } = await open();
    await player.togglePlay();
    audio.position = 3; // 1 s into the music
    player.toggleMute("P1");
    await player.idle();
    expect(args("read_audio_chunk").map((a) => a.audio_id)).toEqual(["a1", "a2"]);
    expect(audio.blobs).toHaveLength(2);
    expect(audio.position).toBe(3);
    expect(audio.playing).toBe(true);
    expect(ui.view.busy).toBe(false);
    expect(ui.view.parts.find((part) => part.id === "P1")?.muted).toBe(true);
  });

  it("keeps the same moment of the count-in clicks when the mix changes during them", async () => {
    const { player, audio } = await open();
    await player.togglePlay();
    audio.position = 1; // the count-in is 2 s
    player.toggleMute("P1");
    await player.idle();
    expect(audio.position).toBe(1);
  });

  it("renders at the tempo the user chose, then plays at normal rate", async () => {
    const { player, audio, args } = await open({ answers: { synthesize: () => track({ audio_id: "a2", tempo_factor: 0.5, duration_seconds: 8 }) } });
    player.setTempo(0.5);
    expect(audio.rate).toBe(0.5);
    player.toggleMute("P1");
    await player.idle();
    expect(args("synthesize")[0]?.tempo_factor).toBe(0.5);
    expect(audio.rate).toBe(1);
  });

  it("scales the place in the music when the render's tempo differs", async () => {
    const { player, audio } = await open({
      answers: { synthesize: () => track({ audio_id: "a2", tempo_factor: 0.5, duration_seconds: 8 }) },
    });
    player.setTempo(0.5);
    audio.position = 3; // 1 s into the music at tempo 1
    player.toggleMute("P1");
    await player.idle();
    // the count-in is 4 s at tempo 0.5; the music place 1 s is 2 s later
    expect(audio.position).toBe(6);
  });

  it("serializes changes: two quick changes end in the last mix, with one call per settled mix", async () => {
    const { player, args, calls } = await open();
    player.toggleMute("P1");
    player.toggleMute("P2");
    await player.idle();
    expect(calls("synthesize").length).toBeLessThanOrEqual(2);
    expect(args("synthesize").at(-1)?.part_gains).toEqual({ P1: 0, P2: 0, P3: 1 });
  });

  it("restores the mix and shows the error when the render fails", async () => {
    const failed: ToolResult = {
      isError: true,
      content: [{ type: "text", text: JSON.stringify({ error: "No soundfont", error_code: "PROCESSING_FAILED" }) }],
    };
    const { player, ui, audio } = await open({ answers: { synthesize: failed } });
    player.toggleMute("P1");
    await player.idle();
    expect(ui.view.parts.find((part) => part.id === "P1")?.muted).toBe(false);
    expect(ui.view.notice).toContain("PROCESSING_FAILED");
    expect(ui.view.busy).toBe(false);
    expect(audio.blobs).toHaveLength(1);
  });

  it("tells the model what changed", async () => {
    const { player, bridge } = await open();
    const context: string[] = [];
    bridge.updateModelContext = async (text) => void context.push(text);
    player.toggleMute("P2");
    await player.idle();
    expect(context).toEqual([
      "Practice Player: tempo 100 %, loop on (bars 17 to 18), count-in 1 bar, parts playing: P1, P3; muted: P2.",
    ]);
  });
});

describe("count-in and timbre", () => {
  it("count-in off renders with 0 bars", async () => {
    const { player, args, ui } = await open();
    player.toggleCountIn();
    await player.idle();
    expect(args("synthesize")[0]).toMatchObject({ count_in_bars: 0 });
    expect(ui.view.countInOn).toBe(false);
  });

  it("count-in on renders the bars the call asked for, or one", async () => {
    const { player, args } = await open({ input: { musicxml: XML, count_in_bars: 2 }, result: track() });
    player.toggleCountIn();
    player.toggleCountIn();
    await player.idle();
    expect(args("synthesize").at(-1)).toMatchObject({ count_in_bars: 2 });
    const none = await open({ input: { musicxml: XML } });
    none.player.toggleCountIn();
    await none.player.idle();
    expect(none.args("synthesize")[0]).toMatchObject({ count_in_bars: 1 });
  });

  it("a timbre change is one render with that timbre", async () => {
    const { player, args, ui } = await open();
    player.setTimbre("choir");
    await player.idle();
    expect(args("synthesize")).toHaveLength(1);
    expect(args("synthesize")[0]).toMatchObject({ timbre: "choir" });
    expect(ui.view.timbre).toBe("choir");
  });
});

describe("starting pitches", () => {
  it("asks for the score's first notes and plays the clip", async () => {
    const answer: ToolResult = {
      content: [
        { type: "text", text: JSON.stringify({ text: "S: D5, A: A4" }) },
        { type: "audio", data: "AAAA", mimeType: "audio/wav" },
      ],
    };
    const { player, args, ui } = await open({ answers: { starting_pitches: answer } });
    await player.startingPitches();
    expect(args("starting_pitches")).toEqual([{ musicxml: XML }]);
    expect(ui.view.startingPitches).toBe("S: D5, A: A4");
    expect(ui.clips).toEqual(["data:audio/wav;base64,AAAA"]);
  });

  it("shows the notes alone when the server sent no clip", async () => {
    const answer: ToolResult = { content: [{ type: "text", text: JSON.stringify({ text: "S: D5" }) }] };
    const { player, ui } = await open({ answers: { starting_pitches: answer } });
    await player.startingPitches();
    expect(ui.view.startingPitches).toBe("S: D5");
    expect(ui.clips).toEqual([]);
  });

  it("says so when the call fails", async () => {
    const { player, ui } = await open({ answers: { starting_pitches: { isError: true, content: [] } } });
    await player.startingPitches();
    expect(ui.view.notice).toMatch(/starting pitches/i);
  });
});
