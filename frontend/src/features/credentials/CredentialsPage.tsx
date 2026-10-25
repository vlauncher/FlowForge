import { useToast } from "../../components/Toast";
import React, { useEffect, useState, useCallback } from "react";
import { Header } from "../../components/Header";
import { apiFetch } from "../../api/client";
import { ApiError } from "../../api/errors";
import type { components } from "../../api/schema";

type Credential = components["schemas"]["CredentialResponse"];
type CredentialsPageResponse = components["schemas"]["CredentialsPageResponse"];

interface CredentialsPageProps {
  orgId: string;
}

export function CredentialsPage({ orgId }: CredentialsPageProps) {
  const toast = useToast();
  const [credentials, setCredentials] = useState<Credential[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Form state
  const [name, setName] = useState("");
  const [provider, setProvider] = useState("");
  const [secret, setSecret] = useState("");
  const [hosts, setHosts] = useState("");
  const [scopes, setScopes] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  // Rotation modal state
  const [rotatingCred, setRotatingCred] = useState<Credential | null>(null);
  const [rotateSecret, setRotateSecret] = useState("");
  const [isRotating, setIsRotating] = useState(false);
  const [rotateError, setRotateError] = useState<string | null>(null);

  const fetchCredentials = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);
      const data = await apiFetch<CredentialsPageResponse>(
        `/v1/organizations/${orgId}/credentials`
      );
      setCredentials(data.items);
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setError(err.detail || err.message);
      } else {
        setError("Failed to fetch credentials");
      }
    } finally {
      setIsLoading(false);
    }
  }, [orgId]);

  useEffect(() => {
    fetchCredentials();
  }, [fetchCredentials]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !provider.trim() || !secret) {
      setFormError("Name, provider, and secret are required");
      return;
    }

    setIsSubmitting(true);
    setFormError(null);

    const allowedHosts = hosts
      .split(",")
      .map((h) => h.trim())
      .filter(Boolean);
    const permissionScopes = scopes
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);

    try {
      const created = await apiFetch<Credential>(
        `/v1/organizations/${orgId}/credentials`,
        {
          method: "POST",
          body: JSON.stringify({
            name: name.trim(),
            provider: provider.trim(),
            secret,
            allowed_hosts: allowedHosts,
            permission_scopes: permissionScopes,
          }),
        }
      );

      // Append new credential
      setCredentials((prev) => [created, ...prev]);

      // Clear sensitive secret input and other inputs
      setSecret("");
      setName("");
      setProvider("");
      setHosts("");
      setScopes("");
      toast.success("Credential stored", "The secret is encrypted at rest and never shown again.");
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setFormError(err.detail || err.message);
      } else {
        setFormError("Failed to store credential");
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleRotateSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!rotatingCred || !rotateSecret) {
      setRotateError("Secret is required");
      return;
    }
    try {
      setIsRotating(true);
      setRotateError(null);
      const updated = await apiFetch<Credential>(
        `/v1/organizations/${orgId}/credentials/${rotatingCred.id}/rotate`,
        {
          method: "POST",
          body: JSON.stringify({ secret: rotateSecret }),
        }
      );
      setCredentials((prev) =>
        prev.map((c) => (c.id === updated.id ? updated : c))
      );
      setRotatingCred(null);
      setRotateSecret("");
      toast.success("Secret rotated", "New requests use the rotated secret immediately.");
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setRotateError(err.detail || err.message);
      } else {
        setRotateError("Failed to rotate secret");
      }
    } finally {
      setIsRotating(false);
    }
  };

  return (
    <div style={{ minHeight: "100vh", background: "var(--surface-2)" }}>
      <Header />
      <main style={{ maxWidth: "1000px", margin: "24px auto", padding: "0 16px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "24px" }}>
          <div>
            <h1 style={{ margin: "0 0 4px 0", fontSize: "22px", fontWeight: "700" }}>
              Integration Credentials
            </h1>
            <p style={{ margin: 0, fontSize: "14px", color: "var(--text-muted)" }}>
              Encrypted API keys and secrets for external tool adapters.
            </p>
          </div>
          <div style={{ display: "flex", gap: "12px" }}>
            <a
              href={`/orgs/${orgId}/workflows`}
              style={{ color: "var(--link)", textDecoration: "none", fontSize: "14px", fontWeight: "500" }}
            >
              Workflows →
            </a>
            <a
              href={`/orgs/${orgId}/runs`}
              style={{ color: "var(--link)", textDecoration: "none", fontSize: "14px", fontWeight: "500" }}
            >
              Runs →
            </a>
          </div>
        </div>

        {error && (
          <div
            data-testid="credentials-error"
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
            {error}
          </div>
        )}

        <div style={{ display: "grid", gridTemplateColumns: "1fr 340px", gap: "24px" }}>
          {/* Credentials List */}
          <div
            style={{
              background: "var(--surface)",
              borderRadius: "8px",
              border: "1px solid var(--border)",
              padding: "20px",
            }}
          >
            <h2 style={{ margin: "0 0 16px 0", fontSize: "16px", fontWeight: "600" }}>
              Stored Credentials ({credentials.length})
            </h2>

            {isLoading ? (
              <div data-testid="credentials-loading" style={{ textAlign: "center", padding: "32px", color: "var(--text-muted)" }}>
                Loading credentials...
              </div>
            ) : credentials.length === 0 ? (
              <div data-testid="no-credentials-message" style={{ textAlign: "center", padding: "32px", color: "var(--text-muted)" }}>
                No credentials created yet. Add one using the form.
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                {credentials.map((cred) => (
                  <div
                    key={cred.id}
                    data-testid={`credential-item-${cred.id}`}
                    style={{
                      padding: "14px",
                      border: "1px solid var(--border)",
                      borderRadius: "6px",
                      background: "var(--surface-2)",
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "6px" }}>
                      <span data-testid={`credential-name-${cred.id}`} style={{ fontWeight: "700", fontSize: "14px", color: "var(--text)" }}>
                        {cred.name}
                      </span>
                      <span
                        style={{
                          fontSize: "11px",
                          fontWeight: "600",
                          padding: "2px 8px",
                          borderRadius: "4px",
                          background: "var(--info-bg)",
                          color: "var(--info-fg)",
                          textTransform: "uppercase",
                        }}
                      >
                        {cred.provider}
                      </span>
                    </div>

                    <div style={{ fontSize: "12px", color: "var(--text-muted)", marginBottom: "4px" }}>
                      Hosts: {cred.allowed_hosts.length > 0 ? cred.allowed_hosts.join(", ") : "None specified"}
                    </div>

                    <div style={{ fontSize: "12px", color: "var(--text-muted)", marginBottom: "4px" }}>
                      Scopes: {cred.permission_scopes.length > 0 ? cred.permission_scopes.join(", ") : "None"}
                    </div>

                    <div style={{ fontSize: "11px", color: "var(--text-dim)", marginBottom: "8px" }}>
                      Key ID: {cred.key_id} • Created: {new Date(cred.created_at).toLocaleDateString()}
                    </div>

                    {cred.rotated_at && (
                      <div
                        data-testid={`cred-rotated-at-${cred.id}`}
                        style={{ fontSize: "11px", color: "var(--success-fg)", marginBottom: "8px", fontWeight: "500" }}
                      >
                        Rotated: {new Date(cred.rotated_at).toLocaleString()}
                      </div>
                    )}

                    <button
                      data-testid={`rotate-cred-${cred.id}`}
                      onClick={() => {
                        setRotatingCred(cred);
                        setRotateSecret("");
                        setRotateError(null);
                      }}
                      style={{
                        padding: "4px 8px",
                        fontSize: "11px",
                        fontWeight: "500",
                        color: "var(--text-soft)",
                        background: "var(--surface-2)",
                        border: "1px solid var(--border)",
                        borderRadius: "4px",
                        cursor: "pointer",
                      }}
                    >
                      Rotate Secret
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Add Credential Form */}
          <div
            style={{
              background: "var(--surface)",
              borderRadius: "8px",
              border: "1px solid var(--border)",
              padding: "20px",
              height: "fit-content",
            }}
          >
            <h2 style={{ margin: "0 0 16px 0", fontSize: "16px", fontWeight: "600" }}>
              Add Credential
            </h2>

            {formError && (
              <div
                data-testid="credential-form-error"
                style={{
                  padding: "8px 12px",
                  background: "var(--danger-bg)",
                  color: "var(--danger-fg)",
                  borderRadius: "4px",
                  marginBottom: "12px",
                  fontSize: "12px",
                }}
              >
                {formError}
              </div>
            )}

            <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
              <div>
                <label style={{ display: "block", fontSize: "12px", fontWeight: "600", color: "var(--text)", marginBottom: "4px" }}>
                  Name
                </label>
                <input
                  data-testid="credential-name-input"
                  type="text"
                  placeholder="e.g. stripe_prod"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  style={{ width: "100%", padding: "8px", borderRadius: "4px", border: "1px solid var(--border)", fontSize: "13px", boxSizing: "border-box" }}
                  required
                />
              </div>

              <div>
                <label style={{ display: "block", fontSize: "12px", fontWeight: "600", color: "var(--text)", marginBottom: "4px" }}>
                  Provider
                </label>
                <input
                  data-testid="credential-provider-input"
                  type="text"
                  placeholder="e.g. stripe"
                  value={provider}
                  onChange={(e) => setProvider(e.target.value)}
                  style={{ width: "100%", padding: "8px", borderRadius: "4px", border: "1px solid var(--border)", fontSize: "13px", boxSizing: "border-box" }}
                  required
                />
              </div>

              <div>
                <label style={{ display: "block", fontSize: "12px", fontWeight: "600", color: "var(--text)", marginBottom: "4px" }}>
                  Secret Key
                </label>
                <input
                  data-testid="credential-secret-input"
                  type="password"
                  placeholder="Paste raw API token"
                  value={secret}
                  onChange={(e) => setSecret(e.target.value)}
                  style={{ width: "100%", padding: "8px", borderRadius: "4px", border: "1px solid var(--border)", fontSize: "13px", boxSizing: "border-box" }}
                  required
                />
                <span style={{ fontSize: "11px", color: "var(--text-dim)" }}>
                  Encrypted at rest with AES-256-GCM. Never shown again.
                </span>
              </div>

              <div>
                <label style={{ display: "block", fontSize: "12px", fontWeight: "600", color: "var(--text)", marginBottom: "4px" }}>
                  Allowed Hosts (comma-separated)
                </label>
                <input
                  data-testid="credential-hosts-input"
                  type="text"
                  placeholder="api.stripe.com, stripe.com"
                  value={hosts}
                  onChange={(e) => setHosts(e.target.value)}
                  style={{ width: "100%", padding: "8px", borderRadius: "4px", border: "1px solid var(--border)", fontSize: "13px", boxSizing: "border-box" }}
                />
              </div>

              <div>
                <label style={{ display: "block", fontSize: "12px", fontWeight: "600", color: "var(--text)", marginBottom: "4px" }}>
                  Permission Scopes (comma-separated)
                </label>
                <input
                  data-testid="credential-scopes-input"
                  type="text"
                  placeholder="charges:write, customers:read"
                  value={scopes}
                  onChange={(e) => setScopes(e.target.value)}
                  style={{ width: "100%", padding: "8px", borderRadius: "4px", border: "1px solid var(--border)", fontSize: "13px", boxSizing: "border-box" }}
                />
              </div>

              <button
                data-testid="credential-submit-btn"
                type="submit"
                disabled={isSubmitting}
                style={{
                  marginTop: "8px",
                  padding: "10px",
                  background: "var(--grad-primary)",
                  color: "#fff",
                  border: "none",
                  borderRadius: "6px",
                  fontWeight: "600",
                  fontSize: "14px",
                  cursor: isSubmitting ? "not-allowed" : "pointer",
                }}
              >
                {isSubmitting ? "Encrypting & Storing..." : "Save Credential"}
              </button>
            </form>
          </div>
        </div>

        {/* Rotate Secret Modal */}
        {rotatingCred && (
          <div
            data-testid="rotate-secret-modal"
            style={{
              position: "fixed",
              top: 0,
              left: 0,
              right: 0,
              bottom: 0,
              background: "rgba(0, 0, 0, 0.5)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              zIndex: 1000,
            }}
          >
            <div
              style={{
                background: "var(--surface)",
                borderRadius: "8px",
                padding: "24px",
                width: "400px",
                maxWidth: "90%",
                boxShadow: "0 10px 15px -3px rgba(0, 0, 0, 0.1)",
              }}
            >
              <h3 style={{ margin: "0 0 12px 0", fontSize: "16px", fontWeight: "600" }}>
                Rotate Secret for {rotatingCred.name}
              </h3>

              {rotateError && (
                <div
                  data-testid="rotate-error"
                  style={{
                    background: "var(--danger-bg)",
                    color: "var(--danger-fg)",
                    padding: "8px 12px",
                    borderRadius: "4px",
                    fontSize: "12px",
                    marginBottom: "12px",
                  }}
                >
                  {rotateError}
                </div>
              )}

              <form onSubmit={handleRotateSubmit}>
                <div style={{ marginBottom: "16px" }}>
                  <label style={{ display: "block", fontSize: "12px", fontWeight: "600", color: "var(--text)", marginBottom: "4px" }}>
                    New Secret
                  </label>
                  <input
                    data-testid="rotate-secret-input"
                    type="password"
                    placeholder="Enter new secret"
                    value={rotateSecret}
                    onChange={(e) => setRotateSecret(e.target.value)}
                    style={{ width: "100%", padding: "8px", borderRadius: "4px", border: "1px solid var(--border)", fontSize: "13px", boxSizing: "border-box" }}
                  />
                </div>

                <div style={{ display: "flex", justifyContent: "flex-end", gap: "8px" }}>
                  <button
                    type="button"
                    onClick={() => setRotatingCred(null)}
                    style={{
                      padding: "8px 14px",
                      background: "var(--surface-2)",
                      border: "1px solid var(--border)",
                      borderRadius: "6px",
                      fontSize: "13px",
                      cursor: "pointer",
                    }}
                  >
                    Cancel
                  </button>
                  <button
                    data-testid="submit-rotate-btn"
                    type="submit"
                    disabled={isRotating}
                    style={{
                      padding: "8px 14px",
                      background: "var(--grad-primary)",
                      color: "#fff",
                      border: "none",
                      borderRadius: "6px",
                      fontSize: "13px",
                      fontWeight: "600",
                      cursor: isRotating ? "not-allowed" : "pointer",
                    }}
                  >
                    {isRotating ? "Rotating..." : "Submit Rotation"}
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
