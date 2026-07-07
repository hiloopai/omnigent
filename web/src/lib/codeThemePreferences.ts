// Persisted syntax-highlighting theme preferences for Shiki and Monaco.
//
// Independent from the app's light/dark UI mode: the user picks a light theme
// and a dark theme from the Shiki bundled set, and the active one follows the
// resolved palette. Subscribers are notified on change so open code viewers
// re-highlight and Monaco editors call setTheme without a reload.

import { useEffect, useState } from "react";
import type { BundledTheme } from "shiki";

const STORAGE_KEY_LIGHT = "omnigent:code-theme-light";
const STORAGE_KEY_DARK = "omnigent:code-theme-dark";

export const CODE_THEME_LIGHT_DEFAULT = "github-light" satisfies BundledTheme;
export const CODE_THEME_DARK_DEFAULT = "github-dark" satisfies BundledTheme;

/** Curated Shiki bundled theme ids exposed in Settings → Appearance. */
export const CODE_THEME_ALLOWLIST = [
  "github-light",
  "github-dark",
  "one-dark-pro",
  "dracula",
  "nord",
  "monokai",
  "solarized-light",
  "solarized-dark",
  "catppuccin-latte",
  "catppuccin-mocha",
] as const satisfies readonly BundledTheme[];

export type CodeThemeId = (typeof CODE_THEME_ALLOWLIST)[number];

const allowlistSet = new Set<string>(CODE_THEME_ALLOWLIST);

/** Editor / read-only viewer background per theme (Shiki `bg` defaults). */
export const CODE_THEME_BACKGROUNDS: Record<CodeThemeId, string> = {
  "github-light": "#ffffff",
  "github-dark": "#0d1117",
  "one-dark-pro": "#282c34",
  dracula: "#282a36",
  nord: "#2e3440",
  monokai: "#272822",
  "solarized-light": "#fdf6e3",
  "solarized-dark": "#002b36",
  "catppuccin-latte": "#eff1f5",
  "catppuccin-mocha": "#1e1e2e",
};

const CODE_THEME_LABELS: Record<CodeThemeId, string> = {
  "github-light": "GitHub Light",
  "github-dark": "GitHub Dark",
  "one-dark-pro": "One Dark Pro",
  dracula: "Dracula",
  nord: "Nord",
  monokai: "Monokai",
  "solarized-light": "Solarized Light",
  "solarized-dark": "Solarized Dark",
  "catppuccin-latte": "Catppuccin Latte",
  "catppuccin-mocha": "Catppuccin Mocha",
};

/** Human-readable label for a theme id in the Settings dropdown. */
export function codeThemeLabel(id: CodeThemeId): string {
  return CODE_THEME_LABELS[id];
}

function isAllowedTheme(value: unknown): value is CodeThemeId {
  return typeof value === "string" && allowlistSet.has(value);
}

function readStoredTheme(key: string, fallback: CodeThemeId): CodeThemeId {
  if (typeof window === "undefined") return fallback;
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return fallback;
    const parsed: unknown = JSON.parse(raw);
    return isAllowedTheme(parsed) ? parsed : fallback;
  } catch {
    return fallback;
  }
}

function writeStoredTheme(key: string, id: CodeThemeId): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(key, JSON.stringify(id));
  } catch {
    // localStorage quota or access errors shouldn't break the app.
  }
}

const listeners = new Set<() => void>();

function emit(): void {
  for (const listener of listeners) {
    listener();
  }
}

/** Subscribe to light/dark syntax theme changes. Returns an unsubscribe fn. */
export function subscribeCodeThemes(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Bump when either syntax theme changes — for React components. */
export function useCodeThemeRevision(): number {
  const [revision, setRevision] = useState(0);
  useEffect(() => subscribeCodeThemes(() => setRevision((r) => r + 1)), []);
  return revision;
}

export function readCodeThemeLight(): CodeThemeId {
  return readStoredTheme(STORAGE_KEY_LIGHT, CODE_THEME_LIGHT_DEFAULT);
}

export function readCodeThemeDark(): CodeThemeId {
  return readStoredTheme(STORAGE_KEY_DARK, CODE_THEME_DARK_DEFAULT);
}

export function writeCodeThemeLight(id: CodeThemeId): void {
  const normalized = isAllowedTheme(id) ? id : CODE_THEME_LIGHT_DEFAULT;
  writeStoredTheme(STORAGE_KEY_LIGHT, normalized);
  emit();
}

export function writeCodeThemeDark(id: CodeThemeId): void {
  const normalized = isAllowedTheme(id) ? id : CODE_THEME_DARK_DEFAULT;
  writeStoredTheme(STORAGE_KEY_DARK, normalized);
  emit();
}

/** Background color for the active syntax theme given a resolved UI palette. */
export function codeThemeBackgroundForMode(resolved: "light" | "dark"): string {
  const id = resolved === "dark" ? readCodeThemeDark() : readCodeThemeLight();
  return CODE_THEME_BACKGROUNDS[id];
}
