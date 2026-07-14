import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useNavigate, useParams } from "@/lib/routing";

export const MAX_CONVERSATION_PANES = 4;
export const CONVERSATION_PANE_WINDOW_PREFIX = "omnigent-conversation-pane:";

const STORAGE_KEY = "omnigent.conversation-layout";

interface StoredConversationLayout {
  conversationIds: string[];
  routeConversationId: string | null;
  legacy: boolean;
}

export interface ConversationLayoutValue {
  conversationIds: string[];
  addConversation: (conversationId: string) => void;
  removeConversation: (conversationId: string) => void;
  reorderConversation: (activeId: string, overId: string) => void;
  showSingleConversation: () => void;
  canAddConversation: (conversationId: string) => boolean;
}

const EMPTY_LAYOUT: ConversationLayoutValue = {
  conversationIds: [],
  addConversation: () => {},
  removeConversation: () => {},
  reorderConversation: () => {},
  showSingleConversation: () => {},
  canAddConversation: () => false,
};

const ConversationLayoutContext = createContext<ConversationLayoutValue>(EMPTY_LAYOUT);

export function normalizeConversationIds(ids: readonly string[]): string[] {
  const unique = new Set<string>();
  for (const id of ids) {
    if (!id) continue;
    unique.add(id);
    if (unique.size === MAX_CONVERSATION_PANES) break;
  }
  return [...unique];
}

export function addConversationPane(
  conversationIds: readonly string[],
  conversationId: string,
): string[] {
  const normalized = normalizeConversationIds(conversationIds);
  if (
    !conversationId ||
    normalized.includes(conversationId) ||
    normalized.length >= MAX_CONVERSATION_PANES
  ) {
    return normalized;
  }
  return [...normalized, conversationId];
}

export function removeConversationPane(
  conversationIds: readonly string[],
  conversationId: string,
): string[] {
  return normalizeConversationIds(conversationIds).filter((id) => id !== conversationId);
}

export function reorderConversationPanes(
  conversationIds: readonly string[],
  activeId: string,
  overId: string,
): string[] {
  const normalized = normalizeConversationIds(conversationIds);
  const from = normalized.indexOf(activeId);
  const to = normalized.indexOf(overId);
  if (from < 0 || to < 0 || from === to) return normalized;

  const reordered = [...normalized];
  const [moved] = reordered.splice(from, 1);
  reordered.splice(to, 0, moved);
  return reordered;
}

export function syncConversationRoute(
  conversationIds: readonly string[],
  previousRouteId: string | null,
  nextRouteId: string,
): string[] {
  const normalized = normalizeConversationIds(conversationIds);
  if (normalized.includes(nextRouteId)) return normalized;

  const previousIndex = previousRouteId ? normalized.indexOf(previousRouteId) : -1;
  if (previousIndex >= 0) {
    const synced = [...normalized];
    synced[previousIndex] = nextRouteId;
    return synced;
  }
  return normalizeConversationIds([nextRouteId, ...normalized]);
}

function readConversationLayout(): StoredConversationLayout {
  try {
    const stored = window.sessionStorage.getItem(STORAGE_KEY);
    if (!stored) return { conversationIds: [], routeConversationId: null, legacy: false };
    const parsed = JSON.parse(stored) as unknown;
    if (Array.isArray(parsed)) {
      return {
        conversationIds: normalizeConversationIds(
          parsed.filter((id): id is string => typeof id === "string"),
        ),
        routeConversationId: null,
        legacy: true,
      };
    }
    if (parsed && typeof parsed === "object" && "conversationIds" in parsed) {
      const ids = (parsed as { conversationIds?: unknown }).conversationIds;
      const routeId = (parsed as { routeConversationId?: unknown }).routeConversationId;
      return {
        conversationIds: Array.isArray(ids)
          ? normalizeConversationIds(ids.filter((id): id is string => typeof id === "string"))
          : [],
        routeConversationId: typeof routeId === "string" ? routeId : null,
        legacy: false,
      };
    }
  } catch {
    // Ignore malformed or unavailable session storage.
  }
  return { conversationIds: [], routeConversationId: null, legacy: false };
}

