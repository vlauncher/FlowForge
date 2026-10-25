import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { UsageDashboardPage } from "./UsageDashboardPage";
import { RouterProvider } from "../../router/Router";
import { AuthProvider } from "../../auth/AuthProvider";

describe("Usage Dashboard Suite (P8-F01 & P8-F02)", () => {
  const originalFetch = global.fetch;

  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("P8-F01: renders usage totals, budget bar, and model table", async () => {
    global.fetch = vi.fn().mockImplementation((url: string) => {
      // Organizations list for Header
      if (url.includes("/v1/organizations") && !url.includes("/usage")) {
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

      // Usage API response
      if (url.includes("/v1/organizations/org-1/usage")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          json: () =>
            Promise.resolve({
              org_id: "org-1",
              from: "2026-09-25T00:00:00Z",
              to: "2026-10-25T23:59:59Z",
              budget_limit_micro_usd: 5000000,
              totals: {
                llm_calls: 42,
                prompt_tokens: 8400,
                completion_tokens: 1260,
                total_tokens: 9660,
                estimated_cost_micro_usd: 19320,
                billed_cost_micro_usd: 0,
              },
              by_model: [
                {
                  provider: "openrouter",
                  model_name: "openrouter/free",
                  calls: 42,
                  total_tokens: 9660,
                  estimated_cost_micro_usd: 19320,
                  billed_cost_micro_usd: 0,
                },
              ],
              runs_by_state: {
                QUEUED: 0,
                RUNNING: 1,
                WAITING_APPROVAL: 2,
                SUCCEEDED: 35,
                FAILED: 3,
                CANCELLED: 1,
              },
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
      <RouterProvider initialPath="/orgs/org-1/usage">
        <AuthProvider>
          <UsageDashboardPage orgId="org-1" />
        </AuthProvider>
      </RouterProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId("budget-card")).toBeInTheDocument();
    });

    // Check budget progress & text
    expect(screen.getByTestId("budget-spent-ratio")).toHaveTextContent("$0.0193 / $5.0000 (0%)");
    expect(screen.getByTestId("budget-progress-bar")).toBeInTheDocument();

    // Check usage totals
    expect(screen.getByTestId("total-llm-calls")).toHaveTextContent("42");
    expect(screen.getByTestId("total-tokens")).toHaveTextContent("9,660");
    expect(screen.getByTestId("total-estimated-cost")).toHaveTextContent("$0.0193");
    expect(screen.getByTestId("total-billed-cost")).toHaveTextContent("$0.0000");

    // Check run distribution
    expect(screen.getByTestId("state-count-succeeded")).toHaveTextContent("SUCCEEDED: 35");
    expect(screen.getByTestId("state-count-running")).toHaveTextContent("RUNNING: 1");

    // Check model table
    expect(screen.getByTestId("model-row-openrouter/free")).toBeInTheDocument();
    expect(screen.getByText("openrouter/free")).toBeInTheDocument();
  });

  it("P8-F02: handles empty usage state cleanly", async () => {
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes("/v1/organizations") && !url.includes("/usage")) {
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

      if (url.includes("/v1/organizations/org-1/usage")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          json: () =>
            Promise.resolve({
              org_id: "org-1",
              from: "2026-09-25T00:00:00Z",
              to: "2026-10-25T23:59:59Z",
              budget_limit_micro_usd: 5000000,
              totals: {
                llm_calls: 0,
                prompt_tokens: 0,
                completion_tokens: 0,
                total_tokens: 0,
                estimated_cost_micro_usd: 0,
                billed_cost_micro_usd: 0,
              },
              by_model: [],
              runs_by_state: {
                QUEUED: 0,
                RUNNING: 0,
                WAITING_APPROVAL: 0,
                SUCCEEDED: 0,
                FAILED: 0,
                CANCELLED: 0,
              },
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
      <RouterProvider initialPath="/orgs/org-1/usage">
        <AuthProvider>
          <UsageDashboardPage orgId="org-1" />
        </AuthProvider>
      </RouterProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId("budget-card")).toBeInTheDocument();
    });

    expect(screen.getByTestId("total-llm-calls")).toHaveTextContent("0");
    expect(screen.getByTestId("no-models-message")).toHaveTextContent(
      "No model usage recorded in this time window."
    );
  });
});
