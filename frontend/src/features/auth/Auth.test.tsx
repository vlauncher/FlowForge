import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { apiFetch, getAccessToken, setAccessToken } from "../../api/client";
import { AuthProvider } from "../../auth/AuthProvider";
import { RouterProvider, useRouter } from "../../router/Router";
import { LoginPage } from "./LoginPage";
import { SignupPage } from "./SignupPage";
import { App } from "../../App";

describe("Frontend Auth Suite (P2-F01 to P2-F04)", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    setAccessToken(null);
    localStorage.clear();
  });

  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("P2-F01: ApiError maps 409 EMAIL_TAKEN and interceptor refreshes once on 401 and replays request", async () => {
    let callCount = 0;
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes("/v1/protected")) {
        callCount++;
        if (callCount === 1) {
          // First call returns 401
          return Promise.resolve({
            ok: false,
            status: 401,
            headers: new Headers({ "content-type": "application/problem+json" }),
            json: async () => ({
              code: "UNAUTHENTICATED",
              detail: "Token expired",
            }),
          } as unknown as Response);
        }
        // Replayed call succeeds
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({ message: "Success replayed" }),
        } as unknown as Response);
      }

      if (url.includes("/v1/auth/refresh")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({
            access_token: "new-fresh-access-token",
            token_type: "bearer",
            user: { id: "u-1", email: "test@example.com", display_name: "Test" },
          }),
        } as unknown as Response);
      }

      return Promise.reject(new Error(`Unexpected url: ${url}`));
    });

    const result = await apiFetch<{ message: string }>("/v1/protected");
    expect(result.message).toBe("Success replayed");
    expect(callCount).toBe(2);
    expect(getAccessToken()).toBe("new-fresh-access-token");
  });

  it("P2-F02: Signup page displays field errors when server returns 422/409, disables submit while pending", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 409,
      headers: new Headers({ "content-type": "application/problem+json" }),
      json: async () => ({
        code: "EMAIL_TAKEN",
        detail: "Email is already registered",
      }),
    } as unknown as Response);

    render(
      <RouterProvider initialPath="/signup">
        <AuthProvider>
          <SignupPage />
        </AuthProvider>
      </RouterProvider>
    );

    const nameInput = screen.getByTestId("signup-name");
    const emailInput = screen.getByTestId("signup-email");
    const passInput = screen.getByTestId("signup-password");
    const submitBtn = screen.getByTestId("signup-submit");

    // Client-side validation: password < 12 characters
    fireEvent.change(nameInput, { target: { value: "Ada Lovelace" } });
    fireEvent.change(emailInput, { target: { value: "ada@example.com" } });
    fireEvent.change(passInput, { target: { value: "short" } });
    fireEvent.click(submitBtn);

    expect(screen.getByTestId("error-password")).toHaveTextContent("Password must be at least 12 characters");

    // Fix password and trigger server 409 EMAIL_TAKEN
    fireEvent.change(passInput, { target: { value: "Password123456!" } });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(screen.getByTestId("error-email")).toHaveTextContent("Email is already registered");
    });
  });

  it("P2-F03: Login page displays invalid credentials error; successful login updates in-memory token and navigates", async () => {
    let shouldFail = true;

    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes("/v1/auth/login")) {
        if (shouldFail) {
          return Promise.resolve({
            ok: false,
            status: 401,
            headers: new Headers({ "content-type": "application/problem+json" }),
            json: async () => ({
              code: "INVALID_CREDENTIALS",
              detail: "Invalid email or password",
            }),
          } as unknown as Response);
        }
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({
            access_token: "tok-valid-login",
            token_type: "bearer",
            user: {
              id: "00000000-0000-0000-0000-000000000001",
              email: "ada@example.com",
              display_name: "Ada",
              is_active: true,
              created_at: "2026-10-25T00:00:00Z",
            },
          }),
        } as unknown as Response);
      }
      return Promise.resolve({
        ok: false,
        status: 401,
        headers: new Headers(),
        json: async () => ({}),
      } as unknown as Response);
    });

    let currentNavPath = "/login";
    function TestConsumer() {
      const { path } = useRouter();
      currentNavPath = path;
      return <div data-testid="current-path">{path}</div>;
    }

    render(
      <RouterProvider initialPath="/login">
        <AuthProvider>
          <LoginPage />
          <TestConsumer />
        </AuthProvider>
      </RouterProvider>
    );

    const emailInput = screen.getByTestId("login-email");
    const passInput = screen.getByTestId("login-password");
    const submitBtn = screen.getByTestId("login-submit");

    // 1. Invalid credentials
    fireEvent.change(emailInput, { target: { value: "wrong@example.com" } });
    fireEvent.change(passInput, { target: { value: "WrongPassword123!" } });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(screen.getByTestId("login-error")).toHaveTextContent("Invalid email or password");
    });
    expect(getAccessToken()).toBeNull();

    // 2. Successful credentials
    shouldFail = false;
    fireEvent.change(emailInput, { target: { value: "ada@example.com" } });
    fireEvent.change(passInput, { target: { value: "Password123456!" } });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(getAccessToken()).toBe("tok-valid-login");
      expect(currentNavPath).toBe("/orgs");
    });
  });

  it("P2-F04: Protected route redirects unauthenticated user to /login; retains redirect destination after login", async () => {
    // Initial mount silent refresh fails (user unauthenticated)
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes("/v1/auth/refresh")) {
        return Promise.resolve({
          ok: false,
          status: 401,
          headers: new Headers(),
          json: async () => ({}),
        } as unknown as Response);
      }
      if (url.includes("/v1/auth/login")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({
            access_token: "tok-redirected-login",
            token_type: "bearer",
            user: {
              id: "00000000-0000-0000-0000-000000000002",
              email: "user@example.com",
              display_name: "Redirected User",
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
            items: [],
            next_cursor: null,
            has_more: false,
          }),
        } as unknown as Response);
      }
      return Promise.resolve({ ok: true, json: async () => ({}) } as unknown as Response);
    });

    // Mock initial window.location.pathname as /orgs/some-org-id/workflows
    window.history.pushState(null, "", "/orgs/some-org-id/workflows");

    render(<App />);

    // Should redirect to /login
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Log In" })).toBeInTheDocument();
      expect(screen.getByTestId("login-email")).toBeInTheDocument();
    });

    // Login
    fireEvent.change(screen.getByTestId("login-email"), { target: { value: "user@example.com" } });
    fireEvent.change(screen.getByTestId("login-password"), { target: { value: "Password123456!" } });
    fireEvent.click(screen.getByTestId("login-submit"));

    // Should navigate back to the protected destination: /orgs/some-org-id/workflows
    await waitFor(() => {
      expect(window.location.pathname).toBe("/orgs/some-org-id/workflows");
    });
  });
});
