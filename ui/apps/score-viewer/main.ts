// Composition root: real host bridge, both renderers and DOM, wired into the ScoreViewer.

import { createExtAppsBridge } from "@sheet-music-mcp/ui-kit/host/ExtAppsBridge";
import { ScoreView } from "@sheet-music-mcp/ui-kit/score/ScoreView";
import { ServerScoreRenderer } from "@sheet-music-mcp/ui-kit/score/ServerScoreRenderer";
import { DomUi } from "./dom.ts";
import { ScoreViewer } from "./viewer.ts";
import "./style.css";

const bridge = createExtAppsBridge({
  name: "sheet-music-score-viewer",
  version: "0.1.0",
  displayModes: ["inline", "fullscreen"],
});
const ui = new DomUi(document);
// Verovio WASM first; hosts whose CSP refuses WebAssembly get pages from render_page_svg.
const viewer = new ScoreViewer(bridge, [() => ScoreView.create(), async () => new ServerScoreRenderer(bridge)], ui);
ui.bind(viewer);

viewer.start().catch((error: unknown) => {
  ui.showNotice("The viewer could not connect to the host.");
  console.error(error);
});
