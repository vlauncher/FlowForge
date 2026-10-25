import { useState, useEffect, useCallback } from "react";
import { Header } from "../../components/Header";
import { apiFetch } from "../../api/client";
import { ApiError } from "../../api/errors";
import type { components } from "../../api/schema";

type OrgUsage = components["schemas"]["OrgUsageResponse"];

interface UsageDashboardPageProps {
  orgId: string;
}

export function UsageDashboardPage({ orgId }: UsageDashboardPageProps) {
  const [usage, setUsage] = useState<OrgUsage | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchUsage = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);
      const data = await apiFetch<OrgUsage>(`/v1/organizations/${orgId}/usage`);
      setUsage(data);
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        if (err.status === 403) {
          setError("Access denied: you do not have permission to view organization usage.");
        } else {
          setError(err.detail || err.message);
        }
      } else {
        setError("Failed to load usage analytics");
      }
    } finally {
      setIsLoading(false);
    }
  }, [orgId]);

  useEffect(() => {
    fetchUsage();
  }, [fetchUsage]);

  const formatMicroUsd = (microUsd: number): string => {
    const usd = microUsd / 1_000_000;
    return `$${usd.toFixed(4)}`;
  };

  const calculateBudgetPercent = (spent: number, limit: number): number => {
    if (!limit || limit <= 0) return 0;
    return Math.min(100, Math.round((spent / limit) * 100));
  };

  return (
    <div style={{ minHeight: "100vh", background: "var(--surface-2)" }}>
      <Header currentOrgId={orgId} />
      <main style={{ maxWidth: "1000px", margin: "24px auto", padding: "0 16px" }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: "24px",
          }}
        >
          <div>
            <h1 style={{ margin: "0 0 4px 0", fontSize: "22px", fontWeight: "700" }}>
              Usage & Cost Analytics
            </h1>
            <p style={{ margin: 0, fontSize: "14px", color: "var(--text-muted)" }}>
              Token consumption, model breakdown, and organization budget tracking.
            </p>
          </div>
          <div style={{ display: "flex", gap: "12px" }}>
            <a
              href={`/orgs/${orgId}/runs`}
              data-testid="link-to-runs"
              style={{ color: "var(--link)", textDecoration: "none", fontSize: "14px", fontWeight: "500" }}
            >
              Runs →
            </a>
            <a
              href={`/orgs/${orgId}/workflows`}
              data-testid="link-to-workflows"
              style={{ color: "var(--link)", textDecoration: "none", fontSize: "14px", fontWeight: "500" }}
            >
              Workflows →
            </a>
          </div>
        </div>

        {isLoading ? (
          <div
            data-testid="usage-loading"
            style={{ padding: "40px", textAlign: "center", color: "var(--text-muted)" }}
          >
            Loading usage dashboard...
          </div>
        ) : error ? (
          <div
            data-testid="usage-error"
            style={{
              padding: "16px",
              background: "var(--danger-bg)",
              color: "var(--danger-fg)",
              borderRadius: "8px",
            }}
          >
            {error}
          </div>
        ) : usage ? (
          <div>
            {/* 1. Budget Consumption Bar */}
            <div
              data-testid="budget-card"
              style={{
                background: "var(--surface)",
                borderRadius: "8px",
                border: "1px solid var(--border)",
                padding: "20px",
                marginBottom: "20px",
              }}
            >
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  marginBottom: "8px",
                }}
              >
                <span style={{ fontSize: "14px", fontWeight: "600", color: "var(--text)" }}>
                  Monthly Budget Consumption
                </span>
                <span
                  data-testid="budget-spent-ratio"
                  style={{ fontSize: "14px", fontWeight: "600", color: "var(--link)" }}
                >
                  {formatMicroUsd(usage.totals.estimated_cost_micro_usd)} /{" "}
                  {formatMicroUsd(usage.budget_limit_micro_usd)} (
                  {calculateBudgetPercent(
                    usage.totals.estimated_cost_micro_usd,
                    usage.budget_limit_micro_usd
                  )}
                  %)
                </span>
              </div>
              <div
                style={{
                  width: "100%",
                  height: "10px",
                  background: "var(--border)",
                  borderRadius: "5px",
                  overflow: "hidden",
                }}
              >
                <div
                  data-testid="budget-progress-bar"
                  style={{
                    height: "100%",
                    width: `${calculateBudgetPercent(
                      usage.totals.estimated_cost_micro_usd,
                      usage.budget_limit_micro_usd
                    )}%`,
                    background:
                      calculateBudgetPercent(
                        usage.totals.estimated_cost_micro_usd,
                        usage.budget_limit_micro_usd
                      ) > 90
                        ? "var(--danger)"
                        : "var(--primary)",
                    borderRadius: "5px",
                    transition: "width 0.3s ease",
                  }}
                />
              </div>
            </div>

            {/* 2. Usage Totals Grid */}
            <div
              data-testid="usage-totals-grid"
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(4, 1fr)",
                gap: "16px",
                marginBottom: "24px",
              }}
            >
              <div
                style={{
                  background: "var(--surface)",
                  padding: "16px",
                  borderRadius: "8px",
                  border: "1px solid var(--border)",
                }}
              >
                <div style={{ fontSize: "12px", color: "var(--text-muted)", textTransform: "uppercase" }}>
                  Total LLM Calls
                </div>
                <div
                  data-testid="total-llm-calls"
                  style={{ fontSize: "22px", fontWeight: "700", marginTop: "4px" }}
                >
                  {usage.totals.llm_calls}
                </div>
              </div>

              <div
                style={{
                  background: "var(--surface)",
                  padding: "16px",
                  borderRadius: "8px",
                  border: "1px solid var(--border)",
                }}
              >
                <div style={{ fontSize: "12px", color: "var(--text-muted)", textTransform: "uppercase" }}>
                  Total Tokens
                </div>
                <div
                  data-testid="total-tokens"
                  style={{ fontSize: "22px", fontWeight: "700", marginTop: "4px" }}
                >
                  {usage.totals.total_tokens.toLocaleString()}
                </div>
                <div style={{ fontSize: "11px", color: "var(--text-dim)", marginTop: "2px" }}>
                  {usage.totals.prompt_tokens.toLocaleString()} prompt /{" "}
                  {usage.totals.completion_tokens.toLocaleString()} compl.
                </div>
              </div>

              <div
                style={{
                  background: "var(--surface)",
                  padding: "16px",
                  borderRadius: "8px",
                  border: "1px solid var(--border)",
                }}
              >
                <div style={{ fontSize: "12px", color: "var(--text-muted)", textTransform: "uppercase" }}>
                  Estimated Cost
                </div>
                <div
                  data-testid="total-estimated-cost"
                  style={{ fontSize: "22px", fontWeight: "700", marginTop: "4px", color: "var(--success-fg)" }}
                >
                  {formatMicroUsd(usage.totals.estimated_cost_micro_usd)}
                </div>
              </div>

              <div
                style={{
                  background: "var(--surface)",
                  padding: "16px",
                  borderRadius: "8px",
                  border: "1px solid var(--border)",
                }}
              >
                <div style={{ fontSize: "12px", color: "var(--text-muted)", textTransform: "uppercase" }}>
                  Billed Cost
                </div>
                <div
                  data-testid="total-billed-cost"
                  style={{ fontSize: "22px", fontWeight: "700", marginTop: "4px", color: "var(--text-soft)" }}
                >
                  {formatMicroUsd(usage.totals.billed_cost_micro_usd)}
                </div>
              </div>
            </div>

            {/* 3. Run State Distribution Summary */}
            <div
              data-testid="runs-state-card"
              style={{
                background: "var(--surface)",
                borderRadius: "8px",
                border: "1px solid var(--border)",
                padding: "20px",
                marginBottom: "24px",
              }}
            >
              <h3 style={{ margin: "0 0 12px 0", fontSize: "15px", fontWeight: "600" }}>
                Workflow Runs Distribution (Selected Window)
              </h3>
              <div style={{ display: "flex", gap: "16px", flexWrap: "wrap" }}>
                {Object.entries(usage.runs_by_state).map(([state, count]) => (
                  <div
                    key={state}
                    data-testid={`state-count-${state.toLowerCase()}`}
                    style={{
                      padding: "8px 14px",
                      background: "var(--surface-2)",
                      borderRadius: "6px",
                      border: "1px solid var(--border)",
                      fontSize: "13px",
                    }}
                  >
                    <span style={{ color: "var(--text-muted)" }}>{state}:</span>{" "}
                    <strong>{count}</strong>
                  </div>
                ))}
              </div>
            </div>

            {/* 4. Model Breakdown Table */}
            <div
              data-testid="model-breakdown-card"
              style={{
                background: "var(--surface)",
                borderRadius: "8px",
                border: "1px solid var(--border)",
                overflow: "hidden",
              }}
            >
              <div style={{ padding: "16px 20px", borderBottom: "1px solid var(--border)" }}>
                <h3 style={{ margin: 0, fontSize: "15px", fontWeight: "600" }}>
                  Model Breakdown
                </h3>
              </div>

              {usage.by_model.length === 0 ? (
                <div
                  data-testid="no-models-message"
                  style={{ padding: "32px", textAlign: "center", color: "var(--text-muted)", fontSize: "14px" }}
                >
                  No model usage recorded in this time window.
                </div>
              ) : (
                <table
                  data-testid="model-table"
                  style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px", textAlign: "left" }}
                >
                  <thead>
                    <tr style={{ background: "var(--surface-2)", borderBottom: "1px solid var(--border)" }}>
                      <th style={{ padding: "12px 20px" }}>Provider</th>
                      <th style={{ padding: "12px 20px" }}>Model</th>
                      <th style={{ padding: "12px 20px" }}>Calls</th>
                      <th style={{ padding: "12px 20px" }}>Total Tokens</th>
                      <th style={{ padding: "12px 20px" }}>Est. Cost</th>
                    </tr>
                  </thead>
                  <tbody>
                    {usage.by_model.map((m, idx) => (
                      <tr
                        key={idx}
                        data-testid={`model-row-${m.model_name}`}
                        style={{ borderBottom: "1px solid var(--border-soft)" }}
                      >
                        <td style={{ padding: "12px 20px" }}>{m.provider}</td>
                        <td style={{ padding: "12px 20px", fontFamily: "monospace", fontWeight: "600" }}>
                          {m.model_name}
                        </td>
                        <td style={{ padding: "12px 20px" }}>{m.calls}</td>
                        <td style={{ padding: "12px 20px" }}>{m.total_tokens.toLocaleString()}</td>
                        <td style={{ padding: "12px 20px", color: "var(--success-fg)", fontWeight: "600" }}>
                          {formatMicroUsd(m.estimated_cost_micro_usd)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        ) : null}
      </main>
    </div>
  );
}
