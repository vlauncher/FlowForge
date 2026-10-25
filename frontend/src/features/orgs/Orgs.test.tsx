import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { Header } from "../../components/Header";
import { RouterProvider, useRouter } from "../../router/Router";
import { AuthProvider } from "../../auth/AuthProvider";

describe("Org Switcher Suite (P2-F07)", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("P2-F07: Org switcher dropdown navigates to selected org's workflows and updates localStorage", async () => {
    const orgA = {
      id: "00000000-0000-0000-0000-000000000001",
      name: "Acme Corp",
      slug: "acme-corp",
      plan: "free",
      my_role: "owner",
    };
    const orgB = {
      id: "00000000-0000-0000-0000-000000000002",
      name: "Beta Inc",
      slug: "beta-inc",
      plan: "team",
      my_role: "admin",
    };

    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes("/v1/auth/refresh")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({
            access_token: "test-token",
            token_type: "bearer",
            user: {
              id: "u-1",
              email: "test@example.com",
              display_name: "Test User",
              is_active: true,
              created_at: "2026-10-25T00:00:00Z",
            },
          }),
        } as unknown as Response);
      }
      if (url.includes("/v1/organizations")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({
            items: [orgA, orgB],
            next_cursor: null,
            has_more: false,
          }),
        } as unknown as Response);
      }
      return Promise.resolve({ ok: true, json: async () => ({}) } as unknown as Response);
    });

    let currentNavPath = `/orgs/${orgA.id}/workflows`;
    function NavigationInspector() {
      const { path } = useRouter();
      currentNavPath = path;
      return <div data-testid="nav-path">{path}</div>;
    }

    render(
      <RouterProvider initialPath={`/orgs/${orgA.id}/workflows`}>
        <AuthProvider>
          <Header currentOrgId={orgA.id} />
          <NavigationInspector />
        </AuthProvider>
      </RouterProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId("org-switcher")).toBeInTheDocument();
      expect(screen.getByText("Test User")).toBeInTheDocument();
    });

    const switcher = screen.getByTestId("org-switcher");
    expect(switcher).toHaveValue(orgA.id);

    // Switch to org B
    fireEvent.change(switcher, { target: { value: orgB.id } });

    await waitFor(() => {
      expect(localStorage.getItem("ff.lastOrg")).toBe(orgB.id);
      expect(currentNavPath).toBe(`/orgs/${orgB.id}/workflows`);
    });
  });
});
