import { expect, test } from "../../../test/e2e/host-fixture.ts";
import { messages, openHost } from "../../../test/e2e/host-helpers.ts";

// R1 / U1 (docs/research/ui-and-sound-testing-plan.md): the host calls the real render-mcp over
// stdio. Under the spec's default CSP the page cannot run Verovio, so every page it shows comes
// from the server's render_page_svg; nothing here is a placeholder.

test("renders a page through the real render-mcp over stdio (R1)", async ({ page, renderMcp }) => {
  const frame = await openHost(page, { scenario: "inline-satb", csp: "spec", server: "real" });

  await expect(frame.locator("#engine")).toHaveAttribute("data-engine", "server");
  await expect(frame.locator("#score svg").first()).toBeVisible();
  await expect(frame.locator("#page-label")).toHaveText(/^Page 1 \/ \d+$/);
  await expect(frame.locator("#notice")).toBeHidden();
  // Verovio's own markup, not the placeholder pages of the default host.
  await expect(frame.locator("#score svg[data-server-page]")).toHaveCount(0);
  await expect(frame.locator("#score svg .staff").first()).toBeAttached();

  // The tool result came from the real render_to_pdf, which wrote a PDF under the test's output root.
  await expect(frame.locator("#saved-path")).toHaveText(/\.pdf$/);
  expect(await frame.locator("#saved-path").textContent()).toContain(renderMcp.outputRoot);

  // The host played the model's render_to_pdf call, then relayed the view's own calls.
  expect(renderMcp.calls.map((call) => call.name)).toEqual(["render_to_pdf", "render_page_svg"]);
  const [viewCall] = await messages(page, "tools/call");
  expect(viewCall!.params).toMatchObject({ name: "render_page_svg", arguments: { page: 1, zoom: 1 } });
});
