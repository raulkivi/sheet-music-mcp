import { expect, test } from "@playwright/test";
import { PlayerFrame } from "./player-frame.ts";

// T1.9 (docs/research/mcp-apps-improvement-plan.md): the Practice Player in the mock host, with the
// placeholder synth server (test/mock-host/synth-mock.ts) answering the page's tool calls.

test.describe("render", () => {
  test("opens on the synthesize result: audio loaded in chunks, score drawn, every control ready", async ({ page }) => {
    const player = await PlayerFrame.ready(page);
    await expect(player.button("Play")).toBeEnabled();
    await expect(player.content.locator("#score svg").first()).toBeVisible();
    for (const name of ["Soprano", "Alto", "Tenor", "Bass"]) {
      await expect(player.solo(name)).toBeVisible();
      await expect(player.mute(name)).toBeVisible();
      await expect(player.volume(name)).toHaveValue("100");
    }
    await expect(player.tempo()).toHaveValue("100");
    await expect(player.loop()).toHaveAccessibleName("Loop bars 1 to 4");
    await expect(player.loop()).toHaveAttribute("aria-pressed", "true");
    await expect(player.button("Count-in")).toHaveAttribute("aria-pressed", "true");
    await expect(player.timbre()).toHaveValue("score");
    await expect(player.position()).toContainText("of 0:");
    const names = await player.callNames();
    expect(names.filter((name) => name === "read_audio_chunk").length).toBeGreaterThanOrEqual(1);
    expect(names).toContain("get_score_xml");
    expect(names).not.toContain("synthesize");
    expect((await player.audioState()).duration).toBeGreaterThan(5);
  });

  test("the player draws no sample data of its own: the parts are the track's", async ({ page }) => {
    const player = await PlayerFrame.open(page, {}, "practice-empty");
    await expect(player.content.locator("#parts li")).toHaveCount(0);
  });
});

test.describe("empty and error", () => {
  test("a result without a track says so and leaves the controls off", async ({ page }) => {
    const player = await PlayerFrame.open(page, {}, "practice-empty");
    await expect(player.notice()).toContainText("did not return a practice track");
    await expect(player.content.locator("#state")).toHaveText("No track");
    await expect(player.button("Play")).toBeDisabled();
  });

  test("an audio id the server does not know shows INVALID_PARAMETER", async ({ page }) => {
    const player = await PlayerFrame.open(page, {}, "practice-unknown-audio");
    await expect(player.notice()).toContainText("INVALID_PARAMETER");
    await expect(player.content.locator("#state")).toHaveText("Problem");
    await expect(player.button("Play")).toBeDisabled();
    expect(await player.callNames()).toEqual(["read_audio_chunk"]);
  });
});