function writeConversationLayout(
  conversationIds: readonly string[],
  routeConversationId: string | null,
): void {
  try {
    if (conversationIds.length === 0) {
      window.sessionStorage.removeItem(STORAGE_KEY);
      return;
    }
    window.sessionStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ conversationIds, routeConversationId }),
    );
  } catch {
    // The layout remains available in memory when storage is unavailable.
  }
}

export function isConversationPaneWindow(): boolean {
  return typeof window !== "undefined" && window.name.startsWith(CONVERSATION_PANE_WINDOW_PREFIX);
}

export function ConversationLayoutProvider({ children }: { children: ReactNode }) {
  const { conversationId } = useParams<{ conversationId: string }>();
  const routeConversationId = conversationId ?? null;
  const navigate = useNavigate();
  const initialLayout = useRef<StoredConversationLayout | null>(null);
  if (initialLayout.current === null) initialLayout.current = readConversationLayout();

  const previousRouteId = useRef(initialLayout.current.routeConversationId ?? routeConversationId);
  const [orderedConversationIds, setOrderedConversationIds] = useState(() => {
    const stored = initialLayout.current!;
    if (!routeConversationId) return stored.conversationIds;
    if (stored.legacy) {
      return normalizeConversationIds([routeConversationId, ...stored.conversationIds]);
    }
    return syncConversationRoute(
      stored.conversationIds,
      stored.routeConversationId,
      routeConversationId,
    );
  });

  useEffect(() => {
    if (!routeConversationId) return;
    const priorRouteId = previousRouteId.current;
    previousRouteId.current = routeConversationId;
    setOrderedConversationIds((current) =>
      syncConversationRoute(current, priorRouteId, routeConversationId),
    );
  }, [routeConversationId]);

  useEffect(() => {
    writeConversationLayout(orderedConversationIds, routeConversationId ?? previousRouteId.current);
  }, [orderedConversationIds, routeConversationId]);

  const addConversation = useCallback(
    (id: string) => {
      if (!routeConversationId) {
        navigate(`/c/${encodeURIComponent(id)}`);
        return;
      }
      setOrderedConversationIds((current) => addConversationPane(current, id));
    },
    [routeConversationId, navigate],
  );

  const removeConversation = useCallback(
    (id: string) => {
      const index = orderedConversationIds.indexOf(id);
      const remainingIds = removeConversationPane(orderedConversationIds, id);
      setOrderedConversationIds(remainingIds);

      if (id === routeConversationId) {
        const nextId = remainingIds[Math.min(Math.max(index, 0), remainingIds.length - 1)];
        navigate(nextId ? `/c/${encodeURIComponent(nextId)}` : "/");
      }
    },
    [orderedConversationIds, routeConversationId, navigate],
  );

  const reorderConversation = useCallback((activeId: string, overId: string) => {
    setOrderedConversationIds((current) => reorderConversationPanes(current, activeId, overId));
  }, []);

  const showSingleConversation = useCallback(() => {
    setOrderedConversationIds(routeConversationId ? [routeConversationId] : []);
  }, [routeConversationId]);

  const conversationIds = useMemo(
    () => (routeConversationId ? orderedConversationIds : []),
    [orderedConversationIds, routeConversationId],
  );

  const value = useMemo<ConversationLayoutValue>(
    () => ({
      conversationIds,
      addConversation,
      removeConversation,
      reorderConversation,
      showSingleConversation,
      canAddConversation: (id: string) =>
        Boolean(id) &&
        !conversationIds.includes(id) &&
        conversationIds.length < MAX_CONVERSATION_PANES,
    }),
    [
      conversationIds,
      addConversation,
      removeConversation,
      reorderConversation,
      showSingleConversation,
    ],
  );

  return (
    <ConversationLayoutContext.Provider value={value}>
      {children}
    </ConversationLayoutContext.Provider>
  );
}

export function useConversationLayout(): ConversationLayoutValue {
  return useContext(ConversationLayoutContext);
}
