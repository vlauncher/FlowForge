import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { HealthPage } from "./HealthPage";

function renderWithClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

describe("HealthPage (P1-F02, P1-F03)", () => {
  const originalFetch = global.fetch;

  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("P1-F02: shows loading then ok on healthy backend", async () => {
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.endsWith("/health")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({ status: "ok" }),
        } as unknown as Response);
      }
      if (url.endsWith("/ready")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({ status: "ready", checks: { database: "ok" } }),
        } as unknown as Response);
      }
      return Promise.reject(new Error("Unknown URL"));
    });

    renderWithClient(<HealthPage />);

    expect(screen.getByRole("status")).toHaveTextContent("Checking API…");

    await waitFor(() => {
      expect(screen.getByText("✓ API healthy")).toBeInTheDocument();
    });

    expect(screen.getByText("database")).toBeInTheDocument();
    expect(screen.getByText("✓ ok")).toBeInTheDocument();
  });

  it("P1-F03: shows error with code and request id on 503 service unavailable", async () => {
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.endsWith("/health")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({ status: "ok" }),
        } as unknown as Response);
      }
      if (url.endsWith("/ready")) {
        return Promise.resolve({
          ok: false,
          status: 503,
          headers: new Headers({
            "content-type": "application/problem+json",
            "x-request-id": "req-999-503",
          }),
          json: async () => ({
            code: "SERVICE_UNAVAILABLE",
            detail: "One or more readiness checks failed",
            request_id: "req-999-503",
            checks: { database: "fail" },
          }),
        } as unknown as Response);
      }
      return Promise.reject(new Error("Unknown URL"));
    });

    renderWithClient(<HealthPage />);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });

    expect(screen.getByText("SERVICE_UNAVAILABLE")).toBeInTheDocument();
    expect(screen.getByText("req-999-503")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});
