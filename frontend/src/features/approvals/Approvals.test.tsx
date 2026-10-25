import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ApprovalsPage } from "./ApprovalsPage";
import { RouterProvider } from "../../router/Router";
import { AuthProvider } from "../../auth/AuthProvider";

describe("Approvals Suite (P7-F01 & P7-F02)", () => {
  const originalFetch = global.fetch;

  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("P7-F01: renders pending approvals and disables Approve/Reject for insufficient role", async () => {
    global.fetch = vi.fn().mockImplementation((url: string) => {
      // User is viewer
      if (url.includes("/v1/organizations") && !url.includes("/approvals")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          json: () =>
            Promise.resolve({
              items: [{ id: "org-1", name: "Dev Org", slug: "dev-org", my_role: "viewer" }],
            }),
        });
      }
      if (url.includes("/v1/organizations/org-1/approvals")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          json: () =>
            Promise.resolve({
              items: [
                {
                  id: "app-pending-1",
                  org_id: "org-1",
                  run_id: "run-1",
                  step_id: "gate_1",
                  version_id: "ver-1",
                  assigned_role: "reviewer",
                  state: "PENDING",
                  summary: "Approve user promotion",
                  expires_at: "2099-01-01T00:00:00Z",
                  created_at: "2026-10-25T14:00:00Z",
                },
              ],
            }),
        });
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/json" }),
        json: () => Promise.resolve({}),
      });
    });

    render(
      <RouterProvider initialPath="/orgs/org-1/approvals">
        <AuthProvider>
          <ApprovalsPage orgId="org-1" />
        </AuthProvider>
      </RouterProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId("approval-card-app-pending-1")).toBeInTheDocument();
    });

    expect(screen.getByTestId("approval-summary-app-pending-1")).toHaveTextContent("Approve user promotion");
    expect(screen.getByTestId("approval-status-app-pending-1")).toHaveTextContent("PENDING");

    // Viewer role rank is insufficient for 'reviewer' approval
    await waitFor(() => {
      expect(screen.getByTestId("approval-insufficient-role-app-pending-1")).toBeInTheDocument();
    });

    expect(screen.getByTestId("approval-approve-btn-app-pending-1")).toBeDisabled();
    expect(screen.getByTestId("approval-reject-btn-app-pending-1")).toBeDisabled();
  });

  it("P7-F02: submitting decision updates status and handles 409 conflict", async () => {
    let decisionCount = 0;

    global.fetch = vi.fn().mockImplementation((url: string) => {
      // User is reviewer
      if (url.includes("/v1/organizations") && !url.includes("/approvals")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          json: () =>
            Promise.resolve({
              items: [{ id: "org-1", name: "Dev Org", slug: "dev-org", my_role: "reviewer" }],
            }),
        });
      }

      if (url.includes("/v1/organizations/org-1/approvals")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          json: () =>
            Promise.resolve({
              items: [
                {
                  id: "app-pending-2",
                  org_id: "org-1",
                  run_id: "run-2",
                  step_id: "gate_2",
                  version_id: "ver-1",
                  assigned_role: "reviewer",
                  state: "PENDING",
                  summary: "Approve database export",
                  expires_at: "2099-01-01T00:00:00Z",
                  created_at: "2026-10-25T14:00:00Z",
                },
              ],
            }),
        });
      }

      // POST decision
      if (url.includes("/v1/approvals/app-pending-2/decisions")) {
        decisionCount += 1;
        if (decisionCount === 1) {
          // Conflict 409
          return Promise.resolve({
            ok: false,
            status: 409,
            headers: new Headers({ "content-type": "application/problem+json" }),
            json: () =>
              Promise.resolve({
                code: "INVALID_STATE_TRANSITION",
                detail: "Approval already decided or cancelled",
              }),
          });
        }

        // Success 200
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          json: () =>
            Promise.resolve({
              id: "app-pending-2",
              org_id: "org-1",
              run_id: "run-2",
              step_id: "gate_2",
              version_id: "ver-1",
              assigned_role: "reviewer",
              state: "APPROVED",
              summary: "Approve database export",
              decision_comment: "Approved after second check",
              expires_at: "2099-01-01T00:00:00Z",
              created_at: "2026-10-25T14:00:00Z",
            }),
        });
      }

      return Promise.resolve({
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/json" }),
        json: () => Promise.resolve({}),
      });
    });

    render(
      <RouterProvider initialPath="/orgs/org-1/approvals">
        <AuthProvider>
          <ApprovalsPage orgId="org-1" />
        </AuthProvider>
      </RouterProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId("approval-approve-btn-app-pending-2")).toBeEnabled();
    });

    // 1. Submit -> returns 409 conflict
    fireEvent.click(screen.getByTestId("approval-approve-btn-app-pending-2"));

    await waitFor(() => {
      expect(screen.getByTestId("approval-error-app-pending-2")).toHaveTextContent(
        "Approval already decided or cancelled"
      );
    });

    // 2. Retry -> returns 200 APPROVED
    fireEvent.click(screen.getByTestId("approval-approve-btn-app-pending-2"));

    await waitFor(() => {
      expect(screen.getByTestId("approval-status-app-pending-2")).toHaveTextContent("APPROVED");
    });
  });
});
