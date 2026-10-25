import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { WorkflowsPage } from "./WorkflowsPage";
import { RouterProvider } from "../../router/Router";
import { AuthProvider } from "../../auth/AuthProvider";

describe("WorkflowsPage Suite (P2-F05, P2-F06)", () => {
  const originalFetch = global.fetch;

  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("P2-F05: WorkflowsPage renders empty, error, and populated states correctly", async () => {
    const orgId = "00000000-0000-0000-0000-000000000010";

    // 1. Populated state
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes(`/v1/organizations/${orgId}/workflows`)) {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({
            items: [
              {
                id: "wf-1",
                org_id: orgId,
                display_name: "Customer Onboarding",
                description: "Initial pipeline",
                current_version_id: null,
                created_by: "u-1",
                created_at: "2026-10-25T10:00:00Z",
                updated_at: "2026-10-25T10:00:00Z",
                archived_at: null,
              },
            ],
            next_cursor: null,
            has_more: false,
          }),
        } as unknown as Response);
      }
      if (url.includes(`/v1/organizations/${orgId}`)) {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({
            id: orgId,
            name: "Acme Corp",
            slug: "acme-corp",
            plan: "team",
            budget_limit_micro_usd: 5000000,
            max_concurrent_runs: 5,
            created_at: "2026-10-25T00:00:00Z",
            my_role: "owner",
          }),
        } as unknown as Response);
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({ items: [] }),
      } as unknown as Response);
    });

    const { unmount } = render(
      <RouterProvider initialPath={`/orgs/${orgId}/workflows`}>
        <AuthProvider>
          <WorkflowsPage orgId={orgId} />
        </AuthProvider>
      </RouterProvider>
    );

    await waitFor(() => {
      expect(screen.getByText("Customer Onboarding")).toBeInTheDocument();
      expect(screen.getByText("Active")).toBeInTheDocument();
      expect(screen.getAllByTestId("workflow-row")).toHaveLength(1);
    });

    unmount();

    // 2. Empty state
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes(`/v1/organizations/${orgId}/workflows`)) {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({ items: [], next_cursor: null, has_more: false }),
        } as unknown as Response);
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({ id: orgId, name: "Acme Corp", slug: "acme-corp", plan: "free", my_role: "owner" }),
      } as unknown as Response);
    });

    render(
      <RouterProvider initialPath={`/orgs/${orgId}/workflows`}>
        <AuthProvider>
          <WorkflowsPage orgId={orgId} />
        </AuthProvider>
      </RouterProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId("workflows-empty")).toHaveTextContent("No workflows found");
    });
  });

  it("P2-F06: WorkflowsPage hides 'New workflow' button for users with viewer role; shows for owner", async () => {
    const orgId = "00000000-0000-0000-0000-000000000020";

    // 1. Viewer role -> button hidden
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes(`/v1/organizations/${orgId}/workflows`)) {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({ items: [], next_cursor: null, has_more: false }),
        } as unknown as Response);
      }
      if (url.includes(`/v1/organizations/${orgId}`)) {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({
            id: orgId,
            name: "Viewer Org",
            slug: "viewer-org",
            plan: "free",
            budget_limit_micro_usd: 5000000,
            max_concurrent_runs: 5,
            created_at: "2026-10-25T00:00:00Z",
            my_role: "viewer",
          }),
        } as unknown as Response);
      }
      return Promise.resolve({ ok: true, json: async () => ({ items: [] }) } as unknown as Response);
    });

    const { unmount } = render(
      <RouterProvider initialPath={`/orgs/${orgId}/workflows`}>
        <AuthProvider>
          <WorkflowsPage orgId={orgId} />
        </AuthProvider>
      </RouterProvider>
    );

    await waitFor(() => {
      expect(screen.getByText("Viewer Org")).toBeInTheDocument();
    });

    // Button must NOT be rendered for viewer
    expect(screen.queryByTestId("new-workflow-btn")).toBeNull();

    unmount();

    // 2. Admin/Owner role -> button displayed
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes(`/v1/organizations/${orgId}/workflows`)) {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({ items: [], next_cursor: null, has_more: false }),
        } as unknown as Response);
      }
      if (url.includes(`/v1/organizations/${orgId}`)) {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({
            id: orgId,
            name: "Admin Org",
            slug: "admin-org",
            plan: "team",
            budget_limit_micro_usd: 5000000,
            max_concurrent_runs: 5,
            created_at: "2026-10-25T00:00:00Z",
            my_role: "admin",
          }),
        } as unknown as Response);
      }
      return Promise.resolve({ ok: true, json: async () => ({ items: [] }) } as unknown as Response);
    });

    render(
      <RouterProvider initialPath={`/orgs/${orgId}/workflows`}>
        <AuthProvider>
          <WorkflowsPage orgId={orgId} />
        </AuthProvider>
      </RouterProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId("new-workflow-btn")).toBeInTheDocument();
    });
  });
});
