// DOM implementation of PlayerUi. Knows the markup in index.html; no host, audio or Verovio code.

import type { HostContext } from "@sheet-music-mcp/ui-kit/host/HostBridge";
import { applyTheme } from "@sheet-music-mcp/ui-kit/theme";
import type { PlayheadPoint } from "./playhead.ts";
import { PRESETS, type PresetName } from "./mixer.ts";
import type { PartView, PlayerPosition, PlayerUi, PlayerView } from "./ports.ts";
import { TIMBRES, type Timbre } from "./track.ts";

export interface Controls {
  togglePlay(): Promise<void>;
  restart(): void;
  seek(seconds: number): void;
  setTempo(factor: number): void;
  commitTempo(): void;
  toggleLoop(): void;
  toggleCountIn(): void;
  setTimbre(timbre: Timbre): void;
  toggleMute(id: string): void;
  toggleSolo(id: string): void;
  setVolume(id: string, volume: number): void;
  applyPreset(preset: PresetName, focus: string): void;
  startingPitches(): Promise<void>;
  resize(width: number): void;
}

const SVG_NS = "http://www.w3.org/2000/svg";

const STATE_LABELS: Record<PlayerView["phase"], string> = {
  loading: "Loading",
  empty: "No track",
  error: "Problem",
  ready: "Ready",
};

function clock(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds));
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

export class DomUi implements PlayerUi {
  private readonly el: {
    state: HTMLElement;
    play: HTMLButtonElement;
    restart: HTMLButtonElement;
    tempo: HTMLInputElement;
    tempoLabel: HTMLElement;
    countInToggle: HTMLButtonElement;
    loop: HTMLButtonElement;
    timbre: HTMLSelectElement;
    pitches: HTMLButtonElement;
    pitchesText: HTMLElement;
    notice: HTMLElement;
    score: HTMLElement;
    seek: HTMLInputElement;
    position: HTMLElement;
    mixer: HTMLElement;
    preset: HTMLSelectElement;
    focus: HTMLSelectElement;
    parts: HTMLElement;
    status: HTMLElement;
    audio: HTMLAudioElement;
    clip: HTMLAudioElement;
  };
  private partIds = "";

  constructor(private readonly doc: Document) {
    const byId = <T extends HTMLElement>(id: string) => {
      const found = doc.getElementById(id);
      if (!found) throw new Error(`index.html is missing #${id}`);
      return found as T;
    };
    this.el = {
      state: byId("state"),
      play: byId("play"),
      restart: byId("restart"),
      tempo: byId("tempo"),
      tempoLabel: byId("tempo-label"),
      countInToggle: byId("count-in"),
      loop: byId("loop"),
      timbre: byId("timbre"),
      pitches: byId("pitches"),
      pitchesText: byId("pitches-text"),
      notice: byId("notice"),
      score: byId("score"),
      seek: byId("seek"),
      position: byId("position"),
      mixer: byId("mixer"),
      preset: byId("preset"),
      focus: byId("focus"),
      parts: byId("parts"),
      status: byId("status"),
      audio: byId("audio"),
      clip: byId("clip"),
    };
  }

  /** The <audio> element the AudioPort drives. */
  get audioElement(): HTMLAudioElement {
    return this.el.audio;
  }

