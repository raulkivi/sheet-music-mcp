// Copy text out of the sandboxed page. The host grants `clipboardWrite` through the resource's
// permissions (the ext-apps spec has no clipboard request, only the iframe permission), so the
// async clipboard can still be refused; the legacy copy and finally the user's own selection
// stand behind it.

export interface ClipboardEnv {
  writeText?: (text: string) => Promise<void>;
  /** Synchronous copy through a selected element; true when the browser copied. */
  legacyCopy?: (text: string) => boolean;
}

/** "copied", or "manual" when the user has to select and copy the text themselves. */
export async function copyText(text: string, env: ClipboardEnv): Promise<"copied" | "manual"> {
  if (env.writeText) {
    try {
      await env.writeText(text);
      return "copied";
    } catch {
      // Refused (no permission, no user activation): try the legacy route.
    }
  }
  try {
    if (env.legacyCopy?.(text)) return "copied";
  } catch {
    // Fall through to the manual route.
  }
  return "manual";
}

/** The browser's own clipboard, for the page. */
export function browserClipboard(doc: Document): ClipboardEnv {
  const clipboard = doc.defaultView?.navigator.clipboard;
  return {
    writeText: clipboard ? (text) => clipboard.writeText(text) : undefined,
    legacyCopy(text) {
      const area = doc.createElement("textarea");
      area.value = text;
      area.setAttribute("readonly", "");
      area.style.position = "fixed";
      area.style.opacity = "0";
      doc.body.append(area);
      area.select();
      try {
        return doc.execCommand("copy");
      } finally {
        area.remove();
      }
    },
  };
}
