// Practice Player behavior. Depends on the HostBridge and four small ports (audio output, frame
// clock, screen, score engine), so it runs unchanged against fakes in unit tests and in a host.
//
// What changes locally and what calls the server (decision DA4): tempo, loop and play state are
// local (`playbackRate`); a change of voices, volumes, count-in or timbre renders a new track with
// one `synthesize` call, and the page swaps it in at the same place in the music.

import { AudioLoadError, loadAudio } from "@sheet-music-mcp/ui-kit/audio/loadAudio";
import type { HostBridge, HostContext, ToolInput, ToolResult } from "@sheet-music-mcp/ui-kit/host/HostBridge";
import { errorEnvelope } from "@sheet-music-mcp/ui-kit/host/toolErrors";
import { ScoreFollower, type ScoreEngine } from "./follower.ts";
import {
  applyPreset,
  fromTrackParts,
  setVolume,
  toggleMute,
  toggleSolo,
  type MixerState,
  type PresetName,
} from "./mixer.ts";
import type { AudioPort, FrameClock, PlayerUi, PlayerView } from "./ports.ts";
import { audioSeconds, clampTempo, countInSeconds, loopBounds, playbackRate, scoreSeconds, tempoPercent } from "./tempo.ts";
import {
  barsLabel,
  contextMessage,
  readRequest,
  readStartingPitches,
  readTrack,
  renderArgs,
  type RenderRequest,
  type Timbre,
  type Track,
} from "./track.ts";

export const NOTICES = {
  empty: "This tool call did not return a practice track.",
  loadFailed: (code: string, message: string) => `The practice track could not be loaded (${code})${message ? `: ${message}` : "."}`,
  renderFailed: (code: string, message: string) => `The practice track could not be rendered (${code})${message ? `: ${message}` : "."}`,
  cannotPlay: "This host could not play the practice track.",
  noScore: "The score could not be drawn in this host. The audio still plays.",
  pitchesFailed: "The starting pitches are not available.",
};

/** What is on screen and was rendered: restored when a new render fails. */
interface Applied {
  mixer: MixerState;
  preset: PresetName | "";
  focus: string;
  countInBars: number;
  timbre: Timbre;
}

export interface PlayerDeps {
  ui: PlayerUi;
  audio: AudioPort;
  frames: FrameClock;
  /** Starts the score engine; rejects where it cannot run (the page then has no score). */
  openScore(): Promise<ScoreEngine>;
}

export class PracticePlayer {
  private request: RenderRequest = readRequest({});
  private track: Track | undefined;
  private mixer: MixerState = { parts: [], solo: [] };
  private preset: PresetName | "" = "";
  private focus = "";
  private tempo = 1;
  private loop = false;
  private countInBars = 0;
  private timbre: Timbre = "score";
  private playing = false;
  private busy = false;
  private notice: string | undefined;
  private phase: PlayerView["phase"] = "loading";
  private startingPitchesText: string | undefined;
  private xml = "";
  private preRoll = 0;
  private follower: ScoreFollower | undefined;
  private applied: Applied | undefined;
  private renderQueued = false;
  private work: Promise<void> = Promise.resolve();
  private ticking = false;

  constructor(
    private readonly bridge: HostBridge,
    private readonly deps: PlayerDeps,
  ) {}

  async start(): Promise<void> {
    const { audio } = this.deps;
    audio.onEnded(() => this.onEnded());
    this.bridge.onToolInput((input) => this.onToolInput(input));
    this.bridge.onToolResult((result) => this.enqueue(() => this.open(result)));
    this.bridge.onHostContext((context) => this.onHostContext(context));
    this.onHostContext(await this.bridge.connect());
    this.show();
  }

  /** Resolves when queued work, including work it queued, has finished. */
  async idle(): Promise<void> {
    let settled: Promise<void>;
    do {
      settled = this.work;
      await settled;
    } while (settled !== this.work);
  }

  // --- transport ---------------------------------------------------------------------------

  async togglePlay(): Promise<void> {
    if (!this.track) return;
    if (this.playing) {
      this.deps.audio.pause();
      this.playing = false;
      this.deps.ui.announce("Paused");
    } else {
      if (this.deps.audio.position >= this.track.duration - 0.05) this.deps.audio.seek(0);
      try {
        await this.deps.audio.play();
      } catch {
        this.notice = NOTICES.cannotPlay;
        return this.show();
      }
      this.playing = true;
      this.deps.ui.announce("Playing");
      this.startTicking();
    }
    this.show();
    this.updatePosition(true);
  }

  restart(): void {
    this.seek(0);
  }

  /** Moves to `seconds` into the track (the count-in included). */
  seek(seconds: number): void {
    if (!this.track) return;
    this.deps.audio.seek(Math.max(0, Math.min(seconds, this.track.duration)));
    this.updatePosition(true);
  }

  toggleLoop(): void {
    this.loop = !this.loop;
    this.deps.ui.announce(this.loop ? "Loop on" : "Loop off");
    this.show();
    this.tellModel();
  }

