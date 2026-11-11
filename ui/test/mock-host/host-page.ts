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
import { hostOptions } from "./options.ts";
import { openingCall, OPENING_TOOL } from "./scenarios.ts";
import { noTools, placeholderTools, relayedTools, type Relay, type ToolBackend } from "./tool-backends.ts";

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
// A partial set, as hosts send: the type lists every variable, the protocol requires none.
type StyleVariables = NonNullable<NonNullable<McpUiHostContext["styles"]>["variables"]>;
const DARK_VARIABLES = {
  "--color-background-primary": "#131314",
  "--color-text-primary": "#f2f2f2",
} as StyleVariables;
const NO_VARIABLES = {} as StyleVariables;

const options = hostOptions(location.search);

function viewTools(): ToolBackend {
  if (options.tools === "none") return noTools;
  if (options.tools === "placeholder") return placeholderTools;
  if (!window.mcpHostRelay) throw new Error("server=real needs window.mcpHostRelay: use the renderMcp fixture (test/e2e/host-fixture.ts)");
  return relayedTools(window.mcpHostRelay);
}

const tools = viewTools();
const opening = await openingCall(options.scenario, options.tools === "real" ? tools : undefined);

const log = new MessageLog();
const box = document.getElementById("frame-box")!;
let inlineWidth = options.width;
box.style.width = `${inlineWidth}px`;
const frame = document.createElement("iframe");
frame.title = "Score Viewer";
frame.setAttribute("sandbox", options.downloads ? "allow-scripts allow-downloads" : "allow-scripts");

let displayMode: McpUiDisplayMode = "inline";
const hostContext: McpUiHostContext = {
  theme: options.theme,
  styles: { variables: options.theme === "dark" ? DARK_VARIABLES : NO_VARIABLES },
  displayMode,
  availableDisplayModes: options.modes,
  containerDimensions: { width: options.width, maxHeight: MAX_HEIGHT },
  locale: "en-US",
  platform: "web",
  toolInfo: { tool: { name: OPENING_TOOL, inputSchema: { type: "object" } } },
} as McpUiHostContext;

const bridge = new AppBridge(
  null,
  { name: "mock-host", version: "0.0.0" },
  { serverTools: {}, logging: {}, message: { text: {} }, updateModelContext: { text: {} } },
  { hostContext },
);

bridge.oncalltool = (params) => tools.callTool(params);
bridge.onmessage = async () => ({});
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
    void bridge.sendHostContextChange({ theme: name, styles: { variables: name === "dark" ? DARK_VARIABLES : NO_VARIABLES } });
  },
  messages: (method) => log.messages(method),
};

box.append(frame);
// Listen before the app loads, so its ui/initialize is never missed; the iframe's WindowProxy
// stays the same across the navigation.
await bridge.connect(new LoggingTransport(new PostMessageTransport(frame.contentWindow!, frame.contentWindow!), log));
frame.src = `/app.html?csp=${encodeURIComponent(options.csp)}`;
