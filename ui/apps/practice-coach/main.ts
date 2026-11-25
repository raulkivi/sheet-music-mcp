// Composition root: real host bridge, both score renderers, the DOM and the adaptive poller wired
// into the PracticeCoach. T1.5 plugs its tips handler into `options.tips` here.

import { createExtAppsBridge } from "@sheet-music-mcp/ui-kit/host/ExtAppsBridge";
import { ScoreView } from "@sheet-music-mcp/ui-kit/score/ScoreView";
import { ServerScoreRenderer } from "@sheet-music-mcp/ui-kit/score/ServerScoreRenderer";
import { PracticeCoach } from "./coach.ts";
import { DomUi } from "./dom.ts";
import { PollScheduler } from "./polling.ts";
import { ScoreDom } from "./scoreDom.ts";
import { ScoreStage } from "./scoreStage.ts";
import "./style.css";

const bridge = createExtAppsBridge({ name: "sheet-music-practice-coach", version: "0.1.0", displayModes: ["inline"] });
const ui = new DomUi(document);
const scoreDom = new ScoreDom(document);
// Verovio WASM first; hosts whose CSP refuses WebAssembly get pages from render_page_svg.
const stage = new ScoreStage([() => ScoreView.create(), async () => new ServerScoreRenderer(bridge)], scoreDom);

const coach = new PracticeCoach(bridge, ui, stage, (request) =>
  new PollScheduler(request, {
    now: () => performance.now(),
    setTimeout: (fn, ms) => {
      const id = setTimeout(fn, ms);
      return () => clearTimeout(id);
    },
    isHidden: () => document.hidden,
  }),
);
ui.bind(coach);
scoreDom.onResize((width) => void stage.resize(width));

coach.start().catch((error: unknown) => {
  ui.showMode("empty");
  ui.showNotice("The coach could not connect to the host.");
  console.error(error);
});
