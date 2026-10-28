// Composition root: real host bridge, Verovio renderer and DOM, wired into the ScoreViewer.

import { createExtAppsBridge } from "@sheet-music-mcp/ui-kit/host/ExtAppsBridge";
import { ScoreView } from "@sheet-music-mcp/ui-kit/score/ScoreView";
import { DomUi } from "./dom.ts";
import { ScoreViewer } from "./viewer.ts";
import "./style.css";

const bridge = createExtAppsBridge({
  name: "sheet-music-score-viewer",
  version: "0.1.0",
  displayModes: ["inline", "fullscreen"],
});
const ui = new DomUi(document);
const viewer = new ScoreViewer(bridge, () => ScoreView.create(), ui);
ui.bind(viewer);

viewer.start().catch((error: unknown) => {
  ui.showNotice("The viewer could not connect to the host.");
  console.error(error);
});