test.describe("transport", () => {
  test("Play starts the audio and the playhead follows it; Pause stops both", async ({ page }) => {
    const player = await PlayerFrame.ready(page);
    await player.button("Play").click();
    await expect(player.button("Pause")).toBeVisible();
    await expect(player.status()).toHaveText("Playing");
    await expect.poll(async () => (await player.audioState()).currentTime).toBeGreaterThan(0.3);
    await expect(player.position()).toContainText(/Count-in|Bar/);
    await player.button("Pause").click();
    await expect(player.status()).toHaveText("Paused");
    expect((await player.audioState()).paused).toBe(true);
  });

  test("the seek slider moves the audio to a bar and the playhead marks it", async ({ page }) => {
    const player = await PlayerFrame.ready(page);
    await player.seek().focus();
    // Count-in is 1 bar at 90 BPM: 2.67 s. Bar 3 starts 2 bars (5.33 s) into the music.
    await player.seek().evaluate((input: HTMLInputElement) => {
      input.value = "8.2";
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await expect(player.position()).toContainText("Bar 3");
    await expect(player.score()).toHaveAttribute("data-bar", "2");
    await expect(player.content.locator("#score .bar-marker")).toHaveCount(1);
    expect((await player.audioState()).currentTime).toBeCloseTo(8.2, 1);
  });

  test("Restart returns to the start, count-in included", async ({ page }) => {
    const player = await PlayerFrame.ready(page);
    await player.seek().evaluate((input: HTMLInputElement) => {
      input.value = "6";
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await player.button("Restart").click();
    await expect.poll(async () => (await player.audioState()).currentTime).toBe(0);
    await expect(player.position()).toContainText("Count-in");
  });
});

test.describe("tempo (DA4: local first)", () => {
  test("the speed slider changes the playback rate, keeps the pitch and makes no tool call", async ({ page }) => {
    const player = await PlayerFrame.ready(page);
    const before = await player.callNames();
    await player.tempo().focus();
    await player.tempo().evaluate((input: HTMLInputElement) => {
      input.value = "50";
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await expect(player.content.locator("#tempo-label")).toHaveText("50 %");
    const audio = await player.audioState();
    expect(audio.playbackRate).toBe(0.5);
    expect(audio.preservesPitch).toBe(true);
    expect(await player.callNames()).toEqual(before);
    await expect(player.status()).toHaveText("Tempo 50 %");
  });

  test("the keyboard moves the slider by 5 % and stays inside 25 % to 400 %", async ({ page }) => {
    const player = await PlayerFrame.ready(page);
    await player.tempo().focus();
    await player.tempo().press("ArrowLeft");
    await expect(player.content.locator("#tempo-label")).toHaveText("95 %");
    await player.tempo().press("Home");
    await expect(player.content.locator("#tempo-label")).toHaveText("25 %");
    await player.tempo().press("End");
    await expect(player.content.locator("#tempo-label")).toHaveText("400 %");
  });
});

test.describe("mixer (DA3: solo, mute, volume and presets re-render once)", () => {
  test("a mute makes exactly one synthesize call with that part at 0, then swaps the audio", async ({ page }) => {
    const player = await PlayerFrame.ready(page);
    await player.mute("Alto").click();
    await expect(player.mute("Alto")).toHaveAttribute("aria-pressed", "true");
    await expect(player.content.locator("#state")).toHaveText("Ready");
    const renders = await player.calls("synthesize");
    expect(renders).toHaveLength(1);
    expect(renders[0]).toMatchObject({
      part_gains: { P1: 1, P2: 0, P3: 1, P4: 1 },
      measures: [1, 4],
      count_in_bars: 1,
      timbre: "score",
      tempo_factor: 1,
    });
    const chunkIds = (await player.calls("read_audio_chunk")).map((args) => args.audio_id);
    expect(new Set(chunkIds).size).toBe(2);
    await expect(player.status()).toHaveText("Mix updated");
  });

  test("a solo silences the other voices in one call", async ({ page }) => {
    const player = await PlayerFrame.ready(page);
    await player.solo("Tenor").click();
    await expect(player.solo("Tenor")).toHaveAttribute("aria-pressed", "true");
    await expect(player.content.locator("#state")).toHaveText("Ready");
    const renders = await player.calls("synthesize");
    expect(renders).toHaveLength(1);
    expect(renders[0]?.part_gains).toEqual({ P1: 0, P2: 0, P3: 1, P4: 0 });
  });

  test("a volume slider renders once, when the user lets go", async ({ page }) => {
    const player = await PlayerFrame.ready(page);
    await player.volume("Bass").evaluate((input: HTMLInputElement) => {
      for (const value of ["110", "120", "130"]) {
        input.value = value;
        input.dispatchEvent(new Event("input", { bubbles: true }));
      }
    });
    expect(await player.calls("synthesize")).toHaveLength(0);
    await player.volume("Bass").evaluate((input: HTMLInputElement) => input.dispatchEvent(new Event("change", { bubbles: true })));
    await expect(player.content.locator("#state")).toHaveText("Ready");
    const renders = await player.calls("synthesize");
    expect(renders).toHaveLength(1);
    expect(renders[0]?.part_gains).toEqual({ P1: 1, P2: 1, P3: 1, P4: 1.3 });
  });

  test("the learning preset sets the focus part loud and the others soft, and the sliders follow", async ({ page }) => {
    const player = await PlayerFrame.ready(page);
    await player.focusPart().selectOption("P2");
    await player.preset().selectOption("learning");
    await expect(player.volume("Alto")).toHaveValue("150");
    await expect(player.volume("Soprano")).toHaveValue("50");
    const renders = await player.calls("synthesize");
    expect(renders.at(-1)?.part_gains).toEqual({ P1: 0.5, P2: 1.5, P3: 0.5, P4: 0.5 });
  });

  test("a mix change while playing keeps playing at the same place", async ({ page }) => {
    const player = await PlayerFrame.ready(page);
    await player.button("Play").click();
    await expect.poll(async () => (await player.audioState()).currentTime).toBeGreaterThan(0.5);
    await player.mute("Soprano").click();
    await expect(player.mute("Soprano")).toHaveAttribute("aria-pressed", "true");
    await expect(player.content.locator("#state")).toHaveText("Ready");
    await expect.poll(async () => (await player.audioState()).paused).toBe(false);
    expect((await player.audioState()).currentTime).toBeGreaterThan(0.3);
  });
});

test.describe("count-in, loop and sound", () => {
  test("count-in off re-renders with count_in_bars 0 and the track gets shorter", async ({ page }) => {
    const player = await PlayerFrame.ready(page);
    const before = (await player.audioState()).duration;
    await player.button("Count-in").click();
    await expect(player.button("Count-in")).toHaveAttribute("aria-pressed", "false");
    await expect(player.content.locator("#state")).toHaveText("Ready");
    expect((await player.calls("synthesize")).at(-1)).toMatchObject({ count_in_bars: 0 });
    await expect.poll(async () => (await player.audioState()).duration).toBeLessThan(before - 1);
  });

  test("the loop button is local: no tool call, and it names the bars it is bound to", async ({ page }) => {
    const player = await PlayerFrame.ready(page);
    const before = await player.callNames();
    await player.loop().click();
    await expect(player.loop()).toHaveAttribute("aria-pressed", "false");
    await expect(player.status()).toHaveText("Loop off");
    expect(await player.callNames()).toEqual(before);
  });

  test("a sound change renders once with that timbre", async ({ page }) => {
    const player = await PlayerFrame.ready(page);
    await player.timbre().selectOption("choir");
    await expect(player.content.locator("#state")).toHaveText("Ready");
    const renders = await player.calls("synthesize");
    expect(renders).toHaveLength(1);
    expect(renders[0]).toMatchObject({ timbre: "choir" });
  });

  test("starting pitches shows the notes the server gave", async ({ page }) => {
    const player = await PlayerFrame.ready(page);
    await player.button("Starting pitches").click();
    await expect(player.content.locator("#pitches-text")).toContainText("Soprano: D5, Alto: A4, Tenor: F#4, Bass: D3");
    expect((await player.calls("starting_pitches")).at(0)).toHaveProperty("musicxml");
  });
});

test("the page tells the model the state after a change", async ({ page }) => {
  const player = await PlayerFrame.ready(page);
  await player.mute("Alto").click();
  await expect(player.content.locator("#state")).toHaveText("Ready");
  await expect
    .poll(async () =>
      (
        await page.evaluate(() =>
          (window as unknown as { __host: { messages(m: string): { direction: string; params?: { content?: { text?: string }[] } }[] } }).__host
            .messages("ui/update-model-context")
            .map((message) => message.params?.content?.[0]?.text),
        )
      ).at(-1),
    )
    .toBe("Practice Player: tempo 100 %, loop on (bars 1 to 4), count-in 1 bar, parts playing: P1, P3, P4; muted: P2.");
});