  // --- tempo: local only -------------------------------------------------------------------

  setTempo(factor: number): void {
    this.tempo = clampTempo(factor);
    if (this.track) this.deps.audio.setRate(playbackRate(this.tempo, this.track.tempoFactor));
    this.show();
  }

  /** The user let go of the slider: announce it and tell the model. */
  commitTempo(): void {
    this.deps.ui.announce(`Tempo ${tempoPercent(this.tempo)} %`);
    this.tellModel();
  }

  // --- mix: one render per change ----------------------------------------------------------

  toggleMute(id: string): void {
    this.changeMix(toggleMute(this.mixer, id));
  }

  toggleSolo(id: string): void {
    this.changeMix(toggleSolo(this.mixer, id));
  }

  setVolume(id: string, volume: number): void {
    this.changeMix(setVolume(this.mixer, id, volume));
  }

  applyPreset(preset: PresetName, focus: string): void {
    this.mixer = applyPreset(this.mixer, preset, focus);
    this.preset = preset;
    this.focus = focus;
    this.changed();
  }

  toggleCountIn(): void {
    this.countInBars = this.countInBars > 0 ? 0 : Math.max(this.request.countInBars, 1);
    this.changed();
  }

  setTimbre(timbre: Timbre): void {
    this.timbre = timbre;
    this.changed();
  }

  async startingPitches(): Promise<void> {
    const score = Object.fromEntries(
      Object.entries(this.request.carried).filter(([key]) => key === "musicxml" || key === "musicxml_path"),
    );
    let pitches;
    try {
      pitches = readStartingPitches(await this.bridge.callTool("starting_pitches", score));
    } catch {
      pitches = undefined;
    }
    if (!pitches) {
      this.notice = NOTICES.pitchesFailed;
      return this.show();
    }
    this.notice = undefined;
    this.startingPitchesText = pitches.text;
    this.show();
    if (pitches.audioUrl) this.deps.ui.playClip(pitches.audioUrl);
  }

  resize(width: number): void {
    this.follower?.resize(width);
  }

  // --- opening -----------------------------------------------------------------------------

  private onToolInput(input: ToolInput): void {
    this.request = readRequest(input.arguments);
  }

  private onHostContext(context: HostContext): void {
    this.deps.ui.applyHostContext(context);
    if (this.follower) this.follower.resize(this.deps.ui.containerWidth());
  }

  private async open(result: ToolResult): Promise<void> {
    this.phase = "loading";
    this.show();
    const parsed = readTrack(result);
    if (!parsed.ok) {
      this.phase = parsed.kind === "empty" ? "empty" : "error";
      this.notice = parsed.kind === "empty" ? NOTICES.empty : NOTICES.renderFailed(parsed.code, parsed.message);
      return this.show();
    }
    const { track } = parsed;
    try {
      await this.attachAudio(track);
    } catch (error) {
      this.phase = "error";
      this.notice =
        error instanceof AudioLoadError ? NOTICES.loadFailed(error.code, error.message) : NOTICES.cannotPlay;
      return this.show();
    }
    this.track = track;
    this.mixer = fromTrackParts(track.parts);
    this.focus = track.parts[0]?.id ?? "";
    this.preset = "";
    this.tempo = track.tempoFactor;
    this.countInBars = this.request.countInBars;
    this.timbre = this.request.timbre;
    this.loop = this.request.measures !== undefined;
    this.deps.audio.setRate(1);
    this.snapshot();
    this.phase = "ready";
    this.notice = undefined;
    await this.openScore(track);
    this.show();
    this.updatePosition(true);
  }

  private async attachAudio(track: Track): Promise<void> {
    const blob = await loadAudio(this.bridge, track.audioId);
    await this.deps.audio.load(blob);
  }

  private async openScore(track: Track): Promise<void> {
    try {
      const result = await this.bridge.callTool("get_score_xml", { audio_id: track.audioId });
      const xml = result.structuredContent?.musicxml;
      if (errorEnvelope(result) || typeof xml !== "string") throw new Error("no score");
      this.xml = xml;
      this.preRoll = countInSeconds(xml, this.countInBars, track.tempoFactor);
      const engine = await this.deps.openScore();
      const follower = new ScoreFollower(engine, this.deps.ui, () => this.deps.ui.prefersReducedMotion());
      await follower.open(xml, this.deps.ui.containerWidth());
      this.follower = follower;
    } catch {
      this.follower = undefined;
      this.notice = NOTICES.noScore;
    }
  }

  // --- re-rendering ------------------------------------------------------------------------

  private changeMix(mixer: MixerState): void {
    this.mixer = mixer;
    this.preset = "";
    this.changed();
  }

  /** A change the audio must follow: show it at once and render once the queue is free. */
  private changed(): void {
    this.show();
    if (this.renderQueued || !this.track) return;
    this.renderQueued = true;
    this.enqueue(() => this.render());
  }

