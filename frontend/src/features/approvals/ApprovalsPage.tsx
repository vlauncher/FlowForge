import { useToast } from "../../components/Toast";
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
  const toast = useToast();
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
      if (decision === "approve") {
        toast.success("Approved", "The run will resume momentarily.");
      } else {
        toast.warning("Rejected", "The run has been stopped by your decision.");
      }
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
        return { background: "var(--success-bg)", color: "var(--success-fg)" };
      case "PENDING":
        return { background: "var(--warn-bg)", color: "var(--warn-fg)" };
      case "REJECTED":
        return { background: "var(--danger-bg)", color: "var(--danger-fg)" };
      case "EXPIRED":
        return { background: "var(--surface-2)", color: "var(--text-muted)" };
      case "CANCELLED":
        return { background: "var(--surface-2)", color: "var(--text-soft)" };
      default:
        return { background: "var(--border)", color: "var(--text)" };
    }
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
            marginBottom: "20px",
          }}
        >
          <div>
            <h1 style={{ margin: "0 0 4px 0", fontSize: "22px", fontWeight: "700" }}>
              Approval Requests
            </h1>
            <p style={{ margin: 0, fontSize: "14px", color: "var(--text-muted)" }}>
              Human governance gate for workflow executions requiring verification.
            </p>
          </div>
          <div style={{ display: "flex", gap: "12px" }}>
            <a
              href={`/orgs/${orgId}/runs`}
              data-testid="link-to-runs"
              style={{ color: "var(--link)", textDecoration: "none", fontSize: "14px", fontWeight: "500" }}
            >
              View Runs →
            </a>
            <a
              href={`/orgs/${orgId}/audit`}
              data-testid="link-to-audit"
              style={{ color: "var(--link)", textDecoration: "none", fontSize: "14px", fontWeight: "500" }}
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
                border: selectedState === st ? "2px solid var(--primary)" : "1px solid var(--border)",
                background: selectedState === st ? "var(--info-bg)" : "#fff",
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
            style={{ padding: "40px", textAlign: "center", color: "var(--text-muted)" }}
          >
            Loading approvals...
          </div>
        ) : error ? (
          <div
            data-testid="approvals-error"
            style={{
              padding: "16px",
              background: "var(--danger-bg)",
              color: "var(--danger-fg)",
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
              background: "var(--surface)",
              borderRadius: "8px",
              border: "1px solid var(--border)",
              color: "var(--text-muted)",
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
                    background: "var(--surface)",
                    borderRadius: "8px",
                    border: "1px solid var(--border)",
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
                      <div style={{ fontSize: "13px", color: "var(--text-muted)" }}>
                        Run:{" "}
                        <a
                          href={`/orgs/${orgId}/runs/${app.run_id}`}
                          style={{ color: "var(--link)", fontFamily: "monospace" }}
                        >
                          {app.run_id}
                        </a>{" "}
                        | Step: <strong>{app.step_id}</strong> | Required Role:{" "}
                        <span data-testid={`approval-assigned-role-${app.id}`}>
                          {app.assigned_role}
                        </span>
                      </div>
                      <div style={{ fontSize: "12px", color: "var(--text-dim)", marginTop: "4px" }}>
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
                        background: "var(--danger-bg)",
                        border: "1px solid var(--danger-border)",
                        color: "var(--danger-fg)",
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
                        background: "var(--danger-bg)",
                        border: "1px solid var(--danger-border)",
                        color: "var(--danger-fg)",
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
                          border: "1px solid var(--border)",
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
                            background: allowed ? "var(--success)" : "var(--text-dim)",
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
                            background: allowed ? "var(--danger)" : "var(--text-dim)",
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
                        background: "var(--surface-2)",
                        borderRadius: "6px",
                        fontSize: "13px",
                        color: "var(--text-soft)",
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
                        <span style={{ marginLeft: "12px", color: "var(--text-dim)", fontSize: "12px" }}>
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
                    background: "var(--surface)",
                    border: "1px solid var(--border)",
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
