import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { WorkflowDetailPage } from "./WorkflowDetailPage";
import { VersionEditor } from "./VersionEditor";
import { RouterProvider } from "../../router/Router";
import { AuthProvider } from "../../auth/AuthProvider";

describe("Workflow Version Editor Suite (P3-F01 to P3-F04)", () => {
  const originalFetch = global.fetch;

  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  const mockVersion = {
    id: "00000000-0000-0000-0000-000000000101",
    workflow_id: "00000000-0000-0000-0000-000000000001",
    org_id: "00000000-0000-0000-0000-000000000010",
    version: 1,
    status: "draft",
    schema_version: 1,
    checksum: null,
    created_by: "u-1",
    created_at: "2026-10-25T12:00:00Z",
    published_at: null,
    definition_json: {
      schema_version: 1,
      name: "Ticket Triage",
      start: "step_classify",
      steps: [
        {
          id: "step_classify",
          type: "llm_classify",
          config: {
            prompt_template_id: "tmpl_1",
            input: "some input",
            labels: ["billing", "tech"],
          },
          next: "step_done",
        },
        {
          id: "step_done",
          type: "set_data",
          config: { values: { status: "finished" } },
          next: null,
        },
      ],
    },
  };

  it("P3-F01: renders step preview from valid JSON definition", () => {
    render(
      <RouterProvider initialPath="/orgs/org-1/workflows/wf-1">
        <AuthProvider>
          <VersionEditor workflowId="wf-1" version={mockVersion} userRole="admin" />
        </AuthProvider>
      </RouterProvider>
    );

    expect(screen.getByText("Step Preview (2 steps)")).toBeInTheDocument();
    const items = screen.getAllByTestId("step-preview-item");
    expect(items).toHaveLength(2);
    expect(screen.getAllByText("step_classify").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("step_done").length).toBeGreaterThanOrEqual(1);
  });

  it("P3-F02: shows validation issues from /validate endpoint in accessible alert list", async () => {
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes("/validate")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({
            valid: false,
            checksum: null,
            errors: [
              {
                code: "GRAPH_CYCLE",
                field: "steps",
                message: "Workflow contains a directed cycle",
                step_ids: ["step_a", "step_b"],
              },
            ],
          }),
        } as unknown as Response);
      }
      return Promise.resolve({ ok: true, json: async () => ({}) } as unknown as Response);
    });

    render(
      <RouterProvider initialPath="/orgs/org-1/workflows/wf-1">
        <AuthProvider>
          <VersionEditor workflowId="wf-1" version={mockVersion} userRole="admin" />
        </AuthProvider>
      </RouterProvider>
    );

    fireEvent.click(screen.getByTestId("btn-validate"));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
      expect(screen.getByText("[GRAPH_CYCLE]")).toBeInTheDocument();
      expect(screen.getByText("Workflow contains a directed cycle")).toBeInTheDocument();
    });
  });

  it("P3-F03: disables or hides 'Publish' button when user role is operator or viewer", () => {
    const { unmount } = render(
      <RouterProvider initialPath="/orgs/org-1/workflows/wf-1">
        <AuthProvider>
          <VersionEditor workflowId="wf-1" version={mockVersion} userRole="operator" />
        </AuthProvider>
      </RouterProvider>
    );

    // Operator cannot publish
    expect(screen.queryByTestId("btn-publish")).toBeNull();

    unmount();

    // Viewer cannot publish
    render(
      <RouterProvider initialPath="/orgs/org-1/workflows/wf-1">
        <AuthProvider>
          <VersionEditor workflowId="wf-1" version={mockVersion} userRole="viewer" />
        </AuthProvider>
      </RouterProvider>
    );
    expect(screen.queryByTestId("btn-publish")).toBeNull();
  });

  it("P3-F04: transitions draft to published badge on publish success", async () => {
    const orgId = "00000000-0000-0000-0000-000000000010";
    const wfId = "00000000-0000-0000-0000-000000000001";

    let published = false;

    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes(`/v1/organizations/${orgId}`)) {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({ id: orgId, name: "Acme", slug: "acme", plan: "free", my_role: "admin" }),
        } as unknown as Response);
      }
      if (url.includes(`/v1/workflows/${wfId}/versions/1`)) {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({
            ...mockVersion,
            status: published ? "published" : "draft",
            checksum: published ? "a1b2c3d4" : null,
          }),
        } as unknown as Response);
      }
      if (url.includes(`/v1/workflows/${wfId}/versions`)) {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({
            items: [
              {
                id: mockVersion.id,
                version: 1,
                status: published ? "published" : "draft",
                created_at: "2026-10-25T12:00:00Z",
              },
            ],
            next_cursor: null,
            has_more: false,
          }),
        } as unknown as Response);
      }
      if (url.includes(`/v1/workflows/${wfId}/publish`)) {
        published = true;
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({
            ...mockVersion,
            status: "published",
            checksum: "a1b2c3d4e5f6",
            published_at: "2026-10-25T12:30:00Z",
          }),
        } as unknown as Response);
      }
      if (url.includes(`/v1/workflows/${wfId}`)) {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({
            id: wfId,
            org_id: orgId,
            display_name: "Triage Flow",
            current_version_id: published ? mockVersion.id : null,
            created_at: "2026-10-25T10:00:00Z",
            updated_at: "2026-10-25T10:00:00Z",
          }),
        } as unknown as Response);
      }
      return Promise.resolve({ ok: true, json: async () => ({ items: [] }) } as unknown as Response);
    });

    render(
      <RouterProvider initialPath={`/orgs/${orgId}/workflows/${wfId}`}>
        <AuthProvider>
          <WorkflowDetailPage orgId={orgId} workflowId={wfId} />
        </AuthProvider>
      </RouterProvider>
    );

    // Initial state shows draft badge
    await waitFor(() => {
      expect(screen.getByTestId("version-status-badge")).toHaveTextContent("draft");
      expect(screen.getByTestId("btn-publish")).toBeInTheDocument();
    });

    // Click publish
    fireEvent.click(screen.getByTestId("btn-publish"));

    // Expect transition to published
    await waitFor(() => {
      expect(screen.getByTestId("version-status-badge")).toHaveTextContent("published");
    });
  });

  it("P9-F01: creates webhook trigger and displays webhook URL and curl snippet", async () => {
    const orgId = "00000000-0000-0000-0000-000000000010";
    const wfId = "00000000-0000-0000-0000-000000000001";
    let triggerBody: { credential_id?: string } | null = null;
    let triggersList: Array<{ id: string; workflow_id: string; credential_id: string; enabled: boolean; webhook_url: string; created_at: string }> = [];

    global.fetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      if (url.includes(`/v1/workflows/${wfId}/triggers`)) {
        if (init?.method === "POST") {
          triggerBody = JSON.parse(init.body as string);
          const newTrig = {
            id: "trig-123",
            workflow_id: wfId,
            credential_id: triggerBody?.credential_id || "cred-1",
            enabled: true,
            webhook_url: "/v1/triggers/webhooks/trig-123",
            created_at: "2026-10-25T22:00:00Z",
          };
          triggersList = [newTrig];
          return Promise.resolve({
            ok: true,
            status: 201,
            headers: new Headers({ "content-type": "application/json" }),
            json: async () => newTrig,
          } as unknown as Response);
        }
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => triggersList,
        } as unknown as Response);
      }

      if (url.includes(`/v1/organizations/${orgId}/credentials`)) {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({
            items: [
              {
                id: "cred-1",
                org_id: orgId,
                name: "Webhook Key",
                provider: "custom",
                allowed_hosts: [],
                permission_scopes: [],
                key_id: "k1",
                created_at: "2026-10-25T10:00:00Z",
              },
            ],
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
            name: "Test Org",
            slug: "test-org",
            my_role: "owner",
          }),
        } as unknown as Response);
      }

      if (url.includes(`/v1/workflows/${wfId}/versions`)) {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({ items: [mockVersion] }),
        } as unknown as Response);
      }

      if (url.includes(`/v1/workflows/${wfId}`)) {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({
            id: wfId,
            org_id: orgId,
            display_name: "Triage Flow",
            current_version_id: mockVersion.id,
            created_at: "2026-10-25T10:00:00Z",
            updated_at: "2026-10-25T10:00:00Z",
          }),
        } as unknown as Response);
      }

      return Promise.resolve({ ok: true, json: async () => ({ items: [] }) } as unknown as Response);
    });

    render(
      <RouterProvider initialPath={`/orgs/${orgId}/workflows/${wfId}`}>
        <AuthProvider>
          <WorkflowDetailPage orgId={orgId} workflowId={wfId} />
        </AuthProvider>
      </RouterProvider>
    );

    // Initial state: shows Webhook Trigger card with Create button
    await waitFor(() => {
      expect(screen.getByTestId("create-webhook-trigger-btn")).toBeInTheDocument();
    });

    // Click create webhook trigger
    fireEvent.click(screen.getByTestId("create-webhook-trigger-btn"));

    // Verify webhook URL and curl snippet display
    await waitFor(() => {
      expect(triggerBody?.credential_id).toBe("cred-1");
      expect(screen.getByTestId("webhook-url-display")).toHaveTextContent("/v1/triggers/webhooks/trig-123");
      expect(screen.getByTestId("webhook-curl-snippet")).toBeInTheDocument();
    });
  });
});
