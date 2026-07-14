import { describe, expect, it } from "vitest";
import {
  addConversationPane,
  MAX_CONVERSATION_PANES,
  normalizeConversationIds,
  removeConversationPane,
  reorderConversationPanes,
  syncConversationRoute,
} from "./conversationLayout";

describe("conversation layout", () => {
  it("deduplicates panes and caps the layout at four peers", () => {
    expect(normalizeConversationIds(["a", "b", "b", "c", "d", "e"])).toEqual(["a", "b", "c", "d"]);
    expect(MAX_CONVERSATION_PANES).toBe(4);
  });

  it("adds and removes conversations without assigning a special pane", () => {
    expect(addConversationPane(["a", "b"], "c")).toEqual(["a", "b", "c"]);
    expect(addConversationPane(["a", "b", "c", "d"], "e")).toEqual(["a", "b", "c", "d"]);
    expect(addConversationPane(["a", "b"], "a")).toEqual(["a", "b"]);
    expect(removeConversationPane(["a", "b", "c"], "b")).toEqual(["a", "c"]);
  });

  it("moves any conversation to another pane position", () => {
    expect(reorderConversationPanes(["a", "b", "c", "d"], "d", "b")).toEqual(["a", "d", "b", "c"]);
    expect(reorderConversationPanes(["a", "b", "c"], "a", "c")).toEqual(["b", "c", "a"]);
  });

  it("keeps pane order stable when the route-backed renderer changes", () => {
    expect(syncConversationRoute(["a", "b", "c"], "a", "d")).toEqual(["d", "b", "c"]);
    expect(syncConversationRoute(["a", "b", "c"], "a", "b")).toEqual(["a", "b", "c"]);
  });
});
