import { expect, test } from "@playwright/test";
import { openHost } from "../../../test/e2e/host-helpers.ts";

// The mock host serves any registered app at /app.html?app=<name>; the Score Viewer is the default.
test.describe("mock host app selection", () => {
  test("/app.html defaults to the Score Viewer and ?app= names a registered app", async ({ request }) => {
    const plain = await request.get("/app.html");
    const named = await request.get("/app.html?app=score-viewer");
    expect(plain.status()).toBe(200);
    expect(await named.text()).toBe(await plain.text());
  });

  test("an unregistered app is a 404, not a path lookup", async ({ request }) => {
    for (const app of ["nope", "../package", "__proto__"]) {
      expect((await request.get(`/app.html?app=${encodeURIComponent(app)}`)).status(), app).toBe(404);
    }
  });

  test("the host page option app=score-viewer loads the page in the frame", async ({ page }) => {
    const frame = await openHost(page, { app: "score-viewer" });
    await expect(frame.locator("#page-label")).toBeVisible();
  });
});
