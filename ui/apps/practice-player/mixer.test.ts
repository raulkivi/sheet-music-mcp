import { describe, expect, it } from "vitest";
import {
  applyPreset,
  effectiveGains,
  fromTrackParts,
  setVolume,
  toggleMute,
  toggleSolo,
  type MixerState,
} from "./mixer.ts";

const SATB = [
  { id: "P1", name: "Soprano", included: true, gain: 1 },
  { id: "P2", name: "Alto", included: true, gain: 1 },
  { id: "P3", name: "Tenor", included: true, gain: 1 },
  { id: "P4", name: "Bass", included: true, gain: 1 },
];

function mixer(): MixerState {
  return fromTrackParts(SATB);
}

describe("fromTrackParts", () => {
  it("takes volume from the gain the server used", () => {
    const state = fromTrackParts([{ id: "P1", name: "Soprano", included: true, gain: 1.5 }]);
    expect(effectiveGains(state)).toEqual({ P1: 1.5 });
  });

  it("starts a part the track left out as muted at normal volume", () => {
    const state = fromTrackParts([
      { id: "P1", name: "Soprano", included: true, gain: 1 },
      { id: "P2", name: "Alto", included: false, gain: 0 },
    ]);
    expect(effectiveGains(state)).toEqual({ P1: 1, P2: 0 });
    expect(effectiveGains(toggleMute(state, "P2"))).toEqual({ P1: 1, P2: 1 });
  });

  it("starts a part the server set silent as muted, keeping a usable volume", () => {
    const state = fromTrackParts([{ id: "P1", name: "Soprano", included: true, gain: 0 }]);
    expect(effectiveGains(state)).toEqual({ P1: 0 });
    expect(effectiveGains(toggleMute(state, "P1"))).toEqual({ P1: 1 });
  });
});

describe("mute, solo and volume", () => {
  it("mute silences one part and a second toggle restores its volume", () => {
    const muted = toggleMute(setVolume(mixer(), "P2", 1.5), "P2");
    expect(effectiveGains(muted)).toEqual({ P1: 1, P2: 0, P3: 1, P4: 1 });
    expect(effectiveGains(toggleMute(muted, "P2")).P2).toBe(1.5);
  });

  it("solo silences every other part", () => {
    expect(effectiveGains(toggleSolo(mixer(), "P2"))).toEqual({ P1: 0, P2: 1, P3: 0, P4: 0 });
  });

  it("several solos play together, and a second toggle removes one", () => {
    const both = toggleSolo(toggleSolo(mixer(), "P1"), "P2");
    expect(effectiveGains(both)).toEqual({ P1: 1, P2: 1, P3: 0, P4: 0 });
    expect(effectiveGains(toggleSolo(both, "P1"))).toEqual({ P1: 0, P2: 1, P3: 0, P4: 0 });
    expect(effectiveGains(toggleSolo(toggleSolo(both, "P1"), "P2"))).toEqual({ P1: 1, P2: 1, P3: 1, P4: 1 });
  });

  it("a muted part stays silent even when soloed", () => {
    const state = toggleSolo(toggleMute(mixer(), "P2"), "P2");
    expect(effectiveGains(state).P2).toBe(0);
  });

  it("volume is clamped to the server's 0 to 2", () => {
    expect(effectiveGains(setVolume(mixer(), "P1", 5)).P1).toBe(2);
    expect(effectiveGains(setVolume(mixer(), "P1", -1)).P1).toBe(0);
    expect(effectiveGains(setVolume(mixer(), "P1", Number.NaN)).P1).toBe(1);
  });

  it("does not change the state it was given", () => {
    const before = mixer();
    toggleMute(before, "P1");
    toggleSolo(before, "P1");
    setVolume(before, "P1", 0.2);
    expect(effectiveGains(before)).toEqual({ P1: 1, P2: 1, P3: 1, P4: 1 });
  });

  it("ignores a part it does not know", () => {
    expect(effectiveGains(toggleMute(mixer(), "P9"))).toEqual({ P1: 1, P2: 1, P3: 1, P4: 1 });
  });
});

describe("applyPreset", () => {
  it("learning: the focus part loud, the others soft", () => {
    expect(effectiveGains(applyPreset(mixer(), "learning", "P2"))).toEqual({ P1: 0.5, P2: 1.5, P3: 0.5, P4: 0.5 });
  });

  it("karaoke: the focus part muted, the others normal", () => {
    expect(effectiveGains(applyPreset(mixer(), "karaoke", "P3"))).toEqual({ P1: 1, P2: 1, P3: 0, P4: 1 });
  });

  it("equal: every part at normal volume", () => {
    const changed = setVolume(toggleSolo(mixer(), "P1"), "P2", 0.3);
    expect(effectiveGains(applyPreset(changed, "equal", "P1"))).toEqual({ P1: 1, P2: 1, P3: 1, P4: 1 });
  });

  it("clears earlier solos and mutes", () => {
    const state = applyPreset(toggleMute(toggleSolo(mixer(), "P1"), "P4"), "learning", "P2");
    expect(state.solo).toEqual([]);
    expect(effectiveGains(state).P4).toBe(0.5);
  });

  it("karaoke keeps the focus part unmutable again: a toggle brings it back at normal volume", () => {
    const state = toggleMute(applyPreset(mixer(), "karaoke", "P3"), "P3");
    expect(effectiveGains(state).P3).toBe(1);
  });
});
