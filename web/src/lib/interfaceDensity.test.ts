import { afterEach, describe, expect, it, vi } from "vitest";
import {
  applyInterfaceDensity,
  DEFAULT_INTERFACE_DENSITY,
  normalizeInterfaceDensity,
  readInterfaceDensity,
  writeInterfaceDensity,
} from "./interfaceDensity";

const STORAGE_KEY = "omnigent:interface-density";

afterEach(() => {
  localStorage.clear();
  document.documentElement.removeAttribute("data-density");
  vi.restoreAllMocks();
});

describe("interface density persistence", () => {
  it("defaults to Comfortable without writing storage", () => {
    expect(readInterfaceDensity()).toBe(DEFAULT_INTERFACE_DENSITY);
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it("round-trips Compact and Spacious and clears storage for Comfortable", () => {
    writeInterfaceDensity("compact");
    expect(readInterfaceDensity()).toBe("compact");
    expect(localStorage.getItem(STORAGE_KEY)).toBe("compact");

    writeInterfaceDensity("spacious");
    expect(readInterfaceDensity()).toBe("spacious");
    expect(localStorage.getItem(STORAGE_KEY)).toBe("spacious");

    writeInterfaceDensity("comfortable");
    expect(readInterfaceDensity()).toBe("comfortable");
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it("normalizes unknown or corrupt values to Comfortable", () => {
    localStorage.setItem(STORAGE_KEY, "dense");
    expect(readInterfaceDensity()).toBe("comfortable");
    expect(normalizeInterfaceDensity(null)).toBe("comfortable");
  });
});

describe("interface density root attribute", () => {
  it("applies every supported value to the document root", () => {
    for (const density of ["compact", "comfortable", "spacious"] as const) {
      applyInterfaceDensity(density);
      expect(document.documentElement).toHaveAttribute("data-density", density);
    }
  });

  it("also applies to the scoped root used by the embedded app", () => {
    const embedRoot = document.createElement("div");
    embedRoot.className = "omnigent-app";
    document.body.append(embedRoot);

    applyInterfaceDensity("spacious");
    expect(embedRoot).toHaveAttribute("data-density", "spacious");

    embedRoot.remove();
  });

  it("still applies live when persistence is unavailable", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });

    expect(() => writeInterfaceDensity("compact")).not.toThrow();
    expect(document.documentElement).toHaveAttribute("data-density", "compact");
  });
});
