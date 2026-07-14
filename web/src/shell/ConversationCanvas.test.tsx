import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ConversationCanvas } from "./ConversationCanvas";
import { ConversationLayoutProvider } from "./conversationLayout";

vi.mock("@/hooks/useConversations", () => ({
  useConversations: () => ({
    data: {
      pages: [
        {
          data: [
            { id: "alpha", title: "First chat" },
            { id: "beta", title: "Second chat" },
            { id: "gamma", title: "Third chat" },
            { id: "delta", title: "Fourth chat" },
          ],
        },
      ],
    },
  }),
}));

function renderCanvas() {
  render(
    <MemoryRouter initialEntries={["/c/alpha"]}>
      <TooltipProvider>
        <Routes>
          <Route
            path="/c/:conversationId"
            element={
              <ConversationLayoutProvider>
                <ConversationCanvas />
              </ConversationLayoutProvider>
            }
          />
        </Routes>
      </TooltipProvider>
    </MemoryRouter>,
  );
}

function paneIds(): string[] {
  return [...document.querySelectorAll<HTMLElement>("[data-conversation-id]")].map(
    (pane) => pane.dataset.conversationId!,
  );
}

describe("ConversationCanvas", () => {
  beforeEach(() => {
    window.sessionStorage.setItem(
      "omnigent.conversation-layout",
      JSON.stringify(["beta", "gamma", "delta"]),
    );
  });

  afterEach(() => {
    cleanup();
    window.sessionStorage.clear();
  });

  it("renders four peer panes with a move handle for every chat", () => {
    renderCanvas();

    expect(screen.getByTestId("conversation-grid")).toHaveAttribute("data-count", "4");
    expect(screen.queryByText("Primary")).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /^Move / })).toHaveLength(4);
    expect(document.querySelectorAll("iframe")).toHaveLength(3);
    expect(paneIds()).toEqual(["alpha", "beta", "gamma", "delta"]);
  });

  it("restores the saved order even when the route-backed chat is not first", () => {
    window.sessionStorage.setItem(
      "omnigent.conversation-layout",
      JSON.stringify({
        conversationIds: ["beta", "alpha", "gamma", "delta"],
        routeConversationId: "alpha",
      }),
    );
    renderCanvas();

    expect(paneIds()).toEqual(["beta", "alpha", "gamma", "delta"]);
  });

  it("dims peer panes after a chat receives focus", () => {
    renderCanvas();

    fireEvent.pointerDown(document.querySelector('[data-conversation-id="gamma"]')!);
    expect(document.querySelector('[data-conversation-id="gamma"]')).toHaveAttribute(
      "data-focused",
      "true",
    );
    expect(document.querySelector('[data-conversation-id="alpha"]')).toHaveAttribute(
      "data-dimmed",
      "true",
    );
    expect(document.querySelector('[data-conversation-id="beta"]')).toHaveAttribute(
      "data-dimmed",
      "true",
    );
  });

  it("removes panes and returns to the unchanged single-chat surface", () => {
    renderCanvas();

    fireEvent.click(screen.getByRole("button", { name: "Remove Fourth chat from layout" }));
    expect(screen.getByTestId("conversation-grid")).toHaveAttribute("data-count", "3");

    fireEvent.click(screen.getByRole("button", { name: "Single view" }));
    expect(screen.queryByTestId("conversation-grid")).not.toBeInTheDocument();
    expect(document.querySelectorAll("iframe")).toHaveLength(0);
  });
});
