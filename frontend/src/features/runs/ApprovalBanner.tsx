/* eslint-disable react-refresh/only-export-components */
import { useState, useEffect, useCallback } from "react";
import { apiFetch } from "../../api/client";
import { ApiError } from "../../api/errors";
import type { components } from "../../api/schema";

type Approval = components["schemas"]["ApprovalOut"];
type ApprovalsPage = components["schemas"]["ApprovalsPageResponse"];

export function renderApprovalSummary(summary: unknown): string {
  if (!summary) return "";
  if (typeof summary === "string") return summary;
  if (typeof summary === "object") {
    const s = summary as Record<string, unknown>;
    if (s.summary && typeof s.summary === "string") return s.summary;
    if (s.text && typeof s.text === "string") return s.text;
    return JSON.stringify(summary);
  }
  return String(summary);
}

const ROLE_RANK: Record<string, number> = {
  viewer: 0,
  operator: 1,
  reviewer: 2,
  admin: 3,
  owner: 4,
};

export function canDecideApproval(userRole?: string | null, assignedRole?: string | null): boolean {
  if (!userRole || !assignedRole) return false;
  const userRank = ROLE_RANK[userRole.toLowerCase()] ?? -1;
  const assignedRank = ROLE_RANK[assignedRole.toLowerCase()] ?? 999;
  if (userRank < 2) return false; // Must be reviewer, admin, or owner
  return userRank >= assignedRank;
}

interface ApprovalBannerProps {
  orgId: string;
  runId: string;
  userRole?: string;
  onDecisionSubmitted?: () => void;
}

export function ApprovalBanner({
  orgId,
  runId,
  userRole,
  onDecisionSubmitted,
}: ApprovalBannerProps) {
  const [approval, setApproval] = useState<Approval | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [comment, setComment] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchPendingApproval = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);
      const res = await apiFetch<ApprovalsPage>(
        `/v1/organizations/${orgId}/approvals?state=PENDING`
      );
      const matched = res.items.find((a) => a.run_id === runId);
      setApproval(matched || null);
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setError(err.detail || err.message);
      } else {
        setError("Failed to fetch pending approval");
      }
    } finally {
      setIsLoading(false);
    }
  }, [orgId, runId]);

  useEffect(() => {
    fetchPendingApproval();
  }, [fetchPendingApproval]);

  const handleDecision = async (decision: "approve" | "reject") => {
    if (!approval) return;
    setIsSubmitting(true);
    setError(null);

    try {
      await apiFetch<Approval>(`/v1/approvals/${approval.id}/decisions`, {
        method: "POST",
        body: JSON.stringify({
          decision,
          comment: comment.trim() || undefined,
        }),
      });
      if (onDecisionSubmitted) {
        onDecisionSubmitted();
      }
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        if (err.code === "INVALID_STATE_TRANSITION" || err.status === 409) {
          setError(
            err.detail || "Approval conflict: this request has already been decided or cancelled."
          );
        } else {
          setError(err.detail || err.message);
        }
      } else {
        setError("Failed to submit decision");
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  if (isLoading) {
    return (
      <div
        data-testid="approval-banner-loading"
        style={{
          padding: "16px",
          background: "#fefce8",
          border: "1px solid #fef08a",
          borderRadius: "8px",
          marginBottom: "20px",
          color: "#854d0e",
        }}
      >
        Loading approval details...
      </div>
    );
  }

  if (!approval) {
    return null;
  }

  const allowed = canDecideApproval(userRole, approval.assigned_role);
  const isExpired = new Date(approval.expires_at) <= new Date();

  return (
    <div
      data-testid="approval-banner"
      style={{
        padding: "20px",
        background: "#fefce8",
        border: "1px solid #fde047",
        borderRadius: "8px",
        marginBottom: "24px",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "12px" }}>
        <div>
          <span
            data-testid="approval-gate-tag"
            style={{
              display: "inline-block",
              padding: "2px 8px",
              background: "#ca8a04",
              color: "#fff",
              borderRadius: "4px",
              fontSize: "12px",
              fontWeight: "700",
              textTransform: "uppercase",
              marginBottom: "6px",
            }}
          >
            Human Approval Gate
          </span>
          <h3
            data-testid="approval-banner-summary"
            style={{ margin: "4px 0", fontSize: "16px", color: "#713f12" }}
          >
            {renderApprovalSummary(approval.summary)}
          </h3>
          <div style={{ fontSize: "13px", color: "#854d0e" }}>
            Step: <strong data-testid="approval-step-id">{approval.step_id}</strong> | Required
            Role: <strong data-testid="approval-assigned-role">{approval.assigned_role}</strong> |
            Expires:{" "}
            <span data-testid="approval-expires-at">
              {new Date(approval.expires_at).toLocaleString()}
            </span>
          </div>
        </div>
      </div>

      {!allowed && (
        <div
          data-testid="approval-role-warning"
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
          Your current role ({userRole || "unknown"}) cannot decide approvals assigned to{" "}
          {approval.assigned_role}. Requires role rank &ge; {approval.assigned_role}.
        </div>
      )}

      {error && (
        <div
          data-testid="approval-banner-error"
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
          {error}
        </div>
      )}

      <div style={{ marginTop: "12px" }}>
        <input
          data-testid="approval-comment-input"
          type="text"
          placeholder="Decision comment (optional)..."
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          disabled={!allowed || isSubmitting || isExpired}
          style={{
            width: "100%",
            boxSizing: "border-box",
            padding: "8px 12px",
            borderRadius: "6px",
            border: "1px solid #cbd5e1",
            fontSize: "13px",
            marginBottom: "12px",
          }}
        />

        <div style={{ display: "flex", gap: "10px" }}>
          <button
            data-testid="approve-btn"
            onClick={() => handleDecision("approve")}
            disabled={!allowed || isSubmitting || isExpired}
            style={{
              padding: "8px 16px",
              background: allowed && !isExpired ? "#16a34a" : "#94a3b8",
              color: "#fff",
              border: "none",
              borderRadius: "6px",
              fontWeight: "600",
              fontSize: "13px",
              cursor: allowed && !isExpired ? "pointer" : "not-allowed",
            }}
          >
            {isSubmitting ? "Submitting..." : "Approve"}
          </button>
          <button
            data-testid="reject-btn"
            onClick={() => handleDecision("reject")}
            disabled={!allowed || isSubmitting || isExpired}
            style={{
              padding: "8px 16px",
              background: allowed && !isExpired ? "#dc2626" : "#94a3b8",
              color: "#fff",
              border: "none",
              borderRadius: "6px",
              fontWeight: "600",
              fontSize: "13px",
              cursor: allowed && !isExpired ? "pointer" : "not-allowed",
            }}
          >
            {isSubmitting ? "Submitting..." : "Reject"}
          </button>
        </div>
      </div>
    </div>
  );
}
