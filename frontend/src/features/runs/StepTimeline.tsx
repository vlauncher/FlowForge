import type { components } from "../../api/schema";
import { AiStepBadge } from "./AiStepBadge";

type StepAttempt = components["schemas"]["StepAttemptResponse"];

interface StepTimelineProps {
  steps: StepAttempt[];
}

export function StepTimeline({ steps }: StepTimelineProps) {
  // Group attempts by step_id preserving order of first appearance
  const groupedByStep = steps.reduce<Record<string, StepAttempt[]>>((acc, att) => {
    if (!acc[att.step_id]) {
      acc[att.step_id] = [];
    }
    acc[att.step_id].push(att);
    return acc;
  }, {});

  const stepIds = Object.keys(groupedByStep);

  const getStatusBadgeStyle = (status: string) => {
    switch (status) {
      case "SUCCEEDED":
        return { background: "#dcfce7", color: "#166534" };
      case "FAILED":
        return { background: "#fee2e2", color: "#991b1b" };
      case "RUNNING":
        return { background: "#dbeafe", color: "#1e40af" };
      default:
        return { background: "#f1f5f9", color: "#475569" };
    }
  };

  if (steps.length === 0) {
    return (
      <div data-testid="no-steps-message" style={{ color: "#64748b", fontSize: "13px" }}>
        No step attempts recorded yet.
      </div>
    );
  }

  return (
    <div data-testid="step-timeline" style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
      {stepIds.map((stepId) => {
        const attempts = groupedByStep[stepId];
        const latestAttempt = attempts[attempts.length - 1];

        return (
          <div
            key={stepId}
            data-testid={`step-attempt-${stepId}`}
            style={{
              padding: "16px",
              border: "1px solid #e2e8f0",
              borderRadius: "8px",
              background: "#ffffff",
            }}
          >
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                marginBottom: "12px",
                paddingBottom: "8px",
                borderBottom: "1px solid #f1f5f9",
              }}
            >
              <div>
                <span style={{ fontWeight: "700", fontSize: "15px", color: "#0f172a" }}>
                  {stepId}
                </span>
                <span style={{ marginLeft: "8px", fontSize: "12px", color: "#64748b" }}>
                  ({latestAttempt.step_type})
                </span>
              </div>
              <span style={{ fontSize: "12px", color: "#64748b" }}>
                {attempts.length} attempt{attempts.length > 1 ? "s" : ""}
              </span>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
              {attempts.map((att) => (
                <div
                  key={att.id}
                  data-testid={`step-attempt-${att.step_id}-${att.attempt_no}`}
                  style={{
                    padding: "10px 12px",
                    background: "#f8fafc",
                    border: "1px solid #e2e8f0",
                    borderRadius: "6px",
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      marginBottom: "6px",
                    }}
                  >
                    <span
                      data-testid={`attempt-badge-${att.step_id}-${att.attempt_no}`}
                      style={{
                        padding: "2px 8px",
                        borderRadius: "4px",
                        fontSize: "12px",
                        fontWeight: "600",
                        ...getStatusBadgeStyle(att.status),
                      }}
                    >
                      Attempt #{att.attempt_no} {att.status}
                      {att.error_code ? ` (${att.error_code})` : ""}
                    </span>

                    <span style={{ fontSize: "12px", color: "#64748b" }}>
                      Duration: {att.duration_ms != null ? `${att.duration_ms} ms` : "running"}
                    </span>
                  </div>

                  {att.error_detail && (
                    <div
                      data-testid={`attempt-error-${att.step_id}-${att.attempt_no}`}
                      style={{
                        fontSize: "12px",
                        color: "#b91c1c",
                        background: "#fef2f2",
                        padding: "6px 8px",
                        borderRadius: "4px",
                        marginTop: "6px",
                      }}
                    >
                      {att.error_detail}
                    </div>
                  )}

                  {(att.step_type === "llm_classify" || att.step_type === "llm_transform") && (
                    <AiStepBadge
                      stepType={att.step_type}
                      output={att.output as Record<string, unknown> | null}
                      errorCode={att.error_code}
                      errorDetail={att.error_detail}
                      durationMs={att.duration_ms}
                    />
                  )}

                  {att.output && att.step_type !== "llm_classify" && (
                    <div style={{ marginTop: "6px" }}>
                      <pre
                        data-testid={`step-output-${att.step_id}`}
                        style={{
                          margin: "6px 0 0 0",
                          padding: "8px",
                          background: "#fff",
                          border: "1px solid #cbd5e1",
                          borderRadius: "4px",
                          fontSize: "11px",
                          overflowX: "auto",
                        }}
                      >
                        {JSON.stringify(att.output, null, 2)}
                      </pre>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
