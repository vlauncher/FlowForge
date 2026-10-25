import { useState, useEffect, useCallback } from "react";
import { Header } from "../../components/Header";
import { apiFetch } from "../../api/client";
import { ApiError } from "../../api/errors";
import type { components } from "../../api/schema";
import { canDecideApproval, renderApprovalSummary } from "../runs/ApprovalBanner";

type Approval = components["schemas"]["ApprovalOut"];
type ApprovalsPageResponse = components["schemas"]["ApprovalsPageResponse"];
type OrgPage = components["schemas"]["Page_OrganizationResponse_"];

const FILTER_STATES = ["ALL", "PENDING", "APPROVED", "REJECTED", "EXPIRED", "CANCELLED"] as const;
type FilterState = (typeof FILTER_STATES)[number];

interface ApprovalsPageProps {
  orgId: string;
}

export function ApprovalsPage({ orgId }: ApprovalsPageProps) {
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [selectedState, setSelectedState] = useState<FilterState>("PENDING");
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [userRole, setUserRole] = useState<string>("viewer");

  // Per-approval comment & submit state
  const [activeComments, setActiveComments] = useState<Record<string, string>>({});
  const [submittingIds, setSubmittingIds] = useState<Record<string, boolean>>({});
  const [decisionErrors, setDecisionErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    apiFetch<OrgPage>("/v1/organizations")
      .then((data) => {
        const found = data.items.find((o) => o.id === orgId);
        if (found) setUserRole(found.my_role);
      })
      .catch(() => {});
  }, [orgId]);

  const fetchApprovals = useCallback(
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

        const data = await apiFetch<ApprovalsPageResponse>(
          `/v1/organizations/${orgId}/approvals?${params.toString()}`
        );

        if (cursor) {
          setApprovals((prev) => [...prev, ...data.items]);
        } else {
          setApprovals(data.items);
        }
        setNextCursor(data.next_cursor || null);
      } catch (err: unknown) {
        if (err instanceof ApiError) {
          setError(err.detail || err.message);
        } else {
          setError("Failed to load approvals");
        }
      } finally {
        setIsLoading(false);
      }
    },
    [orgId, selectedState]
  );

  useEffect(() => {
    fetchApprovals();
  }, [fetchApprovals]);

  const handleDecision = async (approvalId: string, decision: "approve" | "reject") => {
    setSubmittingIds((prev) => ({ ...prev, [approvalId]: true }));
    setDecisionErrors((prev) => ({ ...prev, [approvalId]: "" }));

    try {
      const comment = (activeComments[approvalId] || "").trim();
      const updated = await apiFetch<Approval>(`/v1/approvals/${approvalId}/decisions`, {
        method: "POST",
        body: JSON.stringify({
          decision,
          comment: comment || undefined,
        }),
      });

      // Update in local state
      setApprovals((prev) =>
        prev.map((app) => (app.id === approvalId ? updated : app))
      );
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        if (err.code === "INVALID_STATE_TRANSITION" || err.status === 409) {
          setDecisionErrors((prev) => ({
            ...prev,
            [approvalId]:
              err.detail || "Approval conflict: already decided, cancelled, or expired.",
          }));
        } else {
          setDecisionErrors((prev) => ({
            ...prev,
            [approvalId]: err.detail || err.message,
          }));
        }
      } else {
        setDecisionErrors((prev) => ({
          ...prev,
          [approvalId]: "Failed to submit decision",
        }));
      }
    } finally {
      setSubmittingIds((prev) => ({ ...prev, [approvalId]: false }));
    }
  };

  const getStateBadgeStyle = (state: string) => {
    switch (state) {
      case "APPROVED":
        return { background: "#dcfce7", color: "#166534" };
      case "PENDING":
        return { background: "#fef9c3", color: "#854d0e" };
      case "REJECTED":
        return { background: "#fee2e2", color: "#991b1b" };
      case "EXPIRED":
        return { background: "#f3f4f6", color: "#6b7280" };
      case "CANCELLED":
        return { background: "#f1f5f9", color: "#475569" };
      default:
        return { background: "#e2e8f0", color: "#334155" };
    }
  };

  return (
    <div style={{ minHeight: "100vh", background: "#f8fafc" }}>
      <Header currentOrgId={orgId} />
      <main style={{ maxWidth: "1000px", margin: "24px auto", padding: "0 16px" }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: "20px",
          }}
        >
          <div>
            <h1 style={{ margin: "0 0 4px 0", fontSize: "22px", fontWeight: "700" }}>
              Approval Requests
            </h1>
            <p style={{ margin: 0, fontSize: "14px", color: "#64748b" }}>
              Human governance gate for workflow executions requiring verification.
            </p>
          </div>
          <div style={{ display: "flex", gap: "12px" }}>
            <a
              href={`/orgs/${orgId}/runs`}
              data-testid="link-to-runs"
              style={{ color: "#2563eb", textDecoration: "none", fontSize: "14px", fontWeight: "500" }}
            >
              View Runs →
            </a>
            <a
              href={`/orgs/${orgId}/audit`}
              data-testid="link-to-audit"
              style={{ color: "#2563eb", textDecoration: "none", fontSize: "14px", fontWeight: "500" }}
            >
              Audit Log →
            </a>
          </div>
        </div>

        {/* State Filter Buttons */}
        <div style={{ display: "flex", gap: "8px", marginBottom: "20px", flexWrap: "wrap" }}>
          {FILTER_STATES.map((st) => (
            <button
              key={st}
              data-testid={`filter-approval-${st.toLowerCase()}`}
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

        {isLoading && approvals.length === 0 ? (
          <div
            data-testid="approvals-loading"
            style={{ padding: "40px", textAlign: "center", color: "#64748b" }}
          >
            Loading approvals...
          </div>
        ) : error ? (
          <div
            data-testid="approvals-error"
            style={{
              padding: "16px",
              background: "#fee2e2",
              color: "#991b1b",
              borderRadius: "8px",
            }}
          >
            {error}
          </div>
        ) : approvals.length === 0 ? (
          <div
            data-testid="no-approvals-message"
            style={{
              padding: "48px",
              textAlign: "center",
              background: "#fff",
              borderRadius: "8px",
              border: "1px solid #e2e8f0",
              color: "#64748b",
            }}
          >
            No approval requests found for filter &quot;{selectedState}&quot;.
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
            {approvals.map((app) => {
              const allowed = canDecideApproval(userRole, app.assigned_role);
              const isPending = app.state === "PENDING";
              const isSubmitting = submittingIds[app.id] || false;
              const decError = decisionErrors[app.id];

              return (
                <div
                  key={app.id}
                  data-testid={`approval-card-${app.id}`}
                  style={{
                    background: "#fff",
                    borderRadius: "8px",
                    border: "1px solid #e2e8f0",
                    padding: "20px",
                    boxShadow: "0 1px 3px rgba(0,0,0,0.05)",
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "flex-start",
                      marginBottom: "12px",
                    }}
                  >
                    <div>
                      <h3
                        data-testid={`approval-summary-${app.id}`}
                        style={{ margin: "0 0 6px 0", fontSize: "16px", fontWeight: "600" }}
                      >
                        {renderApprovalSummary(app.summary)}
                      </h3>
                      <div style={{ fontSize: "13px", color: "#64748b" }}>
                        Run:{" "}
                        <a
                          href={`/orgs/${orgId}/runs/${app.run_id}`}
                          style={{ color: "#2563eb", fontFamily: "monospace" }}
                        >
                          {app.run_id}
                        </a>{" "}
                        | Step: <strong>{app.step_id}</strong> | Required Role:{" "}
                        <span data-testid={`approval-assigned-role-${app.id}`}>
                          {app.assigned_role}
                        </span>
                      </div>
                      <div style={{ fontSize: "12px", color: "#94a3b8", marginTop: "4px" }}>
                        Expires: {new Date(app.expires_at).toLocaleString()} | Created:{" "}
                        {new Date(app.created_at).toLocaleString()}
                      </div>
                    </div>

                    <span
                      data-testid={`approval-status-${app.id}`}
                      style={{
                        padding: "4px 10px",
                        borderRadius: "12px",
                        fontSize: "12px",
                        fontWeight: "600",
                        ...getStateBadgeStyle(app.state),
                      }}
                    >
                      {app.state}
                    </span>
                  </div>

                  {decError && (
                    <div
                      data-testid={`approval-error-${app.id}`}
                      style={{
                        padding: "8px 12px",
                        background: "#fee2e2",
                        border: "1px solid #fecaca",
                        color: "#991b1b",
                        borderRadius: "6px",
                        fontSize: "13px",
                        marginBottom: "12px",
                      }}
                    >
                      {decError}
                    </div>
                  )}

                  {isPending && !allowed && (
                    <div
                      data-testid={`approval-insufficient-role-${app.id}`}
                      style={{
                        padding: "8px 12px",
                        background: "#fee2e2",
                        border: "1px solid #fecaca",
                        color: "#991b1b",
                        borderRadius: "6px",
                        fontSize: "13px",
                        marginBottom: "12px",
                      }}
                    >
                      Your role ({userRole}) cannot decide approvals assigned to {app.assigned_role}
                      . Requires role rank &ge; {app.assigned_role}.
                    </div>
                  )}

                  {isPending ? (
                    <div style={{ marginTop: "12px" }}>
                      <input
                        data-testid={`approval-comment-${app.id}`}
                        type="text"
                        placeholder="Decision comment (optional)..."
                        value={activeComments[app.id] || ""}
                        onChange={(e) =>
                          setActiveComments((prev) => ({ ...prev, [app.id]: e.target.value }))
                        }
                        disabled={!allowed || isSubmitting}
                        style={{
                          width: "100%",
                          boxSizing: "border-box",
                          padding: "8px 12px",
                          borderRadius: "6px",
                          border: "1px solid #cbd5e1",
                          fontSize: "13px",
                          marginBottom: "10px",
                        }}
                      />
                      <div style={{ display: "flex", gap: "10px" }}>
                        <button
                          data-testid={`approval-approve-btn-${app.id}`}
                          onClick={() => handleDecision(app.id, "approve")}
                          disabled={!allowed || isSubmitting}
                          style={{
                            padding: "8px 16px",
                            background: allowed ? "#16a34a" : "#94a3b8",
                            color: "#fff",
                            border: "none",
                            borderRadius: "6px",
                            fontWeight: "600",
                            fontSize: "13px",
                            cursor: allowed ? "pointer" : "not-allowed",
                          }}
                        >
                          {isSubmitting ? "Submitting..." : "Approve"}
                        </button>
                        <button
                          data-testid={`approval-reject-btn-${app.id}`}
                          onClick={() => handleDecision(app.id, "reject")}
                          disabled={!allowed || isSubmitting}
                          style={{
                            padding: "8px 16px",
                            background: allowed ? "#dc2626" : "#94a3b8",
                            color: "#fff",
                            border: "none",
                            borderRadius: "6px",
                            fontWeight: "600",
                            fontSize: "13px",
                            cursor: allowed ? "pointer" : "not-allowed",
                          }}
                        >
                          {isSubmitting ? "Submitting..." : "Reject"}
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div
                      style={{
                        marginTop: "8px",
                        padding: "8px 12px",
                        background: "#f8fafc",
                        borderRadius: "6px",
                        fontSize: "13px",
                        color: "#475569",
                      }}
                    >
                      {app.decision_comment ? (
                        <span>
                          <strong>Decision Note:</strong> {app.decision_comment}
                        </span>
                      ) : (
                        <span>No comment provided.</span>
                      )}
                      {app.decided_at && (
                        <span style={{ marginLeft: "12px", color: "#94a3b8", fontSize: "12px" }}>
                          Decided on {new Date(app.decided_at).toLocaleString()}
                        </span>
                      )}
                    </div>
                  )}
                </div>
              );
            })}

            {nextCursor && (
              <div style={{ textAlign: "center", marginTop: "16px" }}>
                <button
                  data-testid="load-more-approvals"
                  onClick={() => fetchApprovals(nextCursor)}
                  disabled={isLoading}
                  style={{
                    padding: "8px 20px",
                    background: "#fff",
                    border: "1px solid #cbd5e1",
                    borderRadius: "6px",
                    cursor: "pointer",
                    fontSize: "13px",
                    fontWeight: "500",
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
