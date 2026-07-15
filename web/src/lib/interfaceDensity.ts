const STORAGE_KEY = "omnigent:interface-density";

export const interfaceDensities = ["compact", "comfortable", "spacious"] as const;
export type InterfaceDensity = (typeof interfaceDensities)[number];

export const DEFAULT_INTERFACE_DENSITY: InterfaceDensity = "comfortable";

export function isInterfaceDensity(value: string | null | undefined): value is InterfaceDensity {
  return value === "compact" || value === "comfortable" || value === "spacious";
}

export function normalizeInterfaceDensity(value: string | null | undefined): InterfaceDensity {
  return isInterfaceDensity(value) ? value : DEFAULT_INTERFACE_DENSITY;
}

/** Read the device-local density preference without letting storage block app boot. */
export function readInterfaceDensity(): InterfaceDensity {
  if (typeof window === "undefined") return DEFAULT_INTERFACE_DENSITY;
  try {
    return normalizeInterfaceDensity(window.localStorage.getItem(STORAGE_KEY));
  } catch {
    return DEFAULT_INTERFACE_DENSITY;
  }
}

/** Apply density to the root so every chrome surface updates in the same frame. */
export function applyInterfaceDensity(value: InterfaceDensity): void {
  if (typeof document === "undefined") return;
  const normalized = normalizeInterfaceDensity(value);
  document.documentElement.dataset.density = normalized;
  // The embed build remaps :root selectors onto its scoped root.
  document.querySelectorAll<HTMLElement>(".omnigent-app").forEach((root) => {
    root.dataset.density = normalized;
  });
}

/** Persist non-default choices; Comfortable stays represented by an absent key. */
export function writeInterfaceDensity(value: InterfaceDensity): void {
  const normalized = normalizeInterfaceDensity(value);
  if (typeof window !== "undefined") {
    try {
      if (normalized === DEFAULT_INTERFACE_DENSITY) {
        window.localStorage.removeItem(STORAGE_KEY);
      } else {
        window.localStorage.setItem(STORAGE_KEY, normalized);
      }
    } catch {
      // A blocked localStorage must not prevent the live density change.
    }
  }
  applyInterfaceDensity(normalized);
}
