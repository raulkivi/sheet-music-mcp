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

export const FALLBACK_VARIABLES: Record<ThemeName, Readonly<Record<string, string>>> = {
  light: {
    "--color-background-primary": "#ffffff",
    "--color-background-secondary": "#f4f4f5",
    "--color-text-primary": "#1c1c1e",
    "--color-text-secondary": "#5c5c66",
    "--color-border-primary": "#d4d4d8",
    "--color-ring-primary": "#2563eb",
    "--font-sans": "system-ui, -apple-system, 'Segoe UI', sans-serif",
    "--border-radius-md": "6px",
  },
  dark: {
    "--color-background-primary": "#1c1c1e",
    "--color-background-secondary": "#2a2a2e",
    "--color-text-primary": "#ececf1",
    "--color-text-secondary": "#a1a1aa",
    "--color-border-primary": "#3f3f46",
    "--color-ring-primary": "#60a5fa",
    "--font-sans": "system-ui, -apple-system, 'Segoe UI', sans-serif",
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
