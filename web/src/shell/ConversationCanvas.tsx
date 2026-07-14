import { type CSSProperties, useCallback, useEffect, useMemo, useState } from "react";
import {
  closestCenter,
  DndContext,
  DragOverlay,
  type DragEndEvent,
  type DragStartEvent,
  KeyboardSensor,
  PointerSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import { ExternalLinkIcon, GripVerticalIcon, Grid2X2Icon, Rows2Icon, XIcon } from "lucide-react";
import { useConversations } from "@/hooks/useConversations";
import { Outlet, useParams, useRebasePath } from "@/lib/routing";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { conversationDisplayLabel } from "./sidebarNav";
import { CONVERSATION_PANE_WINDOW_PREFIX, useConversationLayout } from "./conversationLayout";

function ConversationPaneFrame({
  conversationId,
  onActivate,
}: {
  conversationId: string;
  onActivate: () => void;
}) {
  const [loaded, setLoaded] = useState(false);
  const rebasePath = useRebasePath();
  const src = rebasePath(`/c/${encodeURIComponent(conversationId)}`);

  return (
    <div className="relative min-h-0 flex-1 bg-background">
      {!loaded && (
        <div className="absolute inset-0 flex items-center justify-center text-muted-foreground text-xs">
          Loading conversation…
        </div>
      )}
      {/* oxlint-disable-next-line react/iframe-missing-sandbox -- This trusted app pane needs same-origin storage and scripts. */}
      <iframe
        src={src}
        name={`${CONVERSATION_PANE_WINDOW_PREFIX}${conversationId}`}
        title={`Conversation ${conversationId}`}
        className={cn("h-full w-full border-0", !loaded && "invisible")}
        allow="clipboard-read; clipboard-write; microphone"
        onLoad={() => setLoaded(true)}
        onFocus={onActivate}
      />
    </div>
  );
}

interface ConversationPaneProps {
  conversationId: string;
  routeConversationId: string;
  title: string;
  fullTitle: string;
  rebasePath: (path: string) => string;
  removeConversation: (conversationId: string) => void;
  isFocused: boolean;
  isDimmed: boolean;
  onActivate: (conversationId: string) => void;
}

function ConversationPane({
  conversationId,
  routeConversationId,
  title,
  fullTitle,
  rebasePath,
  removeConversation,
  isFocused,
  isDimmed,
  onActivate,
}: ConversationPaneProps) {
  const {
    attributes,
    isDragging,
    listeners,
    setActivatorNodeRef,
    setNodeRef: setDraggableNodeRef,
  } = useDraggable({ id: conversationId });
  const { isOver, setNodeRef: setDroppableNodeRef } = useDroppable({ id: conversationId });
  const setNodeRef = useCallback(
    (node: HTMLElement | null) => {
      setDraggableNodeRef(node);
      setDroppableNodeRef(node);
    },
    [setDraggableNodeRef, setDroppableNodeRef],
  );

  return (
    <section
      ref={setNodeRef}
      className="conversation-grid-pane flex min-h-0 min-w-0 flex-col overflow-hidden rounded-lg border border-border bg-card shadow-sm"
      data-conversation-id={conversationId}
      data-dragging={isDragging ? "true" : undefined}
      data-drag-over={isOver && !isDragging ? "true" : undefined}
      data-focused={isFocused ? "true" : undefined}
      data-dimmed={isDimmed ? "true" : undefined}
      onPointerDownCapture={() => onActivate(conversationId)}
      onFocusCapture={() => onActivate(conversationId)}
    >
      <header className="flex h-9 shrink-0 items-center gap-1.5 border-b border-border bg-muted/40 px-2">
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              ref={setActivatorNodeRef}
              type="button"
              className="inline-flex size-6 shrink-0 touch-none cursor-grab items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground active:cursor-grabbing focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              {...attributes}
              {...listeners}
              aria-label={`Move ${title}`}
            >
              <GripVerticalIcon className="size-3.5" aria-hidden />
            </button>
          </TooltipTrigger>
          <TooltipContent>Drag to move</TooltipContent>
        </Tooltip>
        <span className="min-w-0 flex-1 truncate font-medium text-xs" title={fullTitle}>
          {title}
        </span>
        <Tooltip>
          <TooltipTrigger asChild>
            <a
              href={rebasePath(`/c/${encodeURIComponent(conversationId)}`)}
              target="_blank"
              rel="noreferrer"
              className="inline-flex size-6 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              aria-label={`Open ${title} in a new tab`}
            >
              <ExternalLinkIcon className="size-3.5" aria-hidden />
            </a>
          </TooltipTrigger>
          <TooltipContent>Open in new tab</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              className="size-6"
              aria-label={`Remove ${title} from layout`}
              onClick={() => removeConversation(conversationId)}
            >
              <XIcon className="size-3.5" aria-hidden />
            </Button>
          </TooltipTrigger>
          <TooltipContent>Remove from layout</TooltipContent>
        </Tooltip>
      </header>
      {conversationId === routeConversationId ? (
        <div className="flex min-h-0 flex-1 flex-col">
          <Outlet />
        </div>
      ) : (
        <ConversationPaneFrame
          conversationId={conversationId}
          onActivate={() => onActivate(conversationId)}
        />
      )}
    </section>
  );
}

export function ConversationCanvas() {
  const { conversationId: routeConversationId } = useParams<{ conversationId: string }>();
  const { conversationIds, removeConversation, reorderConversation, showSingleConversation } =
    useConversationLayout();
  const [draggingId, setDraggingId] = useState<string | null>(null);
  const [focusedConversationId, setFocusedConversationId] = useState<string | null>(null);
  const rebasePath = useRebasePath();
  const { data } = useConversations();
  const conversations = useMemo(
    () => data?.pages.flatMap((page) => page.data) ?? [],
    [data?.pages],
  );
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor),
  );

  const handleDragStart = useCallback((event: DragStartEvent) => {
    const id = String(event.active.id);
    setDraggingId(id);
    setFocusedConversationId(id);
  }, []);
  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      setDraggingId(null);
      if (event.over) reorderConversation(String(event.active.id), String(event.over.id));
    },
    [reorderConversation],
  );

  useEffect(() => {
    if (focusedConversationId && !conversationIds.includes(focusedConversationId)) {
      setFocusedConversationId(null);
    }
  }, [conversationIds, focusedConversationId]);

  if (!routeConversationId || conversationIds.length < 2) {
    return (
      <div id="conversation-canvas" className="relative flex min-h-0 flex-1 flex-col">
        <Outlet />
      </div>
    );
  }

  const draggingConversation = conversations.find((candidate) => candidate.id === draggingId);
  const draggingTitle = draggingConversation
    ? conversationDisplayLabel(draggingConversation)
    : "Conversation";

  return (
    <div
      id="conversation-canvas"
      className="conversation-canvas relative flex min-h-0 flex-1 flex-col"
      data-testid="conversation-canvas"
    >
      <div className="conversation-canvas-toolbar flex h-9 shrink-0 items-center justify-between px-3">
        <div className="flex min-w-0 items-center gap-2 text-muted-foreground text-xs">
          {conversationIds.length === 4 ? (
            <Grid2X2Icon className="size-3.5 shrink-0" aria-hidden />
          ) : (
            <Rows2Icon className="size-3.5 shrink-0" aria-hidden />
          )}
          <span className="truncate">{conversationIds.length} conversations</span>
        </div>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-7 px-2 text-xs"
          onClick={showSingleConversation}
        >
          Single view
        </Button>
      </div>

      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragStart={handleDragStart}
        onDragEnd={handleDragEnd}
        onDragCancel={() => setDraggingId(null)}
      >
        <div
          className="conversation-grid min-h-0 flex-1"
          data-count={conversationIds.length}
          data-reordering={draggingId ? "true" : undefined}
          data-has-focus={focusedConversationId ? "true" : undefined}
          data-testid="conversation-grid"
        >
          {conversationIds.map((id) => {
            const conversation = conversations.find((candidate) => candidate.id === id);
            const title = conversation ? conversationDisplayLabel(conversation) : "Conversation";
            return (
              <ConversationPane
                key={id}
                conversationId={id}
                routeConversationId={routeConversationId}
                title={title}
                fullTitle={conversation?.title ?? id}
                rebasePath={rebasePath}
                removeConversation={removeConversation}
                isFocused={id === focusedConversationId}
                isDimmed={focusedConversationId !== null && id !== focusedConversationId}
                onActivate={setFocusedConversationId}
              />
            );
          })}
        </div>
        <DragOverlay dropAnimation={null} style={{ pointerEvents: "none" } as CSSProperties}>
          {draggingId ? (
            <div className="conversation-pane-drag-overlay flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 shadow-lg">
              <GripVerticalIcon className="size-3.5 text-muted-foreground" aria-hidden />
              <span className="max-w-64 truncate font-medium text-xs">{draggingTitle}</span>
            </div>
          ) : null}
        </DragOverlay>
      </DndContext>
    </div>
  );
}
