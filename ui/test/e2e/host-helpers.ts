// Spec helpers for pages shown in the mock host (test/mock-host): open the host with query
// options, and read the message log the host keeps (window.__host).

import type { FrameLocator, Page } from "@playwright/test";

export interface LoggedMessage {
  direction: "host->app" | "app->host";
  t: number;
  method?: string;
  params?: Record<string, unknown>;
}

/** Opens the host with the given query (see test/mock-host/options.ts) and returns the app's frame. */
export async function openHost(page: Page, query: Record<string, string> = {}): Promise<FrameLocator> {
  await page.goto(`/?${new URLSearchParams(query)}`);
  return page.frameLocator("iframe");
}

/** Every message with this method, either direction, in order. */
export function messages(page: Page, method: string): Promise<LoggedMessage[]> {
  return page.evaluate(
    (m) => (window as unknown as { __host: { messages(m: string): LoggedMessage[] } }).__host.messages(m),
    method,
  );
}

/** The Score Viewer's "Page n / count" label as numbers. */
export async function pageLabel(frame: FrameLocator): Promise<{ page: number; count: number }> {
  const text = (await frame.locator("#page-label").textContent()) ?? "";
  const [, page, count] = text.match(/Page (\d+) \/ (\d+)/) ?? [];
  return { page: Number(page), count: Number(count) };
}
