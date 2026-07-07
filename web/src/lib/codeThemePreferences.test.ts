import { afterEach, describe, expect, it, vi } from "vitest";
import {
  CODE_THEME_DARK_DEFAULT,
  CODE_THEME_LIGHT_DEFAULT,
  readCodeThemeDark,
  readCodeThemeLight,
  subscribeCodeThemes,
  writeCodeThemeDark,
  writeCodeThemeLight,
} from "./codeThemePreferences";

const STORAGE_KEY_LIGHT = "omnigent:code-theme-light";
const STORAGE_KEY_DARK = "omnigent:code-theme-dark";

afterEach(() => {
  localStorage.clear();
});

describe("codeThemePreferences", () => {
  it("returns defaults when nothing is stored", () => {
    expect(readCodeThemeLight()).toBe(CODE_THEME_LIGHT_DEFAULT);
    expect(readCodeThemeDark()).toBe(CODE_THEME_DARK_DEFAULT);
  });

  it("round-trips valid theme ids", () => {
    writeCodeThemeLight("nord");
    writeCodeThemeDark("dracula");
    expect(readCodeThemeLight()).toBe("nord");
    expect(readCodeThemeDark()).toBe("dracula");
    expect(localStorage.getItem(STORAGE_KEY_LIGHT)).toBe(JSON.stringify("nord"));
    expect(localStorage.getItem(STORAGE_KEY_DARK)).toBe(JSON.stringify("dracula"));
  });

  it("falls back to defaults for unknown or malformed values", () => {
    localStorage.setItem(STORAGE_KEY_LIGHT, JSON.stringify("not-a-theme"));
    localStorage.setItem(STORAGE_KEY_DARK, "}{bad json");
    expect(readCodeThemeLight()).toBe(CODE_THEME_LIGHT_DEFAULT);
    expect(readCodeThemeDark()).toBe(CODE_THEME_DARK_DEFAULT);
  });

  it("clamps invalid writes to the default for that slot", () => {
    writeCodeThemeLight("bogus" as "nord");
    writeCodeThemeDark("bogus" as "nord");
    expect(readCodeThemeLight()).toBe(CODE_THEME_LIGHT_DEFAULT);
    expect(readCodeThemeDark()).toBe(CODE_THEME_DARK_DEFAULT);
  });

  it("notifies subscribers when either theme changes", () => {
    const listener = vi.fn();
    const unsub = subscribeCodeThemes(listener);
    writeCodeThemeLight("monokai");
    expect(listener).toHaveBeenCalledTimes(1);
    writeCodeThemeDark("one-dark-pro");
    expect(listener).toHaveBeenCalledTimes(2);
    unsub();
    writeCodeThemeLight("solarized-light");
    expect(listener).toHaveBeenCalledTimes(2);
  });
});
