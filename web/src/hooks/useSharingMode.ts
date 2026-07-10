import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { SharingMode } from "@/lib/capabilities";
import { authenticatedFetch } from "@/lib/identity";

/** Server-wide sharing policy state from ``GET /v1/sharing-mode`` (admin). */
export interface SharingModeState {
  object: "sharing_mode";
  sharing_mode: SharingMode;
  /** False when the deployment injects its own resolver (not file-backed). */
  editable: boolean;
  /** Available tiers, most-permissive first. */
  options: SharingMode[];
}

const QUERY_KEY = ["sharing-mode"];

async function fetchSharingMode(): Promise<SharingModeState> {
  const res = await authenticatedFetch("/v1/sharing-mode");
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body?.error?.message ?? `${res.status} ${res.statusText}`);
  }
  return (await res.json()) as SharingModeState;
}

/** Fetch the current server-wide sharing mode (admin only). */
export function useSharingMode() {
  return useQuery({ queryKey: QUERY_KEY, queryFn: fetchSharingMode, staleTime: 5_000 });
}

/** PUT /v1/sharing-mode — set the server-wide sharing mode (admin only). */
export function useSetSharingMode() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (mode: SharingMode) => {
      const res = await authenticatedFetch("/v1/sharing-mode", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sharing_mode: mode }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body?.error?.message ?? `${res.status} ${res.statusText}`);
      }
      return (await res.json()) as SharingModeState;
    },
    onSuccess: (data) => {
      // Reflect the new value immediately, then revalidate.
      queryClient.setQueryData(QUERY_KEY, data);
      void queryClient.invalidateQueries({ queryKey: QUERY_KEY });
    },
  });
}
