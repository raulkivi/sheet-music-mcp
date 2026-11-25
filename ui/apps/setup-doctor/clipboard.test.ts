import { describe, expect, it, vi } from "vitest";
import { copyText } from "./clipboard.ts";

describe("copyText", () => {
  it("uses the async clipboard when the host allows it", async () => {
    const writeText = vi.fn(async () => {});
    const legacy = vi.fn(() => true);
    await expect(copyText("hi", { writeText, legacyCopy: legacy })).resolves.toBe("copied");
    expect(writeText).toHaveBeenCalledWith("hi");
    expect(legacy).not.toHaveBeenCalled();
  });

  it("falls back to the legacy copy when the async clipboard is refused", async () => {
    const writeText = vi.fn(async () => {
      throw new Error("NotAllowedError");
    });
    const legacy = vi.fn(() => true);
    await expect(copyText("hi", { writeText, legacyCopy: legacy })).resolves.toBe("copied");
    expect(legacy).toHaveBeenCalledWith("hi");
  });

  it("falls back when there is no async clipboard", async () => {
    const legacy = vi.fn(() => true);
    await expect(copyText("hi", { legacyCopy: legacy })).resolves.toBe("copied");
  });

  it("reports manual when nothing could copy, so the page can offer the text to select", async () => {
    const writeText = vi.fn(async () => {
      throw new Error("no");
    });
    await expect(copyText("hi", { writeText, legacyCopy: () => false })).resolves.toBe("manual");
    await expect(copyText("hi", { legacyCopy: () => { throw new Error("no"); } })).resolves.toBe("manual");
    await expect(copyText("hi", {})).resolves.toBe("manual");
  });
});
