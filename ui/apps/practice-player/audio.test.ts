import { describe, expect, it } from "vitest";
import { AudioElementPort, type AudioElementLike } from "./audio.ts";

type Handler = () => void;

class FakeElement implements AudioElementLike {
  src = "";
  currentTime = 0;
  playbackRate = 1;
  preservesPitch = false;
  played = 0;
  paused = 0;
  /** Which sources the "browser" accepts. */
  accepts: (src: string) => boolean = () => true;
  private handlers = new Map<string, Handler[]>();
  addEventListener(type: string, handler: Handler) {
    this.handlers.set(type, [...(this.handlers.get(type) ?? []), handler]);
  }
  removeEventListener(type: string, handler: Handler) {
    this.handlers.set(type, (this.handlers.get(type) ?? []).filter((h) => h !== handler));
  }
  load() {
    const src = this.src;
    queueMicrotask(() => this.fire(this.accepts(src) ? "loadedmetadata" : "error"));
  }
  async play() {
    this.played += 1;
  }
  pause() {
    this.paused += 1;
  }
  fire(type: string) {
    for (const handler of this.handlers.get(type) ?? []) handler();
  }
}

function port(element: FakeElement) {
  const revoked: string[] = [];
  const instance = new AudioElementPort(element, {
    objectUrl: () => "blob:fake",
    revoke: (url) => void revoked.push(url),
    dataUrl: async () => "data:audio/wav;base64,AAAA",
  });
  return { instance, revoked };
}

const BLOB = new Blob(["x"], { type: "audio/wav" });

describe("AudioElementPort", () => {
  it("plays a blob URL when the host allows it", async () => {
    const element = new FakeElement();
    await port(element).instance.load(BLOB);
    expect(element.src).toBe("blob:fake");
    expect(element.preservesPitch).toBe(true);
  });

  it("falls back to a data: URL when the host's CSP refuses blob: media", async () => {
    const element = new FakeElement();
    element.accepts = (src) => src.startsWith("data:");
    const { instance, revoked } = port(element);
    await instance.load(BLOB);
    expect(element.src).toBe("data:audio/wav;base64,AAAA");
    expect(revoked).toEqual(["blob:fake"]);
  });

  it("rejects when neither source can be decoded", async () => {
    const element = new FakeElement();
    element.accepts = () => false;
    await expect(port(element).instance.load(BLOB)).rejects.toThrow(/decode|play/i);
  });

  it("revokes the previous blob URL when a new track is loaded", async () => {
    const element = new FakeElement();
    const { instance, revoked } = port(element);
    await instance.load(BLOB);
    await instance.load(BLOB);
    expect(revoked).toEqual(["blob:fake"]);
  });

  it("passes play, pause, position, seek and rate through to the element", async () => {
    const element = new FakeElement();
    const { instance } = port(element);
    await instance.load(BLOB);
    await instance.play();
    instance.pause();
    instance.seek(3.5);
    instance.setRate(0.5);
    expect([element.played, element.paused, element.currentTime, element.playbackRate]).toEqual([1, 1, 3.5, 0.5]);
    expect(instance.position).toBe(3.5);
  });

  it("keeps the pitch whenever the rate is set", async () => {
    const element = new FakeElement();
    const { instance } = port(element);
    element.preservesPitch = false;
    instance.setRate(0.75);
    expect(element.preservesPitch).toBe(true);
  });

  it("calls the ended listeners", async () => {
    const element = new FakeElement();
    const { instance } = port(element);
    let ended = 0;
    instance.onEnded(() => (ended += 1));
    element.fire("ended");
    expect(ended).toBe(1);
  });
});
