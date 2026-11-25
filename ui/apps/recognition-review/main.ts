// Composition root: real host bridge, Verovio pane and DOM, wired into the RecognitionReview.

import { createExtAppsBridge } from "@sheet-music-mcp/ui-kit/host/ExtAppsBridge";
import { DomUi } from "./dom.ts";
import { RecognitionReview } from "./reviewer.ts";
import { VerovioPane } from "./score.ts";
import "./style.css";

const bridge = createExtAppsBridge({ name: "sheet-music-recognition-review", version: "0.1.0", displayModes: ["inline"] });
const ui = new DomUi(document);
const pane = new VerovioPane(document.getElementById("score")!);
const review = new RecognitionReview(bridge, ui, pane);
ui.bind(review);

review.start().catch((error: unknown) => {
  ui.showNotices(["The review could not connect to the host."]);
  console.error(error);
});
