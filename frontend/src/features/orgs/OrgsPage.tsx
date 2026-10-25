import React, { useEffect, useState } from "react";
import { Header } from "../../components/Header";
import { useRouter } from "../../router/Router";
import { apiFetch } from "../../api/client";
import { ApiError } from "../../api/errors";
import type { components } from "../../api/schema";

type Org = components["schemas"]["OrganizationResponse"];
type OrgPage = components["schemas"]["Page_OrganizationResponse_"];

export function OrgsPage() {
  const { navigate } = useRouter();
  const [orgs, setOrgs] = useState<Org[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Create Org Form State
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [createError, setCreateError] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);

  const fetchOrgs = async () => {
    try {
      setIsLoading(true);
      setError(null);
      const data = await apiFetch<OrgPage>("/v1/organizations");
      setOrgs(data.items);
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setError(err.detail || err.message);
      } else {
        setError("Failed to load organizations");
      }
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchOrgs();
  }, []);

  const handleSelectOrg = (orgId: string) => {
    localStorage.setItem("ff.lastOrg", orgId);
    navigate(`/orgs/${orgId}/workflows`);
  };

  const handleCreateOrg = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;

    setIsCreating(true);
    setCreateError(null);

    try {
      const payload: { name: string; slug?: string } = { name: name.trim() };
      if (slug.trim()) {
        payload.slug = slug.trim().toLowerCase();
      }

      const newOrg = await apiFetch<Org>("/v1/organizations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      setShowCreateModal(false);
      setName("");
      setSlug("");
      handleSelectOrg(newOrg.id);
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setCreateError(err.detail || err.message || "Failed to create organization");
      } else {
        setCreateError("An unexpected error occurred");
      }
    } finally {
      setIsCreating(false);
    }
  };

  return (
    <div>
      <Header />
      <main style={{ maxWidth: "800px", margin: "40px auto", padding: "0 20px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "24px" }}>
          <div>
            <h1 style={{ fontSize: "24px", fontWeight: "bold" }}>Organizations</h1>
            <p style={{ color: "#64748b", marginTop: "4px" }}>Select or create an organization to manage workflows</p>
          </div>
          <button
            data-testid="create-org-btn"
            onClick={() => setShowCreateModal(true)}
            style={{ padding: "8px 16px", background: "#3b82f6", color: "#fff", border: "none", borderRadius: "4px", cursor: "pointer", fontWeight: "500" }}
          >
            Create Organization
          </button>
        </div>

        {isLoading && <p data-testid="orgs-loading" style={{ color: "#64748b" }}>Loading organizations...</p>}

        {error && (
          <div data-testid="orgs-error" style={{ padding: "12px", background: "#fee2e2", color: "#b91c1c", borderRadius: "4px", marginBottom: "16px" }}>
            {error}
          </div>
        )}

        {!isLoading && !error && orgs.length === 0 && (
          <div data-testid="orgs-empty" style={{ padding: "40px", textAlign: "center", border: "1px dashed #cbd5e1", borderRadius: "8px" }}>
            <p style={{ color: "#64748b", marginBottom: "16px" }}>You are not a member of any organization yet.</p>
            <button
              onClick={() => setShowCreateModal(true)}
              style={{ padding: "8px 16px", background: "#3b82f6", color: "#fff", border: "none", borderRadius: "4px", cursor: "pointer" }}
            >
              Create your first organization
            </button>
          </div>
        )}

        <div style={{ display: "grid", gap: "16px" }}>
          {orgs.map((org) => (
            <div
              key={org.id}
              data-testid="org-card"
              onClick={() => handleSelectOrg(org.id)}
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                padding: "20px",
                border: "1px solid #e2e8f0",
                borderRadius: "8px",
                cursor: "pointer",
                transition: "border-color 0.2s",
              }}
            >
              <div>
                <h3 style={{ fontSize: "18px", fontWeight: "600", color: "#1e293b" }}>{org.name}</h3>
                <p style={{ fontSize: "14px", color: "#64748b", marginTop: "4px" }}>
                  slug: <code>{org.slug}</code> • Plan: <span style={{ textTransform: "uppercase", fontSize: "12px", fontWeight: "bold" }}>{org.plan}</span>
                </p>
              </div>
              <div style={{ textAlign: "right" }}>
                <span
                  style={{
                    display: "inline-block",
                    padding: "4px 8px",
                    background: "#f1f5f9",
                    color: "#475569",
                    borderRadius: "4px",
                    fontSize: "12px",
                    fontWeight: "500",
                    textTransform: "capitalize",
                  }}
                >
                  {org.my_role}
                </span>
              </div>
            </div>
          ))}
        </div>

        {showCreateModal && (
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
            <div style={{ background: "#fff", padding: "24px", borderRadius: "8px", width: "100%", maxWidth: "440px" }}>
              <h2 style={{ fontSize: "20px", fontWeight: "bold", marginBottom: "16px" }}>Create Organization</h2>

              {createError && (
                <div data-testid="org-create-error" style={{ padding: "8px", background: "#fee2e2", color: "#b91c1c", borderRadius: "4px", marginBottom: "12px", fontSize: "14px" }}>
                  {createError}
                </div>
              )}

              <form onSubmit={handleCreateOrg}>
                <div style={{ marginBottom: "16px" }}>
                  <label htmlFor="modal-org-name" style={{ display: "block", marginBottom: "6px", fontSize: "14px" }}>Organization Name</label>
                  <input
                    id="modal-org-name"
                    data-testid="org-name"
                    type="text"
                    required
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="Acme Corp"
                    style={{ width: "100%", padding: "8px", borderRadius: "4px", border: "1px solid #cbd5e1" }}
                  />
                </div>

                <div style={{ marginBottom: "20px" }}>
                  <label htmlFor="modal-org-slug" style={{ display: "block", marginBottom: "6px", fontSize: "14px" }}>
                    Slug <span style={{ color: "#94a3b8" }}>(optional, auto-derived if empty)</span>
                  </label>
                  <input
                    id="modal-org-slug"
                    data-testid="org-slug"
                    type="text"
                    value={slug}
                    onChange={(e) => setSlug(e.target.value)}
                    placeholder="acme-corp"
                    style={{ width: "100%", padding: "8px", borderRadius: "4px", border: "1px solid #cbd5e1" }}
                  />
                </div>

                <div style={{ display: "flex", justifyContent: "flex-end", gap: "10px" }}>
                  <button
                    type="button"
                    onClick={() => setShowCreateModal(false)}
                    style={{ padding: "8px 16px", borderRadius: "4px", border: "1px solid #cbd5e1", background: "none", cursor: "pointer" }}
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    data-testid="org-submit"
                    disabled={isCreating}
                    style={{ padding: "8px 16px", borderRadius: "4px", background: "#3b82f6", color: "#fff", border: "none", cursor: isCreating ? "not-allowed" : "pointer" }}
                  >
                    {isCreating ? "Creating..." : "Create"}
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
