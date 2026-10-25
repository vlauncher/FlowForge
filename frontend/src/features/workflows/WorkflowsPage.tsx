import { useToast } from "../../components/Toast";
import React, { useEffect, useState, useCallback } from "react";
import { Header } from "../../components/Header";
import { useRouter } from "../../router/Router";
import { apiFetch } from "../../api/client";
import { ApiError } from "../../api/errors";
import type { components } from "../../api/schema";

type Workflow = components["schemas"]["WorkflowResponse"];
type WorkflowPage = components["schemas"]["Page_WorkflowResponse_"];
type Org = components["schemas"]["OrganizationResponse"];

export function WorkflowsPage({ orgId }: { orgId: string }) {
  const toast = useToast();
  const { navigate } = useRouter();
  const [org, setOrg] = useState<Org | null>(null);
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [includeArchived, setIncludeArchived] = useState(false);

  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // New Workflow Form State
  const [showNewModal, setShowNewModal] = useState(false);
  const [displayName, setDisplayName] = useState("");
  const [description, setDescription] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const fetchOrgDetails = useCallback(async () => {
    try {
      const data = await apiFetch<Org>(`/v1/organizations/${orgId}`);
      setOrg(data);
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setError(err.detail || err.message);
      }
    }
  }, [orgId]);

  const fetchWorkflows = useCallback(async (reset: boolean = true, cursorToUse?: string | null) => {
    try {
      if (reset) {
        setIsLoading(true);
        setError(null);
      } else {
        setIsLoadingMore(true);
      }

      const params = new URLSearchParams();
      if (includeArchived) {
        params.set("include_archived", "true");
      }
      params.set("limit", "10");
      if (cursorToUse) {
        params.set("cursor", cursorToUse);
      }

      const res = await apiFetch<WorkflowPage>(
        `/v1/organizations/${orgId}/workflows?${params.toString()}`
      );

      if (reset) {
        setWorkflows(res.items);
      } else {
        setWorkflows((prev) => [...prev, ...res.items]);
      }
      setNextCursor(res.next_cursor || null);
      setHasMore(res.has_more);
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setError(err.detail || err.message);
      } else {
        setError("Failed to load workflows");
      }
    } finally {
      setIsLoading(false);
      setIsLoadingMore(false);
    }
  }, [orgId, includeArchived]);

  useEffect(() => {
    fetchOrgDetails();
    fetchWorkflows(true);
  }, [fetchOrgDetails, fetchWorkflows]);

  const handleToggleArchived = (e: React.ChangeEvent<HTMLInputElement>) => {
    setIncludeArchived(e.target.checked);
  };

  const handleLoadMore = () => {
    if (!hasMore || !nextCursor || isLoadingMore) return;
    fetchWorkflows(false, nextCursor);
  };

  const handleCreateWorkflow = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!displayName.trim()) return;

    setIsSubmitting(true);
    setFormError(null);

    try {
      const newWf = await apiFetch<Workflow>(`/v1/organizations/${orgId}/workflows`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          display_name: displayName.trim(),
          description: description.trim() || undefined,
        }),
      });

      setWorkflows((prev) => [newWf, ...prev]);
      toast.success("Workflow created", `${newWf.display_name} is ready for its first version.`);
      setShowNewModal(false);
      setDisplayName("");
      setDescription("");
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setFormError(err.detail || err.message || "Failed to create workflow");
      } else {
        setFormError("An unexpected error occurred");
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  // RBAC: viewer role cannot write workflows
  const canWriteWorkflow = org?.my_role ? org.my_role !== "viewer" : true;

  return (
    <div>
      <Header currentOrgId={orgId} />
      <main style={{ maxWidth: "1000px", margin: "40px auto", padding: "0 20px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "24px" }}>
          <div>
            <h1 style={{ fontSize: "24px", fontWeight: "bold" }}>{org ? org.name : "Workflows"}</h1>
            <p style={{ color: "var(--text-muted)", marginTop: "4px" }}>
              {org && (
                <span>
                  Role: <strong style={{ textTransform: "capitalize" }}>{org.my_role || "member"}</strong> • Plan: {org.plan?.toUpperCase() || "FREE"}
                </span>
              )}
            </p>
          </div>

          {canWriteWorkflow && (
            <button
              data-testid="new-workflow-btn"
              onClick={() => setShowNewModal(true)}
              style={{
                padding: "8px 16px",
                background: "var(--grad-primary)",
                color: "#fff",
                border: "none",
                borderRadius: "4px",
                cursor: "pointer",
                fontWeight: "500",
              }}
            >
              New Workflow
            </button>
          )}
        </div>

        {/* Filter Toolbar */}
        <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: "16px" }}>
          <label style={{ display: "flex", alignItems: "center", gap: "8px", fontSize: "14px", cursor: "pointer", color: "var(--text-soft)" }}>
            <input
              type="checkbox"
              data-testid="workflows-include-archived"
              checked={includeArchived}
              onChange={handleToggleArchived}
            />
            Include archived workflows
          </label>
        </div>

        {/* Workflow list states */}
        {isLoading && <p data-testid="workflows-loading" style={{ color: "var(--text-muted)" }}>Loading workflows...</p>}

        {error && (
          <div data-testid="workflows-error" style={{ padding: "12px", background: "var(--danger-bg)", color: "var(--danger-fg)", borderRadius: "4px", marginBottom: "16px" }}>
            {error}
          </div>
        )}

        {!isLoading && !error && workflows.length === 0 && (
          <div data-testid="workflows-empty" style={{ padding: "40px", textAlign: "center", border: "1px dashed var(--border)", borderRadius: "8px" }}>
            <p style={{ color: "var(--text-muted)", marginBottom: "16px" }}>No workflows found</p>
            {canWriteWorkflow && (
              <button
                onClick={() => setShowNewModal(true)}
                style={{ padding: "8px 16px", background: "var(--grad-primary)", color: "#fff", border: "none", borderRadius: "4px", cursor: "pointer" }}
              >
                Create your first workflow
              </button>
            )}
          </div>
        )}

        {!isLoading && workflows.length > 0 && (
          <div>
            <table style={{ width: "100%", borderCollapse: "collapse", border: "1px solid var(--border)", borderRadius: "8px", overflow: "hidden" }}>
              <thead>
                <tr style={{ background: "var(--surface-2)", textAlign: "left", borderBottom: "1px solid var(--border)" }}>
                  <th style={{ padding: "12px 16px", fontSize: "14px", fontWeight: "600", color: "var(--text-soft)" }}>Name</th>
                  <th style={{ padding: "12px 16px", fontSize: "14px", fontWeight: "600", color: "var(--text-soft)" }}>Status</th>
                  <th style={{ padding: "12px 16px", fontSize: "14px", fontWeight: "600", color: "var(--text-soft)" }}>Created</th>
                </tr>
              </thead>
              <tbody>
                {workflows.map((wf) => (
                  <tr
                    key={wf.id}
                    data-testid="workflow-row"
                    onClick={() => navigate(`/orgs/${orgId}/workflows/${wf.id}`)}
                    style={{ borderBottom: "1px solid var(--border-soft)", cursor: "pointer" }}
                  >
                    <td style={{ padding: "14px 16px" }}>
                      <div style={{ fontWeight: "600", color: "var(--text)" }}>{wf.display_name}</div>
                      {wf.description && <div style={{ fontSize: "13px", color: "var(--text-muted)", marginTop: "2px" }}>{wf.description}</div>}
                    </td>
                    <td style={{ padding: "14px 16px", fontSize: "14px" }}>
                      {wf.archived_at ? (
                        <span style={{ padding: "2px 8px", background: "var(--surface-2)", color: "var(--text-muted)", borderRadius: "4px", fontSize: "12px" }}>Archived</span>
                      ) : (
                        <span style={{ padding: "2px 8px", background: "var(--success-bg)", color: "var(--success-fg)", borderRadius: "4px", fontSize: "12px" }}>Active</span>
                      )}
                    </td>
                    <td style={{ padding: "14px 16px", fontSize: "13px", color: "var(--text-muted)" }}>
                      {new Date(wf.created_at).toLocaleDateString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {hasMore && (
              <div style={{ textAlign: "center", marginTop: "20px" }}>
                <button
                  data-testid="workflows-load-more"
                  onClick={handleLoadMore}
                  disabled={isLoadingMore}
                  style={{
                    padding: "8px 20px",
                    background: "var(--surface-2)",
                    border: "1px solid var(--border)",
                    borderRadius: "4px",
                    cursor: isLoadingMore ? "not-allowed" : "pointer",
                    fontSize: "14px",
                    color: "var(--text)",
                  }}
                >
                  {isLoadingMore ? "Loading more..." : "Load more"}
                </button>
              </div>
            )}
          </div>
        )}

        {/* New Workflow Modal */}
        {showNewModal && (
          <div
            style={{
              position: "fixed",
              top: 0,
              left: 0,
              right: 0,
              bottom: 0,
              background: "rgba(0,0,0,0.5)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              zIndex: 50,
            }}
          >
            <div style={{ background: "var(--surface)", padding: "24px", borderRadius: "8px", width: "100%", maxWidth: "480px" }}>
              <h2 style={{ fontSize: "20px", fontWeight: "bold", marginBottom: "16px" }}>New Workflow</h2>

              {formError && (
                <div data-testid="new-wf-error" style={{ padding: "8px", background: "var(--danger-bg)", color: "var(--danger-fg)", borderRadius: "4px", marginBottom: "12px", fontSize: "14px" }}>
                  {formError}
                </div>
              )}

              <form onSubmit={handleCreateWorkflow}>
                <div style={{ marginBottom: "16px" }}>
                  <label htmlFor="wf-name" style={{ display: "block", marginBottom: "6px", fontSize: "14px" }}>Display Name</label>
                  <input
                    id="wf-name"
                    data-testid="new-wf-name"
                    type="text"
                    required
                    value={displayName}
                    onChange={(e) => setDisplayName(e.target.value)}
                    placeholder="Document Analysis Pipeline"
                    style={{ width: "100%", padding: "8px", borderRadius: "4px", border: "1px solid var(--border)" }}
                  />
                </div>

                <div style={{ marginBottom: "20px" }}>
                  <label htmlFor="wf-desc" style={{ display: "block", marginBottom: "6px", fontSize: "14px" }}>
                    Description <span style={{ color: "var(--text-dim)" }}>(optional)</span>
                  </label>
                  <textarea
                    id="wf-desc"
                    data-testid="new-wf-desc"
                    rows={3}
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    placeholder="Extract text, summarize, and index in vector store"
                    style={{ width: "100%", padding: "8px", borderRadius: "4px", border: "1px solid var(--border)" }}
                  />
                </div>

                <div style={{ display: "flex", justifyContent: "flex-end", gap: "10px" }}>
                  <button
                    type="button"
                    onClick={() => setShowNewModal(false)}
                    style={{ padding: "8px 16px", borderRadius: "4px", border: "1px solid var(--border)", background: "none", cursor: "pointer" }}
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    data-testid="new-wf-submit"
                    disabled={isSubmitting}
                    style={{ padding: "8px 16px", borderRadius: "4px", background: "var(--grad-primary)", color: "#fff", border: "none", cursor: isSubmitting ? "not-allowed" : "pointer" }}
                  >
                    {isSubmitting ? "Creating..." : "Create Workflow"}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
