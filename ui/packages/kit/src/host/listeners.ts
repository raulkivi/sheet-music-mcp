import type { Unsubscribe } from "./HostBridge.ts";

/** A listener set that remembers the last event, so late subscribers still get it. */
export class Listeners<T> {
  private readonly set = new Set<(value: T) => void>();
  private last: { value: T } | undefined;

  constructor(private readonly replayLast = false) {}

  add(listener: (value: T) => void): Unsubscribe {
    this.set.add(listener);
    if (this.replayLast && this.last) listener(this.last.value);
    return () => this.set.delete(listener);
  }

  emit(value: T): void {
    this.last = { value };
    for (const listener of [...this.set]) listener(value);
  }
}
