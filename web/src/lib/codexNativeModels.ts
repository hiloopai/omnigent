import type { CodexModelOption } from "./types";

/**
 * Static Codex model list for the new-session picker, shown before a session
 * exists and its live ``model/list`` can be fetched. Mirrors the in-session
 * picker's dynamic options; once a session is live the snapshot's
 * ``codexModelOptions`` take over. No default is pre-selected — leaving it
 * unset lets Codex fall back to its own configured model.
 *
 * Keep in sync with the backend static catalog in
 * ``omnigent/model_catalog.py`` (``_CODEX_STATIC_MODELS``).
 */
export const CODEX_NATIVE_PRESESSION_MODELS: readonly { id: string; label: string }[] = [
  { id: "gpt-5.5", label: "GPT-5.5" },
  { id: "gpt-5.4", label: "GPT-5.4" },
  { id: "gpt-5.4-mini", label: "GPT-5.4 mini" },
];

/**
 * Find the Codex option matching a raw Codex model id.
 *
 * @param options - Codex model options from the session snapshot.
 * @param model - Candidate model id, e.g. ``"gpt-5.5"``.
 * @returns The matching option, or ``null`` when unknown.
 */
export function findCodexModelOption(
  options: readonly CodexModelOption[],
  model: string | null | undefined,
): CodexModelOption | null {
  const raw = model?.trim();
  if (!raw) return null;
  return options.find((option) => option.id === raw) ?? null;
}

/**
 * Whether a sticky model id is one Codex advertised for this session.
 *
 * @param options - Codex model options from the session snapshot.
 * @param model - Candidate model id.
 * @returns True only when the candidate matches a Codex-returned option.
 */
export function isCodexNativeModel(
  options: readonly CodexModelOption[],
  model: string | null | undefined,
): boolean {
  return findCodexModelOption(options, model) !== null;
}

/**
 * Effort levels for the currently selected Codex model.
 *
 * @param options - Codex model options from the session snapshot.
 * @param currentModel - Active override or bound model id.
 * @returns Model-specific effort values from Codex ``model/list``.
 */
export function codexEffortLevelsForModel(
  options: readonly CodexModelOption[],
  currentModel: string | null | undefined,
): readonly string[] {
  if (options.length === 0) return [];
  const selected =
    findCodexModelOption(options, currentModel) ??
    options.find((option) => option.isDefault === true) ??
    options[0] ??
    null;
  const efforts = selected?.supportedReasoningEfforts ?? [];
  return Array.from(
    new Set(
      efforts
        .map((option) => option.reasoningEffort)
        .filter((effort): effort is string => typeof effort === "string" && effort.length > 0),
    ),
  );
}
