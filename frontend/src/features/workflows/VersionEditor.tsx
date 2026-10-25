import { useState, useId } from "react";
import { apiFetch } from "../../api/client";
import { ApiError } from "../../api/errors";
import { ValidationErrors } from "./ValidationErrors";
import type { components } from "../../api/schema";

type WorkflowVersion = components["schemas"]["WorkflowVersionResponse"];
type ValidateResponse = components["schemas"]["WorkflowValidateResponse"];
type ValidationIssue = components["schemas"]["ValidationIssueSchema"];

interface VersionEditorProps {
  workflowId: string;
  version: WorkflowVersion;
  userRole?: string;
  onVersionUpdated?: (updated: WorkflowVersion) => void;
  onVersionPublished?: (published: WorkflowVersion) => void;
}

export function VersionEditor({
  workflowId,
  version,
  userRole,
  onVersionUpdated,
  onVersionPublished,
}: VersionEditorProps) {
  const jsonTextareaId = useId();
  const [jsonString, setJsonString] = useState(
    JSON.stringify(version.definition_json, null, 2)
  );
  const [parseError, setParseError] = useState<string | null>(null);
  const [validationIssues, setValidationIssues] = useState<ValidationIssue[]>([]);
  const [isValidating, setIsValidating] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isPublishing, setIsPublishing] = useState(false);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);

  // Can publish only if role is owner or admin
  const canPublish = userRole === "owner" || userRole === "admin";
  const isDraft = version.status === "draft";

  // Parse JSON for live step preview
  let parsedSteps: Array<{ id: string; type: string; next?: string | null }> = [];
  try {
    const parsed = JSON.parse(jsonString);
    if (parsed && Array.isArray(parsed.steps)) {
      parsedSteps = parsed.steps;
    }
  } catch {
    // Ignore syntax errors during typing
  }

  const handleValidate = async () => {
    setParseError(null);
    setActionSuccess(null);
    let parsedObj: Record<string, unknown>;
    try {
      parsedObj = JSON.parse(jsonString);
    } catch (err: unknown) {
      setParseError(err instanceof Error ? err.message : "Malformed JSON syntax");
      return;
    }

    setIsValidating(true);
    try {
      const res = await apiFetch<ValidateResponse>(`/v1/workflows/${workflowId}/validate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ definition: parsedObj }),
      });

      setValidationIssues(res.errors || []);
      if (res.valid) {
        setActionSuccess(`Workflow is valid! Checksum: ${res.checksum?.slice(0, 8)}...`);
      }
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setParseError(err.detail || err.message);
      }
    } finally {
      setIsValidating(false);
    }
  };

  const handleSaveDraft = async () => {
    setParseError(null);
    setActionSuccess(null);
    let parsedObj: Record<string, unknown>;
    try {
      parsedObj = JSON.parse(jsonString);
    } catch (err: unknown) {
      setParseError(err instanceof Error ? err.message : "Malformed JSON syntax");
      return;
    }

    setIsSaving(true);
    try {
      const res = await apiFetch<WorkflowVersion>(
        `/v1/workflows/${workflowId}/versions/${version.version}`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ definition: parsedObj }),
        }
      );
      setActionSuccess("Draft saved successfully.");
      onVersionUpdated?.(res);
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setParseError(err.detail || err.message);
      }
    } finally {
      setIsSaving(false);
    }
  };

  const handlePublish = async () => {
    setParseError(null);
    setValidationIssues([]);
    setActionSuccess(null);
    setIsPublishing(true);

    try {
      const res = await apiFetch<WorkflowVersion>(`/v1/workflows/${workflowId}/publish`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ version: version.version }),
      });
      setActionSuccess(`Version ${res.version} successfully published!`);
      onVersionPublished?.(res);
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        if (err.errors && err.errors.length > 0) {
          setValidationIssues(err.errors as ValidationIssue[]);
        } else {
          setParseError(err.detail || err.message);
        }
      }
    } finally {
      setIsPublishing(false);
    }
  };

  return (
    <div style={{ marginTop: "24px", border: "1px solid #e2e8f0", borderRadius: "8px", padding: "20px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
        <div>
          <h3 style={{ fontSize: "18px", fontWeight: "600", color: "#1e293b" }}>
            Version {version.version}{" "}
            <span
              data-testid="version-status-badge"
              style={{
                fontSize: "12px",
                padding: "2px 8px",
                borderRadius: "4px",
                background: version.status === "published" ? "#dcfce7" : "#fef3c7",
                color: version.status === "published" ? "#15803d" : "#b45309",
                fontWeight: "600",
                textTransform: "uppercase",
              }}
            >
              {version.status}
            </span>
          </h3>
          {version.checksum && (
            <p style={{ fontSize: "12px", color: "#64748b", marginTop: "4px", fontFamily: "monospace" }}>
              Checksum: {version.checksum}
            </p>
          )}
        </div>

        {/* Action Buttons */}
        <div style={{ display: "flex", gap: "8px" }}>
          <button
            data-testid="btn-validate"
            onClick={handleValidate}
            disabled={isValidating}
            style={{
              padding: "6px 14px",
              borderRadius: "4px",
              border: "1px solid #cbd5e1",
              background: "#fff",
              cursor: isValidating ? "not-allowed" : "pointer",
              fontSize: "13px",
            }}
          >
            {isValidating ? "Validating..." : "Validate"}
          </button>

          {isDraft && (
            <button
              data-testid="btn-save-draft"
              onClick={handleSaveDraft}
              disabled={isSaving}
              style={{
                padding: "6px 14px",
                borderRadius: "4px",
                border: "1px solid #cbd5e1",
                background: "#f8fafc",
                cursor: isSaving ? "not-allowed" : "pointer",
                fontSize: "13px",
              }}
            >
              {isSaving ? "Saving..." : "Save Draft"}
            </button>
          )}

          {isDraft && canPublish && (
            <button
              data-testid="btn-publish"
              onClick={handlePublish}
              disabled={isPublishing}
              style={{
                padding: "6px 14px",
                borderRadius: "4px",
                border: "none",
                background: "#16a34a",
                color: "#fff",
                cursor: isPublishing ? "not-allowed" : "pointer",
                fontSize: "13px",
                fontWeight: "600",
              }}
            >
              {isPublishing ? "Publishing..." : "Publish"}
            </button>
          )}
        </div>
      </div>

      {parseError && (
        <div data-testid="editor-error" style={{ padding: "10px", background: "#fee2e2", color: "#b91c1c", borderRadius: "4px", marginBottom: "16px", fontSize: "13px" }}>
          {parseError}
        </div>
      )}

      {actionSuccess && (
        <div data-testid="editor-success" style={{ padding: "10px", background: "#dcfce7", color: "#15803d", borderRadius: "4px", marginBottom: "16px", fontSize: "13px" }}>
          {actionSuccess}
        </div>
      )}

      <ValidationErrors errors={validationIssues} />

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "20px" }}>
        {/* Editor Area */}
        <div>
          <label
            htmlFor={jsonTextareaId}
            style={{ display: "block", marginBottom: "8px", fontSize: "13px", fontWeight: "600", color: "#475569" }}
          >
            Workflow definition JSON
          </label>
          <textarea
            id={jsonTextareaId}
            data-testid="workflow-json-editor"
            aria-label="Workflow definition JSON"
            rows={20}
            readOnly={!isDraft}
            value={jsonString}
            onChange={(e) => setJsonString(e.target.value)}
            style={{
              width: "100%",
              fontFamily: "monospace",
              fontSize: "13px",
              padding: "12px",
              borderRadius: "6px",
              border: "1px solid #cbd5e1",
              background: isDraft ? "#fff" : "#f8fafc",
            }}
          />
        </div>

        {/* Step List Preview */}
        <div>
          <div style={{ marginBottom: "8px", fontSize: "13px", fontWeight: "600", color: "#475569" }}>
            Step Preview ({parsedSteps.length} steps)
          </div>
          <div
            data-testid="step-preview-list"
            style={{ border: "1px solid #e2e8f0", borderRadius: "6px", padding: "12px", maxHeight: "400px", overflowY: "auto", background: "#f8fafc" }}
          >
            {parsedSteps.length === 0 ? (
              <p style={{ color: "#94a3b8", fontSize: "13px", textAlign: "center", marginTop: "40px" }}>
                No steps defined yet
              </p>
            ) : (
              parsedSteps.map((s, idx) => (
                <div
                  key={s.id || idx}
                  data-testid="step-preview-item"
                  style={{
                    padding: "10px",
                    background: "#fff",
                    border: "1px solid #e2e8f0",
                    borderRadius: "4px",
                    marginBottom: "8px",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <span style={{ fontWeight: "600", fontSize: "14px", color: "#1e293b" }}>{s.id}</span>
                    <span style={{ fontSize: "11px", padding: "2px 6px", background: "#e0f2fe", color: "#0369a1", borderRadius: "4px" }}>
                      {s.type}
                    </span>
                  </div>
                  <div style={{ fontSize: "12px", color: "#64748b", marginTop: "4px" }}>
                    next: <code>{s.next === null ? "null (end)" : s.next || "branching"}</code>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
