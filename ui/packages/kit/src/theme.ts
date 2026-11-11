// Maps the MCP Apps host theme and style variables onto CSS custom properties.
// Hosts may send any subset of the spec's variables, so every key the kit's CSS reads has a
// light and a dark fallback.

export type ThemeName = "light" | "dark";

export interface ThemeInput {
  theme?: ThemeName;
  styles?: { variables?: Record<string, string | undefined> };
}

export interface StyleTarget {
  style: { setProperty(name: string, value: string): void };
  dataset: Record<string, string | undefined>;
}

// Kept equal to docs/design/tokens.css (Kannel); ui/test/theme/brand-tokens.test.ts enforces it.
export const FALLBACK_VARIABLES: Record<ThemeName, Readonly<Record<string, string>>> = {
  light: {
    "--color-background-primary": "#ffffff",
    "--color-background-secondary": "#f4f6fa",
    "--color-text-primary": "#15171c",
    "--color-text-secondary": "#4b5563",
    "--color-border-primary": "#d5dce6",
    "--color-ring-primary": "#0072ce",
    "--font-sans": "system-ui, -apple-system, \"Segoe UI\", Roboto, \"Helvetica Neue\", Arial, sans-serif",
    "--border-radius-md": "6px",
  },
  dark: {
    "--color-background-primary": "#101217",
    "--color-background-secondary": "#1a1e27",
    "--color-text-primary": "#eef2f7",
    "--color-text-secondary": "#b4bdcb",
    "--color-border-primary": "#2e3645",
    "--color-ring-primary": "#6cb4f0",
    "--font-sans": "system-ui, -apple-system, \"Segoe UI\", Roboto, \"Helvetica Neue\", Arial, sans-serif",
    "--border-radius-md": "6px",
  },
};

const CUSTOM_PROPERTY = /^--[A-Za-z0-9-]+$/;

export function themeName(input: ThemeInput): ThemeName {
  return input.theme === "dark" ? "dark" : "light";
}

export function themeVariables(input: ThemeInput): Record<string, string> {
  const vars: Record<string, string> = { ...FALLBACK_VARIABLES[themeName(input)] };
  for (const [key, value] of Object.entries(input.styles?.variables ?? {})) {
    if (CUSTOM_PROPERTY.test(key) && typeof value === "string" && value.trim() !== "") {
      vars[key] = value;
    }
  }
  return vars;
}

export function applyTheme(target: StyleTarget, input: ThemeInput): void {
  const name = themeName(input);
  for (const [key, value] of Object.entries(themeVariables(input))) {
    target.style.setProperty(key, value);
  }
  target.style.setProperty("color-scheme", name);
  target.dataset.theme = name;
}
