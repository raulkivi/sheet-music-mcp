import { describe, expect, it } from "vitest";
import { PollScheduler, type PollEnv } from "./polling.ts";

const flush = () => new Promise<void>((resolve) => setImmediate(resolve));

/** A manual clock: timers fire only when the test advances time. */
class FakeEnv implements PollEnv {
  time = 0;
  hidden = false;
  private timers: { at: number; fn: () => void; id: number }[] = [];
  private next = 1;

  now = () => this.time;
  isHidden = () => this.hidden;
  setTimeout = (fn: () => void, ms: number) => {
    const id = this.next++;
    this.timers.push({ at: this.time + ms, fn, id });
    return () => void (this.timers = this.timers.filter((t) => t.id !== id));
  };

  get pending(): number {
    return this.timers.length;
  }

  /** Advances time, firing due timers in order and letting promises settle between them. */
  async advance(ms: number): Promise<void> {
    const end = this.time + ms;
    for (;;) {
      await flush();
      const due = this.timers.filter((t) => t.at <= end).sort((a, b) => a.at - b.at)[0];
      if (!due) break;
      this.timers = this.timers.filter((t) => t !== due);
      this.time = Math.max(this.time, due.at);
      due.fn();
    }
    this.time = end;
    await flush();
  }
}

/** A request that takes `rtt()` ms of fake time. */
function requester(env: FakeEnv, rtt: () => number) {
  const calls: number[] = [];
  const request = async () => {
    calls.push(env.time);
    await new Promise<void>((resolve) => env.setTimeout(resolve, rtt()));
  };
  return { calls, request };
}

describe("PollScheduler", () => {
  it("polls at 10 Hz while round trips are fast", async () => {
    const env = new FakeEnv();
    const { calls, request } = requester(env, () => 20);
    const poller = new PollScheduler(request, env);
    poller.start();
    await env.advance(1000);
    expect(calls.length).toBeGreaterThanOrEqual(9);
    expect(calls.length).toBeLessThanOrEqual(11);
    expect(poller.intervalMs).toBe(100);
    poller.stop();
  });

  it("backs off to 5 Hz when the median round trip exceeds 80 ms", async () => {
    const env = new FakeEnv();
    const { request } = requester(env, () => 120);
    const poller = new PollScheduler(request, env);
    poller.start();
    await env.advance(2000);
    expect(poller.intervalMs).toBe(200);
    poller.stop();
  });

  it("is not fooled by one slow reply among fast ones (the median decides)", async () => {
    const env = new FakeEnv();
    let n = 0;
    const { request } = requester(env, () => (++n === 3 ? 400 : 20));
    const poller = new PollScheduler(request, env);
    poller.start();
    await env.advance(2000);
    expect(poller.intervalMs).toBe(100);
    poller.stop();
  });

  it("returns to 10 Hz once round trips are fast again, not at the first fast one", async () => {
    const env = new FakeEnv();
    let slow = true;
    const { request } = requester(env, () => (slow ? 120 : 20));
    const poller = new PollScheduler(request, env);
    poller.start();
    await env.advance(2000);
    expect(poller.intervalMs).toBe(200);
    slow = false;
    await env.advance(300);
    expect(poller.intervalMs).toBe(200);
    await env.advance(2000);
    expect(poller.intervalMs).toBe(100);
    poller.stop();
  });

  it("never has two requests in flight", async () => {
    const env = new FakeEnv();
    let inFlight = 0;
    let most = 0;
    const poller = new PollScheduler(async () => {
      most = Math.max(most, ++inFlight);
      await new Promise<void>((resolve) => env.setTimeout(resolve, 350));
      inFlight--;
    }, env);
    poller.start();
    await env.advance(3000);
    expect(most).toBe(1);
    poller.stop();
  });

  it("sends no request while the document is hidden, and resumes when it is shown", async () => {
    const env = new FakeEnv();
    const { calls, request } = requester(env, () => 10);
    const poller = new PollScheduler(request, env);
    poller.start();
    await env.advance(500);
    env.hidden = true;
    await env.advance(300); // an in-flight request may finish; the next is not sent
    const whileHidden = calls.length;
    await env.advance(5000);
    expect(calls.length).toBe(whileHidden);
    expect(env.pending).toBe(0);

    env.hidden = false;
    poller.onVisibilityChange();
    await env.advance(500);
    expect(calls.length).toBeGreaterThan(whileHidden + 3);
    poller.stop();
  });

  it("does not start while the document is hidden, until it is shown", async () => {
    const env = new FakeEnv();
    env.hidden = true;
    const { calls, request } = requester(env, () => 10);
    const poller = new PollScheduler(request, env);
    poller.start();
    await env.advance(1000);
    expect(calls).toEqual([]);
    env.hidden = false;
    poller.onVisibilityChange();
    await env.advance(200);
    expect(calls.length).toBeGreaterThan(0);
    poller.stop();
  });

  it("stops: no further request and no timer left", async () => {
    const env = new FakeEnv();
    const { calls, request } = requester(env, () => 10);
    const poller = new PollScheduler(request, env);
    poller.start();
    await env.advance(300);
    poller.stop();
    const sent = calls.length;
    await env.advance(2000);
    expect(calls.length).toBe(sent);
    expect(env.pending).toBe(0);
    expect(poller.running).toBe(false);
  });

  it("start twice does not double the rate", async () => {
    const env = new FakeEnv();
    const { calls, request } = requester(env, () => 10);
    const poller = new PollScheduler(request, env);
    poller.start();
    poller.start();
    await env.advance(1000);
    expect(calls.length).toBeLessThanOrEqual(11);
    poller.stop();
  });

  it("keeps polling after a request throws", async () => {
    const env = new FakeEnv();
    let n = 0;
    const poller = new PollScheduler(async () => {
      n++;
      throw new Error("host gone");
    }, env);
    poller.start();
    await env.advance(1000);
    expect(n).toBeGreaterThan(3);
    poller.stop();
  });
});
