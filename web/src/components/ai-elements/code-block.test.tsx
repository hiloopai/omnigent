import { afterEach, describe, expect, it, vi } from "vitest";
import { writeCodeThemeDark, writeCodeThemeLight } from "@/lib/codeThemePreferences";

const createHighlighterMock = vi.fn(async ({ themes }: { themes: string[] }) => ({
  getLoadedLanguages: () => ["typescript"],
  codeToTokens: vi.fn(() => ({
    bg: "#111111",
    fg: "#eeeeee",
    tokens: [[{ color: "#fff", content: "x" }]],
  })),
  themes,
}));

vi.mock("shiki", () => ({
  createHighlighter: (options: { themes: string[] }) => createHighlighterMock(options),
}));

describe("highlightCode theme selection", () => {
  afterEach(() => {
    vi.resetModules();
    createHighlighterMock.mockClear();
    localStorage.clear();
  });

  it("loads the selected light and dark themes into the highlighter", async () => {
    writeCodeThemeLight("solarized-light");
    writeCodeThemeDark("nord");

    const { highlightCode } = await import("@/components/ai-elements/code-block");

    await new Promise<void>((resolve) => {
      highlightCode("const x = 1", "typescript", () => resolve());
    });

    expect(createHighlighterMock).toHaveBeenCalledWith(
      expect.objectContaining({
        themes: ["solarized-light", "nord"],
      }),
    );
  });
});
