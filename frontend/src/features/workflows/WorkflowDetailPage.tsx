import { useEffect, useState, useCallback } from "react";
import { Header } from "../../components/Header";
import { apiFetch } from "../../api/client";
import { ApiError } from "../../api/errors";
import { VersionEditor } from "./VersionEditor";
import { TriggerRunModal } from "../runs/TriggerRunModal";
import { WebhookTriggerCard } from "./WebhookTriggerCard";
import type { components } from "../../api/schema";

type Workflow = components["schemas"]["WorkflowResponse"];
type WorkflowVersion = components["schemas"]["WorkflowVersionResponse"];
type WorkflowVersionSummary = components["schemas"]["WorkflowVersionSummaryResponse"];
type VersionPage = components["schemas"]["Page_WorkflowVersionSummaryResponse_"];
type Org = components["schemas"]["OrganizationResponse"];

export function WorkflowDetailPage({ orgId, workflowId }: { orgId: string; workflowId: string }) {
  const [org, setOrg] = useState<Org | null>(null);
  const [workflow, setWorkflow] = useState<Workflow | null>(null);
  const [versions, setVersions] = useState<WorkflowVersionSummary[]>([]);
  const [selectedVersion, setSelectedVersion] = useState<WorkflowVersion | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isCreatingDraft, setIsCreatingDraft] = useState(false);
  const [isTriggerModalOpen, setIsTriggerModalOpen] = useState(false);

  const fetchDetails = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);

      // Fetch org to inspect role
      const orgData = await apiFetch<Org>(`/v1/organizations/${orgId}`);
      setOrg(orgData);

      // Fetch workflow
      const wfData = await apiFetch<Workflow>(`/v1/workflows/${workflowId}`);
      setWorkflow(wfData);

      // Fetch versions
      const verPage = await apiFetch<VersionPage>(`/v1/workflows/${workflowId}/versions`);
      setVersions(verPage.items);

      // If draft exists, select it; else select latest version
      const draft = verPage.items.find((v) => v.status === "draft");
      const targetVersionNum = draft ? draft.version : verPage.items[0]?.version;

      if (targetVersionNum) {
        const fullVer = await apiFetch<WorkflowVersion>(
          `/v1/workflows/${workflowId}/versions/${targetVersionNum}`
        );
        setSelectedVersion(fullVer);
      }
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setError(err.detail || err.message);
      } else {
        setError("Failed to load workflow details");
      }
    } finally {
      setIsLoading(false);
    }
  }, [orgId, workflowId]);

  useEffect(() => {
    fetchDetails();
  }, [fetchDetails]);

  const handleCreateDraft = async () => {
    setIsCreatingDraft(true);
    try {
      const latestVer = versions[0]?.version;
      const initialDef = selectedVersion?.definition_json || {
        schema_version: 1,
        name: workflow?.display_name || "New Workflow",
        start: "step_1",
        steps: [
          {
            id: "step_1",
            type: "set_data",
            config: { values: { status: "initialized" } },
            next: null,
          },
        ],
      };

      const newDraft = await apiFetch<WorkflowVersion>(`/v1/workflows/${workflowId}/versions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          definition: initialDef,
          from_version: latestVer,
        }),
      });

      setSelectedVersion(newDraft);
      // Re-fetch version list
      const verPage = await apiFetch<VersionPage>(`/v1/workflows/${workflowId}/versions`);
      setVersions(verPage.items);
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setError(err.detail || err.message);
      }
    } finally {
      setIsCreatingDraft(false);
    }
  };

  const handleSelectVersion = async (versionNum: number) => {
    try {
      const fullVer = await apiFetch<WorkflowVersion>(
        `/v1/workflows/${workflowId}/versions/${versionNum}`
      );
      setSelectedVersion(fullVer);
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setError(err.detail || err.message);
      }
    }
  };

  const hasDraft = versions.some((v) => v.status === "draft");

  return (
    <div>
      <Header currentOrgId={orgId} />
      <main style={{ maxWidth: "1200px", margin: "40px auto", padding: "0 24px" }}>
        {isLoading && <p data-testid="detail-loading" style={{ color: "var(--text-muted)" }}>Loading workflow...</p>}

        {error && (
          <div data-testid="detail-error" style={{ padding: "12px", background: "var(--danger-bg)", color: "var(--danger-fg)", borderRadius: "4px", marginBottom: "16px" }}>
            {error}
          </div>
        )}

        {!isLoading && workflow && (
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", borderBottom: "1px solid var(--border)", paddingBottom: "20px" }}>
              <div>
                <h1 style={{ fontSize: "24px", fontWeight: "bold", color: "var(--text)" }}>
                  {workflow.display_name}
                </h1>
                {workflow.description && (
                  <p style={{ color: "var(--text-muted)", marginTop: "4px" }}>{workflow.description}</p>
                )}
                <div style={{ marginTop: "8px", display: "flex", gap: "12px", alignItems: "center" }}>
                  <span style={{ fontSize: "13px", color: "var(--text-muted)" }}>
                    Active Version:
                  </span>
                  {workflow.current_version_id ? (
                    <span data-testid="published-badge" style={{ padding: "2px 8px", background: "var(--success-bg)", color: "var(--success-fg)", borderRadius: "4px", fontSize: "12px", fontWeight: "600" }}>
                      Published
                    </span>
                  ) : (
                    <span data-testid="unpublished-badge" style={{ padding: "2px 8px", background: "var(--warn-bg)", color: "var(--warn-fg)", borderRadius: "4px", fontSize: "12px" }}>
                      No published version
                    </span>
                  )}
                </div>
              </div>

              <div style={{ display: "flex", gap: "8px" }}>
                {workflow?.current_version_id && (
                  <button
                    data-testid="btn-trigger-run"
                    onClick={() => setIsTriggerModalOpen(true)}
                    style={{
                      padding: "8px 16px",
                      background: "var(--grad-success)",
                      color: "#fff",
                      border: "none",
                      borderRadius: "4px",
                      cursor: "pointer",
                      fontWeight: "500",
                    }}
                  >
                    Trigger Run
                  </button>
                )}

                {!hasDraft && (
                  <button
                    data-testid="btn-create-draft"
                    onClick={handleCreateDraft}
                    disabled={isCreatingDraft}
                    style={{
                      padding: "8px 16px",
                      background: "var(--grad-primary)",
                      color: "#fff",
                      border: "none",
                      borderRadius: "4px",
                      cursor: isCreatingDraft ? "not-allowed" : "pointer",
                      fontWeight: "500",
                    }}
                  >
                    {isCreatingDraft ? "Creating..." : "New Draft"}
                  </button>
                )}
              </div>
            </div>

            <TriggerRunModal
              workflowId={workflowId}
              orgId={orgId}
              isOpen={isTriggerModalOpen}
              onClose={() => setIsTriggerModalOpen(false)}
              onSuccess={(runId) => {
                setIsTriggerModalOpen(false);
                window.location.href = `/orgs/${orgId}/runs/${runId}`;
              }}
            />

            {/* Version History Selector */}
            <div style={{ display: "flex", gap: "8px", marginTop: "20px", alignItems: "center" }}>
              <span style={{ fontSize: "13px", fontWeight: "600", color: "var(--text-soft)" }}>Versions:</span>
              {versions.map((v) => (
                <button
                  key={v.id}
                  data-testid={`version-btn-${v.version}`}
                  onClick={() => handleSelectVersion(v.version)}
                  style={{
                    padding: "4px 10px",
                    borderRadius: "4px",
                    border: selectedVersion?.version === v.version ? "2px solid var(--primary)" : "1px solid var(--border)",
                    background: selectedVersion?.version === v.version ? "var(--info-bg)" : "#fff",
                    fontWeight: selectedVersion?.version === v.version ? "bold" : "normal",
                    fontSize: "12px",
                    cursor: "pointer",
                  }}
                >
                  v{v.version} ({v.status})
                </button>
              ))}
            </div>

            {selectedVersion && (
              <VersionEditor
                workflowId={workflowId}
                version={selectedVersion}
                userRole={org?.my_role}
                onVersionUpdated={(updated) => setSelectedVersion(updated)}
                onVersionPublished={(published) => {
                  setSelectedVersion(published);
                  fetchDetails();
                }}
              />
            )}

            <WebhookTriggerCard orgId={orgId} workflowId={workflowId} />
          </div>
        )}
      </main>
    </div>
  );
}
