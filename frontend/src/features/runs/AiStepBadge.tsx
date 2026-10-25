export interface AiStepBadgeProps {
  stepType: string;
  output?: Record<string, unknown> | null;
  errorCode?: string | null;
  errorDetail?: string | null;
  durationMs?: number | null;
}

export function AiStepBadge({
  stepType,
  output,
  errorCode,
  errorDetail,
  durationMs,
}: AiStepBadgeProps) {
  if (stepType !== "llm_classify" && stepType !== "llm_transform") {
    return null;
  }

  const isInvalidOutput = errorCode === "LLM_INVALID_OUTPUT";

  return (
    <div
      data-testid="ai-step-badge"
      style={{
        marginTop: "8px",
        padding: "10px",
        borderRadius: "6px",
        background: isInvalidOutput ? "#fef2f2" : "#f0fdf4",
        border: `1px solid ${isInvalidOutput ? "#fca5a5" : "#bbf7d0"}`,
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
        <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
          <span
            style={{
              fontSize: "11px",
              fontWeight: "700",
              textTransform: "uppercase",
              padding: "2px 6px",
              borderRadius: "4px",
              background: isInvalidOutput ? "#ef4444" : "#16a34a",
              color: "#ffffff",
            }}
          >
            AI {stepType === "llm_classify" ? "Classification" : "Transformation"}
          </span>
          <span style={{ fontSize: "11px", color: "#64748b" }}>
            Model: openrouter/free
          </span>
        </div>

        {durationMs != null && (
          <span style={{ fontSize: "11px", color: "#64748b" }}>
            Latency: {durationMs} ms
          </span>
        )}
      </div>

      {isInvalidOutput ? (
        <div
          data-testid="ai-invalid-output"
          style={{
            color: "#991b1b",
            fontSize: "12px",
            fontWeight: "600",
            padding: "4px 0",
          }}
        >
          <span>Validation Error: LLM_INVALID_OUTPUT</span>
          {errorDetail && (
            <p style={{ margin: "4px 0 0 0", fontSize: "11px", fontWeight: "normal" }}>
              {errorDetail}
            </p>
          )}
        </div>
      ) : output ? (
        <div style={{ marginTop: "4px" }}>
          {stepType === "llm_classify" ? (
            <div style={{ display: "flex", gap: "10px", alignItems: "center" }}>
              <span
                data-testid="ai-classify-label"
                style={{
                  fontSize: "13px",
                  fontWeight: "600",
                  color: "#166534",
                  background: "#dcfce7",
                  padding: "3px 8px",
                  borderRadius: "4px",
                }}
              >
                Label: {String(output.label ?? "")}
              </span>
              {output.confidence != null && (
                <span
                  data-testid="ai-classify-confidence"
                  style={{
                    fontSize: "12px",
                    color: "#15803d",
                    fontWeight: "500",
                  }}
                >
                  Confidence: {Math.round(Number(output.confidence) * 100)}%
                </span>
              )}
            </div>
          ) : (
            <div data-testid="ai-transform-output" style={{ fontSize: "12px", color: "#166534" }}>
              <div style={{ fontWeight: "600", marginBottom: "4px" }}>Structured Output:</div>
              <pre
                style={{
                  margin: 0,
                  padding: "6px",
                  background: "#ffffff",
                  borderRadius: "4px",
                  border: "1px solid #dcfce7",
                  fontSize: "11px",
                }}
              >
                {JSON.stringify(output, null, 2)}
              </pre>
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}
