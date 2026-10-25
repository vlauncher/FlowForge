import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { RouterProvider } from "../../router/Router";
import { AuthProvider } from "../../auth/AuthProvider";
import { ToastProvider, useToast } from "../../components/Toast";
import { NotificationBell } from "../../components/NotificationBell";
import { LandingPage } from "./LandingPage";

function ToastTriggerHarness() {
  const toast = useToast();
  return (
    <div>
      <button onClick={() => toast.success("Workflow published", "Immutable version v3 created")}>
        Fire Success
      </button>
      <button onClick={() => toast.warning("Approval required", "Step gate_1 paused")}>
        Fire Warning
      </button>
    </div>
  );
}

describe("LandingPage, Toast & Notification Center UI Suite", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      json: async () => ({}),
    } as unknown as Response);
  });

  it("renders the interactive landing page, hero DAG demo, and navigates on CTA click", () => {
    window.history.pushState({}, "", "/");
    render(
      <RouterProvider>
        <AuthProvider>
          <ToastProvider>
            <LandingPage />
          </ToastProvider>
        </AuthProvider>
      </RouterProvider>
    );

    expect(screen.getByText(/Durable AI workflow engine/i)).toBeInTheDocument();
    expect(screen.getByText(/Durable by construction/i)).toBeInTheDocument();
    expect(screen.getByText(/Tool-effects ledger/i)).toBeInTheDocument();

    const startButtons = screen.getAllByRole("button", { name: /Get started/i });
    fireEvent.click(startButtons[0]);
    expect(window.location.pathname).toBe("/signup");
  });

  it("displays toast alerts with title and description and dismisses on click", async () => {
    render(
      <ToastProvider>
        <ToastTriggerHarness />
      </ToastProvider>
    );

    fireEvent.click(screen.getByRole("button", { name: /Fire Success/i }));
    expect(screen.getByText("Workflow published")).toBeInTheDocument();
    expect(screen.getByText("Immutable version v3 created")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Fire Warning/i }));
    expect(screen.getByText("Approval required")).toBeInTheDocument();

    const dismissButtons = screen.getAllByRole("button", { name: /Dismiss notification/i });
    fireEvent.click(dismissButtons[0]);
    await waitFor(() => {
      expect(screen.queryByText("Workflow published")).not.toBeInTheDocument();
    });
    expect(screen.getByText("Approval required")).toBeInTheDocument();
  });

  it("opens the NotificationBell popover when clicked", () => {
    render(
      <RouterProvider>
        <NotificationBell />
      </RouterProvider>
    );

    const bellBtn = screen.getByRole("button", { name: /Notifications/i });
    fireEvent.click(bellBtn);
    expect(screen.getByRole("dialog", { name: /Notifications/i })).toBeInTheDocument();
    expect(screen.getByText(/You're all caught up/i)).toBeInTheDocument();
  });
});