  private async render(): Promise<void> {
    this.renderQueued = false;
    const old = this.track;
    if (!old) return;
    this.busy = true;
    this.deps.ui.announce("Rendering the new mix");
    this.show();
    const wanted = { mixer: this.mixer, preset: this.preset, focus: this.focus, countInBars: this.countInBars, timbre: this.timbre };
    try {
      const result = await this.bridge.callTool(
        "synthesize",
        renderArgs(this.request, wanted.mixer, this.tempo, { countInBars: wanted.countInBars, timbre: wanted.timbre }),
      );
      const parsed = readTrack(result);
      if (!parsed.ok) {
        throw new AudioLoadError(parsed.kind === "error" ? parsed.message : NOTICES.empty, parsed.kind === "error" ? parsed.code : "EMPTY");
      }
      await this.swapIn(old, parsed.track, wanted.countInBars);
      this.notice = undefined;
      this.snapshot();
      this.deps.ui.announce("Mix updated");
      this.tellModel();
    } catch (error) {
      this.restore();
      this.notice =
        error instanceof AudioLoadError ? NOTICES.renderFailed(error.code, error.message) : NOTICES.cannotPlay;
    }
    this.busy = false;
    this.show();
  }

  /** Replaces the audio, keeping the place in the music and whether it plays. */
  private async swapIn(old: Track, next: Track, countInBars: number): Promise<void> {
    const { audio } = this.deps;
    const music = this.follower?.musicSeconds ?? 0;
    const position = audio.position;
    const place = scoreSeconds(position, old.tempoFactor, this.preRoll, music);
    const wasPlaying = this.playing;
    await this.attachAudio(next);
    this.track = next;
    this.preRoll = countInSeconds(this.xml, countInBars, next.tempoFactor);
    audio.setRate(playbackRate(this.tempo, next.tempoFactor));
    // In the count-in there is no place in the music: keep the same moment of the clicks.
    const clicks = Math.min((position * old.tempoFactor) / next.tempoFactor, this.preRoll);
    audio.seek(place === undefined ? clicks : audioSeconds(place, next.tempoFactor, this.preRoll));
    if (wasPlaying) await audio.play();
    this.updatePosition(true);
  }

  private snapshot(): void {
    this.applied = { mixer: this.mixer, preset: this.preset, focus: this.focus, countInBars: this.countInBars, timbre: this.timbre };
  }

  private restore(): void {
    if (!this.applied) return;
    ({ mixer: this.mixer, preset: this.preset, focus: this.focus, countInBars: this.countInBars, timbre: this.timbre } = this.applied);
  }

  // --- following the audio -----------------------------------------------------------------

  private onEnded(): void {
    if (this.loop && this.track) {
      const { start } = loopBounds(this.preRoll, this.track.duration);
      this.deps.audio.seek(start);
      this.enqueue(async () => {
        await this.deps.audio.play();
      });
      return;
    }
    this.playing = false;
    this.show();
    this.updatePosition(true);
  }

  private startTicking(): void {
    if (this.ticking) return;
    this.ticking = true;
    const step = () => {
      if (!this.playing) {
        this.ticking = false;
        return;
      }
      this.updatePosition(false);
      this.deps.frames.request(step);
    };
    this.deps.frames.request(step);
  }

  private updatePosition(force: boolean): void {
    if (!this.track) return;
    const seconds = this.deps.audio.position;
    const inMusic = scoreSeconds(seconds, this.track.tempoFactor, this.preRoll, this.follower?.musicSeconds ?? 0);
    const bar = this.follower?.update(inMusic, force);
    const label = inMusic === undefined ? "Count-in" : (bar ?? "");
    this.deps.ui.showPosition({ seconds, duration: this.track.duration, label });
  }

  // --- the screen and the model ------------------------------------------------------------

  private show(): void {
    const view: PlayerView = {
      phase: this.phase,
      busy: this.busy,
      parts: this.mixer.parts.map((part) => ({
        id: part.id,
        name: part.name,
        volume: part.volume,
        muted: part.muted,
        solo: this.mixer.solo.includes(part.id),
      })),
      preset: this.preset,
      focus: this.focus,
      tempoPercent: tempoPercent(this.tempo),
      playing: this.playing,
      loop: this.loop,
      loopLabel: barsLabel(this.request.measures),
      countInOn: this.countInBars > 0,
      timbre: this.timbre,
      durationSeconds: this.track?.duration ?? 0,
      ...(this.notice === undefined ? {} : { notice: this.notice }),
      ...(this.startingPitchesText === undefined ? {} : { startingPitches: this.startingPitchesText }),
    };
    this.deps.ui.render(view);
  }

  private tellModel(): void {
    if (!this.track) return;
    const text = contextMessage({
      mixer: this.mixer,
      tempo: this.tempo,
      loop: this.loop,
      measures: this.request.measures,
      countInBars: this.countInBars,
    });
    this.enqueue(async () => {
      try {
        await this.bridge.updateModelContext(text);
      } catch {
        // The host may not offer it; the page works without.
      }
    });
  }

  private enqueue(task: () => Promise<void>): void {
    this.work = this.work.then(task).catch(() => {});
  }
}
