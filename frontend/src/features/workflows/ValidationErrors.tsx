import type { components } from "../../api/schema";

type ValidationIssue = components["schemas"]["ValidationIssueSchema"];

export function ValidationErrors({ errors }: { errors: ValidationIssue[] }) {
  if (!errors || errors.length === 0) return null;

  return (
    <div
      style={{
        background: "#fee2e2",
        border: "1px solid #f87171",
        borderRadius: "6px",
        padding: "16px",
        marginBottom: "16px",
      }}
    >
      <h4 style={{ color: "#991b1b", margin: "0 0 8px 0", fontSize: "14px", fontWeight: "600" }}>
        Validation Issues ({errors.length})
      </h4>
      <ul role="alert" data-testid="validation-errors-list" style={{ margin: 0, paddingLeft: "20px", color: "#b91c1c", fontSize: "13px" }}>
        {errors.map((err, idx) => (
          <li key={idx} style={{ marginBottom: "6px" }}>
            <span style={{ fontWeight: "600", fontFamily: "monospace", marginRight: "6px" }}>
              [{err.code}]
            </span>
            <span>{err.message}</span>
            {err.field && (
              <span style={{ color: "#7f1d1d", marginLeft: "6px", fontSize: "12px", fontFamily: "monospace" }}>
                ({err.field})
              </span>
            )}
            {err.step_ids && err.step_ids.length > 0 && (
              <span style={{ marginLeft: "6px", fontSize: "12px", color: "#6b7280" }}>
                steps: {err.step_ids.join(", ")}
              </span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
