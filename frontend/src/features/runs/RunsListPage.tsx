import { useEffect, useState, useCallback } from "react";
import { Header } from "../../components/Header";
import { apiFetch } from "../../api/client";
import { ApiError } from "../../api/errors";
import type { components } from "../../api/schema";

type RunSummary = components["schemas"]["RunSummary"];
type RunsPage = components["schemas"]["RunsPageResponse"];

const FILTER_STATES = [
  "ALL",
  "QUEUED",
  "RUNNING",
  "WAITING_APPROVAL",
  "SUCCEEDED",
  "FAILED",
  "CANCELLED",
];

export function RunsListPage({ orgId }: { orgId: string }) {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [selectedState, setSelectedState] = useState<string>("ALL");
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchRuns = useCallback(
    async (cursor?: string) => {
      try {
        setIsLoading(true);
        setError(null);

        const params = new URLSearchParams();
        params.set("limit", "20");
        if (selectedState !== "ALL") {
          params.set("state", selectedState);
        }
        if (cursor) {
          params.set("cursor", cursor);
        }

        const data = await apiFetch<RunsPage>(
          `/v1/organizations/${orgId}/runs?${params.toString()}`
        );
        if (cursor) {
          setRuns((prev) => [...prev, ...data.items]);
        } else {
          setRuns(data.items);
        }
        setNextCursor(data.next_cursor || null);
      } catch (err: unknown) {
        if (err instanceof ApiError) {
          setError(err.detail || err.message);
        } else {
          setError("Failed to fetch execution runs");
        }
      } finally {
        setIsLoading(false);
      }
    },
    [orgId, selectedState]
  );

  useEffect(() => {
    fetchRuns();
  }, [fetchRuns]);

  const getStateBadgeStyle = (state: string) => {
    switch (state) {
      case "SUCCEEDED":
        return { background: "#dcfce7", color: "#166534" };
      case "RUNNING":
        return { background: "#dbeafe", color: "#1e40af" };
      case "QUEUED":
        return { background: "#fef3c7", color: "#92400e" };
      case "WAITING_APPROVAL":
        return { background: "#fef9c3", color: "#854d0e" };
      case "FAILED":
        return { background: "#fee2e2", color: "#991b1b" };
      case "CANCELLED":
        return { background: "#f1f5f9", color: "#475569" };
      default:
        return { background: "#e2e8f0", color: "#334155" };
    }
  };

  return (
    <div style={{ minHeight: "100vh", background: "#f8fafc" }}>
      <Header />
      <main style={{ maxWidth: "1000px", margin: "24px auto", padding: "0 16px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "20px" }}>
          <div>
            <h1 style={{ margin: "0 0 4px 0", fontSize: "22px", fontWeight: "700" }}>Workflow Runs</h1>
            <p style={{ margin: 0, fontSize: "14px", color: "#64748b" }}>
              Execution history and state progression across workflows.
            </p>
          </div>
          <a
            href={`/orgs/${orgId}/workflows`}
            data-testid="link-to-workflows"
            style={{ color: "#2563eb", textDecoration: "none", fontSize: "14px", fontWeight: "500" }}
          >
            View Workflows →
          </a>
        </div>

        {/* State Filter Buttons */}
        <div style={{ display: "flex", gap: "8px", marginBottom: "20px", flexWrap: "wrap" }}>
          {FILTER_STATES.map((st) => (
            <button
              key={st}
              data-testid={`filter-${st.toLowerCase()}`}
              onClick={() => setSelectedState(st)}
              style={{
                padding: "6px 12px",
                borderRadius: "6px",
                border: selectedState === st ? "2px solid #2563eb" : "1px solid #cbd5e1",
                background: selectedState === st ? "#eff6ff" : "#fff",
                fontWeight: selectedState === st ? "600" : "normal",
                fontSize: "13px",
                cursor: "pointer",
              }}
            >
              {st}
            </button>
          ))}
        </div>

        {isLoading && runs.length === 0 ? (
          <div data-testid="runs-loading" style={{ padding: "40px", textAlign: "center", color: "#64748b" }}>
            Loading runs...
          </div>
        ) : error ? (
          <div data-testid="runs-error" style={{ padding: "16px", background: "#fee2e2", color: "#991b1b", borderRadius: "8px" }}>
            {error}
          </div>
        ) : runs.length === 0 ? (
          <div
            data-testid="no-runs-message"
            style={{
              padding: "48px",
              textAlign: "center",
              background: "#fff",
              borderRadius: "8px",
              border: "1px solid #e2e8f0",
              color: "#64748b",
            }}
          >
            No workflow runs found.
          </div>
        ) : (
          <div
            style={{
              background: "#fff",
              borderRadius: "8px",
              border: "1px solid #e2e8f0",
              overflow: "hidden",
            }}
          >
            <table style={{ width: "100%", borderCollapse: "collapse", textAlign: "left", fontSize: "13px" }}>
              <thead>
                <tr style={{ background: "#f8fafc", borderBottom: "1px solid #e2e8f0", color: "#64748b" }}>
                  <th style={{ padding: "12px 16px" }}>Run ID</th>
                  <th style={{ padding: "12px 16px" }}>State</th>
                  <th style={{ padding: "12px 16px" }}>Version</th>
                  <th style={{ padding: "12px 16px" }}>Trigger</th>
                  <th style={{ padding: "12px 16px" }}>Started</th>
                  <th style={{ padding: "12px 16px" }}>Created</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => (
                  <tr
                    key={r.id}
                    data-testid={`run-row-${r.id}`}
                    style={{ borderBottom: "1px solid #f1f5f9" }}
                  >
                    <td style={{ padding: "12px 16px", fontFamily: "monospace" }}>
                      <a
                        href={`/orgs/${orgId}/runs/${r.id}`}
                        data-testid={`run-link-${r.id}`}
                        style={{ color: "#2563eb", textDecoration: "none", fontWeight: "600" }}
                      >
                        {r.id.slice(0, 8)}...
                      </a>
                    </td>
                    <td style={{ padding: "12px 16px" }}>
                      <span
                        data-testid={`run-state-${r.id}`}
                        style={{
                          padding: "2px 8px",
                          borderRadius: "12px",
                          fontSize: "12px",
                          fontWeight: "500",
                          ...getStateBadgeStyle(r.state),
                        }}
                      >
                        {r.state}
                      </span>
                    </td>
                    <td style={{ padding: "12px 16px" }}>v{r.workflow_version}</td>
                    <td style={{ padding: "12px 16px", textTransform: "capitalize" }}>{r.trigger_kind}</td>
                    <td style={{ padding: "12px 16px", color: "#64748b" }}>
                      {r.started_at ? new Date(r.started_at).toLocaleTimeString() : "—"}
                    </td>
                    <td style={{ padding: "12px 16px", color: "#64748b" }}>
                      {new Date(r.created_at).toLocaleDateString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {nextCursor && (
              <div style={{ padding: "16px", textAlign: "center", borderTop: "1px solid #e2e8f0" }}>
                <button
                  data-testid="btn-load-more"
                  onClick={() => fetchRuns(nextCursor)}
                  disabled={isLoading}
                  style={{
                    padding: "6px 16px",
                    background: "#fff",
                    border: "1px solid #cbd5e1",
                    borderRadius: "4px",
                    fontSize: "13px",
                    cursor: "pointer",
                  }}
                >
                  {isLoading ? "Loading..." : "Load More"}
                </button>
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  );
}
