import { useToast } from "../../components/Toast";
import { useEffect, useState, useCallback, useRef } from "react";
import { Header } from "../../components/Header";
import { apiFetch } from "../../api/client";
import { ApiError } from "../../api/errors";
import type { components } from "../../api/schema";
import { StepTimeline } from "./StepTimeline";
import { ApprovalBanner } from "./ApprovalBanner";

type RunDetail = components["schemas"]["RunDetail"];
type StepAttempt = components["schemas"]["StepAttemptResponse"];
type StepAttemptsList = components["schemas"]["StepAttemptsListResponse"];

interface RunDetailPageProps {
  orgId: string;
  runId: string;
}

const TERMINAL_STATES = new Set(["SUCCEEDED", "FAILED", "CANCELLED"]);

export function RunDetailPage({ orgId, runId }: RunDetailPageProps) {
  const toast = useToast();
  const [run, setRun] = useState<RunDetail | null>(null);
  const [steps, setSteps] = useState<StepAttempt[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Action states
  const [isSubmittingAction, setIsSubmittingAction] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [userRole, setUserRole] = useState<string>("viewer");

  useEffect(() => {
    apiFetch<components["schemas"]["Page_OrganizationResponse_"]>("/v1/organizations")
      .then((data) => {
        const current = data.items.find((o) => o.id === orgId);
        if (current) setUserRole(current.my_role);
      })
      .catch(() => {});
  }, [orgId]);

  const pollTimerRef = useRef<NodeJS.Timeout | null>(null);

  const fetchRunData = useCallback(async () => {
    try {
      const runData = await apiFetch<RunDetail>(`/v1/runs/${runId}`);
      setRun(runData);

      const stepsData = await apiFetch<StepAttemptsList>(`/v1/runs/${runId}/steps`);
      setSteps(stepsData.items);
      return runData.state;
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setError(err.detail || err.message);
      } else {
        setError("Failed to fetch run execution");
      }
      return null;
    } finally {
      setIsLoading(false);
    }
  }, [runId]);

  useEffect(() => {
    let isMounted = true;

    async function poll() {
      const state = await fetchRunData();
      if (!isMounted) return;

      // Continue polling every 2s if non-terminal
      if (state && !TERMINAL_STATES.has(state)) {
        pollTimerRef.current = setTimeout(poll, 2000);
      }
    }

    poll();

    return () => {
      isMounted = false;
      if (pollTimerRef.current) {
        clearTimeout(pollTimerRef.current);
      }
    };
  }, [fetchRunData]);

  const handleCancel = async () => {
    setIsSubmittingAction(true);
    setActionError(null);
    try {
      const updatedRun = await apiFetch<RunDetail>(`/v1/runs/${runId}/cancel`, {
        method: "POST",
      });
      toast.info("Cancellation requested", "The run will stop at the next step boundary.");
      setRun(updatedRun);
      await fetchRunData();
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setActionError(err.detail || err.message);
      } else {
        setActionError("Failed to cancel run");
      }
    } finally {
      setIsSubmittingAction(false);
    }
  };

  const handleRetry = async () => {
    setIsSubmittingAction(true);
    setActionError(null);
    try {
      const updatedRun = await apiFetch<RunDetail>(`/v1/runs/${runId}/retry`, {
        method: "POST",
      });
      toast.success("Retry queued", "A worker will pick the run up shortly.");
      setRun(updatedRun);
      await fetchRunData();
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setActionError(err.detail || err.message);
      } else {
        setActionError("Failed to retry run");
      }
    } finally {
      setIsSubmittingAction(false);
    }
  };

  const getStateBadgeStyle = (state: string) => {
    switch (state) {
      case "SUCCEEDED":
        return { background: "var(--success-bg)", color: "var(--success-fg)" };
      case "RUNNING":
        return { background: "var(--info-bg)", color: "var(--info-fg)" };
      case "QUEUED":
        return { background: "var(--warn-bg)", color: "var(--warn-fg)" };
      case "WAITING_APPROVAL":
        return { background: "var(--warn-bg)", color: "var(--warn-fg)" };
      case "FAILED":
        return { background: "var(--danger-bg)", color: "var(--danger-fg)" };
      case "CANCELLED":
        return { background: "var(--surface-2)", color: "var(--text-soft)" };
      default:
        return { background: "var(--border)", color: "var(--text)" };
    }
  };

  const canCancel = run && (run.state === "QUEUED" || run.state === "RUNNING" || run.state === "WAITING_APPROVAL");
  const canRetry = run && run.state === "FAILED";

  return (
    <div style={{ minHeight: "100vh", background: "var(--surface-2)" }}>
      <Header />
      <main style={{ maxWidth: "1000px", margin: "24px auto", padding: "0 16px" }}>
        <div style={{ marginBottom: "16px" }}>
          <a
            href={`/orgs/${orgId}/runs`}
            data-testid="link-back-runs"
            style={{ color: "var(--link)", textDecoration: "none", fontSize: "14px", fontWeight: "500" }}
          >
            ← Back to Runs
          </a>
        </div>

        {actionError && (
          <div
            data-testid="action-error"
            style={{
              padding: "12px 16px",
              background: "var(--danger-bg)",
              border: "1px solid var(--danger-border)",
              color: "var(--danger-fg)",
              borderRadius: "6px",
              marginBottom: "16px",
              fontSize: "14px",
            }}
          >
            {actionError}
          </div>
        )}

        {isLoading && !run ? (
          <div data-testid="run-loading" style={{ padding: "40px", textAlign: "center", color: "var(--text-muted)" }}>
            Loading execution details...
          </div>
        ) : error ? (
          <div data-testid="run-error" style={{ padding: "16px", background: "var(--danger-bg)", color: "var(--danger-fg)", borderRadius: "8px" }}>
            {error}
          </div>
        ) : run ? (
          <div>
            {/* Run Header Card */}
            <div
              data-testid="run-header-card"
              style={{
                background: "var(--surface)",
                borderRadius: "8px",
                border: "1px solid var(--border)",
                padding: "24px",
                marginBottom: "24px",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                <div>
                  <h1 style={{ margin: "0 0 8px 0", fontSize: "20px", fontWeight: "700" }}>
                    Run <span style={{ fontFamily: "monospace", fontSize: "16px", color: "var(--text-muted)" }}>{run.id}</span>
                  </h1>
                  <div style={{ fontSize: "13px", color: "var(--text-muted)" }}>
                    Version: v{run.workflow_version} | Trigger: {run.trigger_kind} | Started:{" "}
                    {run.started_at ? new Date(run.started_at).toLocaleString() : "Pending"}
                  </div>
                </div>

                <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
                  <span
                    data-testid="run-state-badge"
                    style={{
                      padding: "4px 12px",
                      borderRadius: "16px",
                      fontSize: "13px",
                      fontWeight: "600",
                      ...getStateBadgeStyle(run.state),
                    }}
                  >
                    {run.state}
                  </span>

                  {canCancel && (
                    <button
                      data-testid="cancel-run-btn"
                      onClick={handleCancel}
                      disabled={isSubmittingAction}
                      style={{
                        padding: "6px 14px",
                        background: "var(--grad-danger)",
                        color: "#fff",
                        border: "none",
                        borderRadius: "6px",
                        fontWeight: "600",
                        fontSize: "13px",
                        cursor: isSubmittingAction ? "not-allowed" : "pointer",
                      }}
                    >
                      {isSubmittingAction ? "Cancelling..." : "Cancel Run"}
                    </button>
                  )}

                  {canRetry && (
                    <button
                      data-testid="retry-run-btn"
                      onClick={handleRetry}
                      disabled={isSubmittingAction}
                      style={{
                        padding: "6px 14px",
                        background: "var(--grad-primary)",
                        color: "#fff",
                        border: "none",
                        borderRadius: "6px",
                        fontWeight: "600",
                        fontSize: "13px",
                        cursor: isSubmittingAction ? "not-allowed" : "pointer",
                      }}
                    >
                      {isSubmittingAction ? "Retrying..." : "Retry Run"}
                    </button>
                  )}
                </div>
              </div>

              {run.error_detail && (
                <div
                  data-testid="run-failure-banner"
                  style={{
                    marginTop: "16px",
                    padding: "12px",
                    background: "var(--danger-bg)",
                    border: "1px solid var(--danger-border)",
                    borderRadius: "6px",
                    color: "var(--danger-fg)",
                    fontSize: "13px",
                  }}
                >
                  <strong>{run.error_code || "FAILED"}:</strong> {run.error_detail}
                </div>
              )}
            </div>

            {run.state === "WAITING_APPROVAL" && (
              <ApprovalBanner
                orgId={orgId}
                runId={runId}
                userRole={userRole}
                onDecisionSubmitted={() => {
                  fetchRunData();
                }}
              />
            )}

            {/* Step Execution Timeline */}
            <div
              data-testid="step-timeline-card"
              style={{
                background: "var(--surface)",
                borderRadius: "8px",
                border: "1px solid var(--border)",
                padding: "24px",
                marginBottom: "24px",
              }}
            >
              <h2 style={{ margin: "0 0 16px 0", fontSize: "16px", fontWeight: "600" }}>
                Step Attempts ({steps.length})
              </h2>

              <StepTimeline steps={steps} />
            </div>

            {/* Inputs & Outputs Grid */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px" }}>
              <div
                style={{
                  background: "var(--surface)",
                  borderRadius: "8px",
                  border: "1px solid var(--border)",
                  padding: "16px",
                }}
              >
                <h3 style={{ margin: "0 0 8px 0", fontSize: "14px", fontWeight: "600" }}>Run Inputs</h3>
                <pre
                  data-testid="run-inputs-display"
                  style={{
                    margin: 0,
                    padding: "8px",
                    background: "var(--surface-2)",
                    border: "1px solid var(--border)",
                    borderRadius: "4px",
                    fontSize: "12px",
                    overflowX: "auto",
                  }}
                >
                  {JSON.stringify(run.inputs, null, 2)}
                </pre>
              </div>

              <div
                style={{
                  background: "var(--surface)",
                  borderRadius: "8px",
                  border: "1px solid var(--border)",
                  padding: "16px",
                }}
              >
                <h3 style={{ margin: "0 0 8px 0", fontSize: "14px", fontWeight: "600" }}>Run Outputs</h3>
                <pre
                  data-testid="run-outputs-display"
                  style={{
                    margin: 0,
                    padding: "8px",
                    background: "var(--surface-2)",
                    border: "1px solid var(--border)",
                    borderRadius: "4px",
                    fontSize: "12px",
                    overflowX: "auto",
                  }}
                >
                  {run.outputs ? JSON.stringify(run.outputs, null, 2) : "None (in-flight or failed)"}
                </pre>
              </div>
            </div>
          </div>
        ) : null}
      </main>
    </div>
  );
}
