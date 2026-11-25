// Composition root: real host bridge, <audio> element, Verovio score engine and DOM, wired into
// the PracticePlayer.

import { createExtAppsBridge } from "@sheet-music-mcp/ui-kit/host/ExtAppsBridge";
import { ScoreView } from "@sheet-music-mcp/ui-kit/score/ScoreView";
import { AudioElementPort } from "./audio.ts";
import { DomUi } from "./dom.ts";
import { PracticePlayer } from "./player.ts";
import "./style.css";

const bridge = createExtAppsBridge({
  name: "sheet-music-practice-player",
  version: "0.1.0",
  displayModes: ["inline"],
});
const ui = new DomUi(document);
const player = new PracticePlayer(bridge, {
  ui,
  audio: new AudioElementPort(ui.audioElement),
  frames: { request: (callback) => void requestAnimationFrame(() => callback()) },
  // Verovio WASM only: where the host's CSP refuses WebAssembly the page still plays the audio.
  openScore: () => ScoreView.create(),
});
ui.bind(player);

player.start().catch((error: unknown) => {
  ui.render({
    phase: "error",
    notice: "The player could not connect to the host.",
    busy: false,
    parts: [],
    preset: "",
    focus: "",
    tempoPercent: 100,
    playing: false,
    loop: false,
    loopLabel: "",
    countInOn: false,
    timbre: "score",
    durationSeconds: 0,
  });
  console.error(error);
});
