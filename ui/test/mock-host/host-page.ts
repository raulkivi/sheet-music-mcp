// The mock MCP Apps host's page: embeds the built app in a sandboxed iframe and speaks the host
// side of the protocol with ext-apps' own AppBridge over postMessage, as real hosts do. This file
// only wires the parts together: options.ts (query), scenarios.ts (the opening tool call),
// tool-backends.ts (who answers tools/call) and message-log.ts (window.__host.log).
// Built to dist/host.js by vite.config.ts beside it; never part of the app build.

import {
  AppBridge,
  PostMessageTransport,
  type McpUiDisplayMode,
  type McpUiHostContext,
} from "@modelcontextprotocol/ext-apps/app-bridge";
import { LoggingTransport, MessageLog, type LoggedMessage } from "./message-log.ts";
import { hostStyleVariables } from "./host-styles.ts";
import { hostOptions } from "./options.ts";
import { isAbcScenario, abcTools } from "./abc-tools.ts";
import { diffTools } from "./diff-backend.ts";
import { pitchTools } from "./pitch-backend.ts";
import { openingCall } from "./scenarios.ts";
import { composeTools, noTools, placeholderTools, relayedTools, type Relay, type ToolBackend } from "./tool-backends.ts";

declare global {
  interface Window {
    /** Exposed by the Playwright fixture when the spec runs the real render-mcp. */
    mcpHostRelay?: Relay;
    __host: {
      log: LoggedMessage[];
      resize(width: number): void;
      setTheme(name: "light" | "dark"): void;
      messages(method: string): LoggedMessage[];
    };
  }
}

const MAX_HEIGHT = 6000;
type StyleVariables = NonNullable<NonNullable<McpUiHostContext["styles"]>["variables"]>;

const options = hostOptions(location.search);

function viewTools(): ToolBackend {
  if (options.tools === "none") return noTools;
  if (options.tools === "placeholder") {
    if (isAbcScenario(options.scenario)) return abcTools(options.scenario);
    if (options.app === "diff-viewer") return diffTools;
    // The coach scenarios add pitch-mcp's session tools to the placeholder pages.
    if (!options.scenario.startsWith("coach")) return placeholderTools;
    const state = options.scenario === "coach-loaded" ? "loaded" : "monitoring";
    return composeTools(pitchTools({ xml: scoreXml, take: options.take, state, latencyMs: options.latencyMs }), placeholderTools);
  }
  if (!window.mcpHostRelay) throw new Error("server=real needs window.mcpHostRelay: use the renderMcp fixture (test/e2e/host-fixture.ts)");
  return relayedTools(window.mcpHostRelay);
}

// The score the coach's get_score_for_session returns (the scenario's own input for the coach).
const scoreXml = options.scenario.startsWith("coach") ? await (await fetch("/fixtures/satb-4bars.musicxml")).text() : "";
const tools = viewTools();
const opening = await openingCall(options.scenario, options.tools === "real" ? tools : undefined);

const log = new MessageLog();
const box = document.getElementById("frame-box")!;
let inlineWidth = options.width;
box.style.width = `${inlineWidth}px`;
const frame = document.createElement("iframe");
frame.title = options.app === "diff-viewer" ? "Diff Viewer" : options.app === "practice-coach" ? "Practice Coach" : options.app === "abc-workbench" ? "ABC Workbench" : "Score Viewer";
frame.setAttribute("sandbox", options.downloads ? "allow-scripts allow-downloads" : "allow-scripts");
// A host grants the resource's `clipboardWrite` permission by delegating it to the frame.
if (options.clipboard) frame.setAttribute("allow", "clipboard-write");

let displayMode: McpUiDisplayMode = "inline";
const hostContext: McpUiHostContext = {
  theme: options.theme,
  styles: { variables: hostStyleVariables(options.host, options.theme) as StyleVariables },
  displayMode,
  availableDisplayModes: options.modes,
  containerDimensions: { width: options.width, maxHeight: MAX_HEIGHT },
  locale: "en-US",
  platform: "web",
  toolInfo: { tool: { name: opening.tool, inputSchema: { type: "object" } } },
} as McpUiHostContext;

const bridge = new AppBridge(
  null,
  { name: "mock-host", version: "0.0.0" },
  { serverTools: {}, logging: {}, openLinks: {}, message: { text: {} }, updateModelContext: { text: {} } },
  { hostContext },
);

bridge.oncalltool = (params) => tools.callTool(params);
bridge.onmessage = async () => ({});
// The host would open the link in the user's browser; the log records the request.
bridge.onopenlink = async () => ({});
bridge.onupdatemodelcontext = async () => ({});
bridge.onrequestdisplaymode = async ({ mode }) => {
  if (options.modes.includes(mode)) displayMode = mode;
  // Fullscreen fills the window, as hosts do; inline goes back to the container's width.
  const fullscreen = displayMode === "fullscreen";
  document.body.classList.toggle("fullscreen", fullscreen);
  const containerDimensions = fullscreen
    ? { width: innerWidth, height: innerHeight }
    : { width: Math.min(inlineWidth, box.clientWidth), maxHeight: MAX_HEIGHT };
  queueMicrotask(() => void bridge.sendHostContextChange({ displayMode, containerDimensions }));
  return { mode: displayMode };
};
bridge.onsizechange = ({ height }) => {
  if (displayMode === "fullscreen") return;
  if (height !== undefined && height > 0) frame.style.height = `${Math.min(height, MAX_HEIGHT)}px`;
};
bridge.oninitialized = () => {
  void bridge.sendToolInput({ arguments: opening.input }).then(() => bridge.sendToolResult(opening.result));
};

window.__host = {
  log: log.entries,
  /** Resizes the container like a host would and tells the app (containerDimensions). */
  resize(newWidth) {
    inlineWidth = newWidth;
    box.style.width = `${newWidth}px`;
    void bridge.sendHostContextChange({ containerDimensions: { width: newWidth, maxHeight: MAX_HEIGHT } });
  },
  setTheme(name) {
    void bridge.sendHostContextChange({ theme: name, styles: { variables: hostStyleVariables(options.host, name) as StyleVariables } });
  },
  messages: (method) => log.messages(method),
};

box.append(frame);
// Listen before the app loads, so its ui/initialize is never missed; the iframe's WindowProxy
// stays the same across the navigation.
await bridge.connect(new LoggingTransport(new PostMessageTransport(frame.contentWindow!, frame.contentWindow!), log));
frame.src = `/app.html?app=${encodeURIComponent(options.app)}&csp=${encodeURIComponent(options.csp)}`;