  bind(controls: Controls): void {
    const { el } = this;
    el.play.addEventListener("click", () => void controls.togglePlay());
    el.restart.addEventListener("click", () => controls.restart());
    el.seek.addEventListener("input", () => controls.seek(Number(el.seek.value)));
    el.tempo.addEventListener("input", () => controls.setTempo(Number(el.tempo.value) / 100));
    el.tempo.addEventListener("change", () => controls.commitTempo());
    el.countInToggle.addEventListener("click", () => controls.toggleCountIn());
    el.loop.addEventListener("click", () => controls.toggleLoop());
    el.timbre.addEventListener("change", () => {
      const timbre = TIMBRES.find((name) => name === el.timbre.value);
      if (timbre) controls.setTimbre(timbre);
    });
    el.pitches.addEventListener("click", () => void controls.startingPitches());
    const applyChosenPreset = () => {
      const preset = PRESETS.find((name) => name === el.preset.value);
      if (preset && el.focus.value) controls.applyPreset(preset, el.focus.value);
    };
    el.preset.addEventListener("change", applyChosenPreset);
    el.focus.addEventListener("change", applyChosenPreset);
    // One listener for every part row: rows are rebuilt when a different track opens.
    el.parts.addEventListener("click", (event) => {
      const button = (event.target as Element).closest<HTMLButtonElement>("button[data-part]");
      if (!button?.dataset.part) return;
      if (button.dataset.action === "solo") controls.toggleSolo(button.dataset.part);
      if (button.dataset.action === "mute") controls.toggleMute(button.dataset.part);
    });
    el.parts.addEventListener("input", (event) => {
      const slider = event.target as HTMLInputElement;
      const output = slider.parentElement?.querySelector("output");
      if (output) output.textContent = `${slider.value} %`;
    });
    el.parts.addEventListener("change", (event) => {
      const slider = event.target as HTMLInputElement;
      if (slider.dataset.part) controls.setVolume(slider.dataset.part, Number(slider.value) / 100);
    });
    let frame = 0;
    new ResizeObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => controls.resize(this.containerWidth()));
    }).observe(el.score);
  }

  render(view: PlayerView): void {
    const { el } = this;
    const ready = view.phase === "ready";
    el.state.textContent = view.busy ? "Rendering" : STATE_LABELS[view.phase];
    el.state.dataset.state = view.busy ? "busy" : view.phase;
    el.mixer.setAttribute("aria-busy", String(view.busy));

    el.notice.hidden = view.notice === undefined;
    el.notice.textContent = view.notice ?? "";

    el.play.textContent = view.playing ? "Pause" : "Play";
    el.tempo.value = String(view.tempoPercent);
    el.tempoLabel.textContent = `${view.tempoPercent} %`;
    el.countInToggle.setAttribute("aria-pressed", String(view.countInOn));
    el.loop.setAttribute("aria-pressed", String(view.loop));
    el.loop.textContent = `Loop ${view.loopLabel}`;
    el.timbre.value = view.timbre;
    el.seek.max = String(view.durationSeconds);
    for (const control of [el.play, el.restart, el.tempo, el.countInToggle, el.loop, el.timbre, el.pitches, el.seek, el.preset, el.focus]) {
      control.disabled = !ready;
    }

    el.preset.value = view.preset;
    this.renderParts(view);
    el.pitchesText.hidden = view.startingPitches === undefined;
    el.pitchesText.textContent = view.startingPitches === undefined ? "" : `Starting pitches: ${view.startingPitches}`;
  }

  showPosition(position: PlayerPosition): void {
    const { el } = this;
    el.seek.value = String(position.seconds);
    const where = position.label ? `${position.label} · ` : "";
    el.position.textContent = `${where}${clock(position.seconds)} of ${clock(position.duration)}`;
  }

  showPage(svg: string): void {
    // Verovio escapes score text, and markup assigned through innerHTML never runs scripts.
    this.el.score.innerHTML = svg;
  }

  showPlayhead(point: PlayheadPoint | null): void {
    const { score } = this.el;
    for (const note of score.querySelectorAll(".note.playing")) note.classList.remove("playing");
    for (const band of score.querySelectorAll(".bar-marker")) band.remove();
    score.dataset.bar = point ? String(point.bar) : "";
    score.dataset.notes = point ? String(point.notes.length) : "";
    if (!point) return;
    for (const id of point.notes) this.doc.getElementById(id)?.classList.add("playing");
    const measure = point.measure ? this.doc.getElementById(point.measure) : null;
    if (measure instanceof SVGGraphicsElement) {
      const box = measure.getBBox();
      const band = this.doc.createElementNS(SVG_NS, "rect");
      band.setAttribute("class", "bar-marker");
      for (const [name, value] of [["x", box.x], ["y", box.y], ["width", box.width], ["height", box.height]] as const) {
        band.setAttribute(name, String(value));
      }
      measure.prepend(band);
    }
  }

  announce(text: string): void {
    // A repeated text must still be announced, so clear first.
    this.el.status.textContent = "";
    this.el.status.textContent = text;
  }

  applyHostContext(context: HostContext): void {
    applyTheme(this.doc.documentElement, context);
  }

  containerWidth(): number {
    const style = getComputedStyle(this.el.score);
    return Math.max(0, this.el.score.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight));
  }

  prefersReducedMotion(): boolean {
    return matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  playClip(url: string): void {
    this.el.clip.src = url;
    void this.el.clip.play().catch(() => {});
  }

  private renderParts(view: PlayerView): void {
    const { el } = this;
    const ids = view.parts.map((part) => part.id).join("\n");
    if (ids !== this.partIds) {
      this.partIds = ids;
      el.parts.replaceChildren(...view.parts.map((part) => this.partRow(part)));
      el.focus.replaceChildren(
        ...view.parts.map((part) => {
          const option = this.doc.createElement("option");
          option.value = part.id;
          option.textContent = part.name;
          return option;
        }),
      );
    }
    if (view.focus) el.focus.value = view.focus;
    const rows = new Map(Array.from(el.parts.children).map((row) => [(row as HTMLElement).dataset.part, row]));
    for (const part of view.parts) {
      const row = rows.get(part.id) as HTMLElement | undefined;
      if (!row) continue;
      row.querySelector<HTMLButtonElement>('[data-action="solo"]')?.setAttribute("aria-pressed", String(part.solo));
      row.querySelector<HTMLButtonElement>('[data-action="mute"]')?.setAttribute("aria-pressed", String(part.muted));
      const slider = row.querySelector<HTMLInputElement>("input");
      const output = row.querySelector("output");
      const percent = Math.round(part.volume * 100);
      if (slider && slider !== this.doc.activeElement) slider.value = String(percent);
      if (output) output.textContent = `${percent} %`;
      if (slider) slider.disabled = view.phase !== "ready";
      for (const button of row.querySelectorAll("button")) button.disabled = view.phase !== "ready";
    }
  }

  private partRow(part: PartView): HTMLElement {
    const row = this.doc.createElement("li");
    row.className = "part";
    row.dataset.part = part.id;

    const name = this.doc.createElement("span");
    name.className = "name";
    name.textContent = part.name;

    const solo = this.toggleButton(part, "solo", "Solo");
    const mute = this.toggleButton(part, "mute", "Mute");

    const volume = this.doc.createElement("div");
    volume.className = "volume";
    const slider = this.doc.createElement("input");
    slider.type = "range";
    slider.min = "0";
    slider.max = "200";
    slider.step = "5";
    slider.dataset.part = part.id;
    slider.setAttribute("aria-label", `${part.name} volume`);
    const output = this.doc.createElement("output");
    output.setAttribute("aria-hidden", "true");
    volume.append(slider, output);

    row.append(name, solo, mute, volume);
    return row;
  }

  private toggleButton(part: PartView, action: "solo" | "mute", label: string): HTMLButtonElement {
    const button = this.doc.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.dataset.part = part.id;
    button.dataset.action = action;
    button.setAttribute("aria-label", `${label} ${part.name}`);
    button.setAttribute("aria-pressed", "false");
    return button;
  }
}
