import { expect, test } from "@playwright/test";
import { SIZES, ScoreViewerFrame, type Control, type Size } from "../../../test/e2e/view-frame.ts";

// U4 (docs/research/ui-and-sound-testing-plan.md): every stop at 1280 px and 360 px container
// width, and in the host's fullscreen. At each stop: axe finds nothing in the chrome (the SVG
// notation is excluded, R4), every Tab stop shows its focus ring, and nothing scrolls sideways.
// Each stop runs in the default host and in Claude dark: the recorded Claude Desktop variables
// (U3, test/theme/recordings), where axe also measures the real colour contrast.

/** Hosts the stops run in: the mock host's query for each. */
const HOSTS: { name: string; query: Record<string, string> }[] = [
  { name: "default host", query: {} },
  { name: "Claude dark", query: { host: "claude", theme: "dark" } },
];

interface Stop {
  name: string;
  query: Record<string, string>;
  /** Brings the view to the stop once it is open. */
  reach(view: ScoreViewerFrame): Promise<void>;
  /** The view's own Tab order at the stop, before any fullscreen control. */
  tabOrder: Control[];
}

const PAGE_CONTROLS: Control[] = ["Next page", "Zoom out", "Zoom in", "Download SVG"];

const STOPS: Stop[] = [
  {
    name: "first page",
    query: {},
    reach: async (view) => void (await expect(view.scorePage()).toBeVisible()),
    tabOrder: PAGE_CONTROLS,
  },
  {
    name: "a later page, zoomed in",
    query: {},
    reach: async (view) => {
      await expect(view.scorePage()).toBeVisible();
      await view.click("Next page");
      await expect(view.pageLabel()).toHaveText(/^Page 2 \//);
      await view.click("Zoom in");
      await expect(view.zoomLabel()).toHaveText("125%");
      await expect(view.scorePage()).toBeVisible();
    },
    tabOrder: ["Previous page", ...PAGE_CONTROLS],
  },
  {
    name: "download fallback",
    query: { downloads: "0" },
    reach: async (view) => {
      await expect(view.scorePage()).toBeVisible();
      await view.click("Download SVG");
      await expect(view.downloadFallback()).toBeVisible();
    },
    tabOrder: [...PAGE_CONTROLS, "Ask the assistant to open it"],
  },
  {
    name: "page from render_page_svg",
    query: { csp: "spec" },
    reach: async (view) => void (await expect(view.scorePage()).toHaveAttribute("data-server-page", "1")),
    tabOrder: PAGE_CONTROLS,
  },
  {
    name: "path-only notice",
    query: { scenario: "path-only" },
    reach: async (view) => void (await expect(view.notice()).toContainText("needs the score inline")),
    tabOrder: [],
  },
  {
    name: "no notation engine notice",
    query: { csp: "spec", server: "0" },
    reach: async (view) => void (await expect(view.notice()).toContainText("could not start the notation engine")),
    tabOrder: [],
  },
];

function expectedTabOrder(stop: Stop, size: Size): Control[] {
  // Fullscreen is offered only in the fullscreen run; there its button reads "Exit fullscreen".
  if (size.width !== undefined) return stop.tabOrder;
  const beforeAsk = stop.tabOrder.filter((control) => control !== "Ask the assistant to open it");
  const ask = stop.tabOrder.filter((control) => control === "Ask the assistant to open it");
  return [...beforeAsk, "Exit fullscreen", ...ask];
}

for (const host of HOSTS) {
  for (const size of SIZES) {
    for (const stop of STOPS) {
      test(`U4 ${host.name}, ${size.name}: ${stop.name}: axe clean, focus visible on Tab, no sideways scroll`, async ({ page }) => {
        const view = await ScoreViewerFrame.open(page, { ...stop.query, ...host.query }, size);
        await stop.reach(view);

        if (size.width !== undefined) expect(await view.width()).toBeLessThanOrEqual(size.width);
        expect(await view.scrollsSideways()).toBe(false);
        expect(await view.axeViolations()).toEqual([]);

        const tabStops = await view.tabThrough();
        expect(tabStops.map((tabStop) => tabStop.name)).toEqual(expectedTabOrder(stop, size));
        for (const tabStop of tabStops) expect(tabStop, `focus ring on ${tabStop.name}`).toMatchObject({ ringVisible: true });
      });
    }
  }
}
