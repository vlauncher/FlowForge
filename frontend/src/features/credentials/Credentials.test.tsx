import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { CredentialsPage } from "./CredentialsPage";
import { RouterProvider } from "../../router/Router";
import { AuthProvider } from "../../auth/AuthProvider";

describe("Credentials Suite (P5-F03)", () => {
  const originalFetch = global.fetch;

  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("P5-F03: credential creation clears secret input and appends item", async () => {
    let postBody: { name?: string; provider?: string; secret?: string; allowed_hosts?: string[]; permission_scopes?: string[] } | null = null;

    global.fetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      // Auth me
      if (url.includes("/v1/auth/me")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          json: () =>
            Promise.resolve({
              user: { id: "user-1", email: "user@example.com", display_name: "Admin User" },
              memberships: [{ org_id: "org-1", role: "owner" }],
            }),
        });
      }

      // Organizations list for Header
      if (url.includes("/v1/organizations") && !url.includes("/credentials")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          json: () =>
            Promise.resolve({
              items: [{ id: "org-1", name: "Dev Org", slug: "dev-org", my_role: "owner" }],
            }),
        });
      }

      // GET credentials
      if (init?.method === undefined || init?.method === "GET") {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          json: () => Promise.resolve({ items: [] }),
        });
      }

      // POST credentials
      if (init?.method === "POST") {
        const parsed = JSON.parse(init.body as string);
        postBody = parsed;
        return Promise.resolve({
          ok: true,
          status: 201,
          headers: new Headers({ "content-type": "application/json" }),
          json: () =>
            Promise.resolve({
              id: "cred-999",
              org_id: "org-1",
              name: parsed.name,
              provider: parsed.provider,
              allowed_hosts: parsed.allowed_hosts,
              permission_scopes: parsed.permission_scopes,
              key_id: "k1",
              created_at: "2026-10-25T16:00:00Z",
              rotated_at: null,
            }),
        });
      }

      return Promise.reject(new Error(`Unhandled URL: ${url}`));
    });

    render(
      <AuthProvider>
        <RouterProvider>
          <CredentialsPage orgId="org-1" />
        </RouterProvider>
      </AuthProvider>
    );

    // Initial empty state
    await waitFor(() => {
      expect(screen.getByTestId("no-credentials-message")).toBeInTheDocument();
    });

    const nameInput = screen.getByTestId("credential-name-input") as HTMLInputElement;
    const providerInput = screen.getByTestId("credential-provider-input") as HTMLInputElement;
    const secretInput = screen.getByTestId("credential-secret-input") as HTMLInputElement;
    const hostsInput = screen.getByTestId("credential-hosts-input") as HTMLInputElement;
    const submitBtn = screen.getByTestId("credential-submit-btn");

    // Verify secret field is type="password"
    expect(secretInput.type).toBe("password");

    // Fill form
    fireEvent.change(nameInput, { target: { value: "stripe_prod" } });
    fireEvent.change(providerInput, { target: { value: "stripe" } });
    fireEvent.change(secretInput, { target: { value: "sk_live_supersecret_123" } });
    fireEvent.change(hostsInput, { target: { value: "api.stripe.com" } });

    // Submit
    fireEvent.click(submitBtn);

    // Verify secret is sent in POST payload
    await waitFor(() => {
      expect(postBody).not.toBeNull();
      expect(postBody?.name).toBe("stripe_prod");
      expect(postBody?.secret).toBe("sk_live_supersecret_123");
    });

    // Verify secret input is cleared after submit
    await waitFor(() => {
      expect(secretInput.value).toBe("");
    });

    // Verify newly appended credential is displayed in list without secret
    await waitFor(() => {
      expect(screen.getByTestId("credential-item-cred-999")).toBeInTheDocument();
      expect(screen.getByTestId("credential-name-cred-999")).toHaveTextContent("stripe_prod");
    });
    expect(screen.queryByText("sk_live_supersecret_123")).not.toBeInTheDocument();
  });

  it("P9-F02: rotates credential secret and updates rotated_at", async () => {
    let rotateBody: { secret?: string } | null = null;
    const initialCred = {
      id: "cred-1",
      org_id: "org-1",
      name: "prod_api_key",
      provider: "stripe",
      allowed_hosts: ["api.stripe.com"],
      permission_scopes: ["charges:write"],
      key_id: "k1",
      created_at: "2026-10-25T12:00:00Z",
      rotated_at: null,
    };

    global.fetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      if (url.includes("/v1/auth/me")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          json: () =>
            Promise.resolve({
              user: { id: "user-1", email: "user@example.com", display_name: "Admin User" },
              memberships: [{ org_id: "org-1", role: "owner" }],
            }),
        });
      }

      if (url.includes("/v1/organizations") && !url.includes("/credentials")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          json: () =>
            Promise.resolve({
              items: [{ id: "org-1", name: "Dev Org", slug: "dev-org", my_role: "owner" }],
            }),
        });
      }

      if (url.endsWith("/rotate") && init?.method === "POST") {
        rotateBody = JSON.parse(init.body as string);
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          json: () =>
            Promise.resolve({
              ...initialCred,
              rotated_at: "2026-10-25T22:30:00Z",
            }),
        });
      }

      if (init?.method === undefined || init?.method === "GET") {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          json: () => Promise.resolve({ items: [initialCred] }),
        });
      }

      return Promise.reject(new Error(`Unhandled URL: ${url}`));
    });

    render(
      <AuthProvider>
        <RouterProvider>
          <CredentialsPage orgId="org-1" />
        </RouterProvider>
      </AuthProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId("rotate-cred-cred-1")).toBeInTheDocument();
    });

    // Open rotate modal
    fireEvent.click(screen.getByTestId("rotate-cred-cred-1"));
    expect(screen.getByTestId("rotate-secret-modal")).toBeInTheDocument();

    // Fill new secret and submit
    const secretInput = screen.getByTestId("rotate-secret-input");
    fireEvent.change(secretInput, { target: { value: "new_super_secret_456" } });
    fireEvent.click(screen.getByTestId("submit-rotate-btn"));

    // Verify rotation payload and updated UI
    await waitFor(() => {
      expect(rotateBody?.secret).toBe("new_super_secret_456");
      expect(screen.getByTestId("cred-rotated-at-cred-1")).toHaveTextContent("Rotated:");
    });
  });
});
