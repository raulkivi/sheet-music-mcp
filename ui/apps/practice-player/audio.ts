// AudioPort over an <audio> element. Tries a blob: URL first and falls back to a data: URL,
// because a host's CSP may allow `media-src data:` but not `blob:` (the spec's default policy
// lists `media-src 'self' data:`, and a resource cannot ask for more).

import type { AudioPort } from "./ports.ts";

/** The slice of HTMLAudioElement used, so tests need no DOM. */
export interface AudioElementLike {
  src: string;
  currentTime: number;
  playbackRate: number;
  preservesPitch: boolean;
  load(): void;
  play(): Promise<void>;
  pause(): void;
  addEventListener(type: string, handler: () => void): void;
  removeEventListener(type: string, handler: () => void): void;
}

export interface UrlSource {
  objectUrl(blob: Blob): string;
  revoke(url: string): void;
  dataUrl(blob: Blob): Promise<string>;
}

export const browserUrls: UrlSource = {
  objectUrl: (blob) => URL.createObjectURL(blob),
  revoke: (url) => URL.revokeObjectURL(url),
  dataUrl: (blob) =>
    new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.onerror = () => reject(reader.error ?? new Error("The audio could not be read."));
      reader.readAsDataURL(blob);
    }),
};

export class AudioElementPort implements AudioPort {
  private blobUrl: string | undefined;

  constructor(
    private readonly element: AudioElementLike,
    private readonly urls: UrlSource = browserUrls,
  ) {}

  async load(blob: Blob): Promise<void> {
    this.releaseBlobUrl();
    const url = this.urls.objectUrl(blob);
    this.blobUrl = url;
    if (await this.tryLoad(url)) return;
    this.releaseBlobUrl();
    if (await this.tryLoad(await this.urls.dataUrl(blob))) return;
    throw new Error("The browser could not decode the practice track.");
  }

  play(): Promise<void> {
    return this.element.play();
  }

  pause(): void {
    this.element.pause();
  }

  get position(): number {
    return this.element.currentTime;
  }

  seek(seconds: number): void {
    this.element.currentTime = seconds;
  }

  setRate(rate: number): void {
    this.element.playbackRate = rate;
    this.element.preservesPitch = true;
  }

  onEnded(listener: () => void): void {
    this.element.addEventListener("ended", listener);
  }

  /** Resolves true once the element has the track's metadata, false if it refuses the source. */
  private tryLoad(src: string): Promise<boolean> {
    return new Promise((resolve) => {
      const done = (ok: boolean) => {
        this.element.removeEventListener("loadedmetadata", onLoaded);
        this.element.removeEventListener("error", onError);
        resolve(ok);
      };
      const onLoaded = () => done(true);
      const onError = () => done(false);
      this.element.addEventListener("loadedmetadata", onLoaded);
      this.element.addEventListener("error", onError);
      this.element.src = src;
      this.element.preservesPitch = true;
      this.element.load();
    });
  }

  private releaseBlobUrl(): void {
    if (this.blobUrl === undefined) return;
    this.urls.revoke(this.blobUrl);
    this.blobUrl = undefined;
  }
}
