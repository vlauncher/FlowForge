import { useToast } from "../../components/Toast";
import { useEffect, useState, useCallback } from "react";
import { apiFetch } from "../../api/client";
import { ApiError } from "../../api/errors";
import type { components } from "../../api/schema";

type Trigger = components["schemas"]["TriggerOut"];
type Credential = components["schemas"]["CredentialResponse"];
type CredentialsPageResponse = components["schemas"]["CredentialsPageResponse"];

export function WebhookTriggerCard({
  orgId,
  workflowId,
}: {
  orgId: string;
  workflowId: string;
}) {
  const toast = useToast();
  const [triggers, setTriggers] = useState<Trigger[]>([]);
  const [credentials, setCredentials] = useState<Credential[]>([]);
  const [selectedCredentialId, setSelectedCredentialId] = useState<string>("");
  const [isLoading, setIsLoading] = useState(true);
  const [isCreating, setIsCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);
      const [trigList, credData] = await Promise.all([
        apiFetch<Trigger[]>(`/v1/workflows/${workflowId}/triggers`),
        apiFetch<CredentialsPageResponse>(`/v1/organizations/${orgId}/credentials`),
      ]);
      const safeTriggers = Array.isArray(trigList) ? trigList : [];
      const credItems = Array.isArray(credData) ? credData : credData?.items || [];
      setTriggers(safeTriggers);
      setCredentials(credItems);
      if (credItems.length > 0 && !selectedCredentialId) {
        setSelectedCredentialId(credItems[0].id);
      }
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setError(err.detail || err.message);
      } else {
        setError("Failed to load webhook trigger data");
      }
    } finally {
      setIsLoading(false);
    }
  }, [orgId, workflowId, selectedCredentialId]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleCreateTrigger = async () => {
    if (!selectedCredentialId) {
      setError("Please select a credential to sign webhooks");
      return;
    }
    try {
      setIsCreating(true);
      setError(null);
      const newTrigger = await apiFetch<Trigger>(`/v1/workflows/${workflowId}/triggers`, {
        method: "POST",
        body: JSON.stringify({ credential_id: selectedCredentialId }),
      });
      setTriggers((prev) => [newTrigger, ...prev]);
      toast.success("Webhook trigger created", "Sign requests with HMAC-SHA256 to invoke it.");
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setError(err.detail || err.message);
      } else {
        setError("Failed to create webhook trigger");
      }
    } finally {
      setIsCreating(false);
    }
  };

  if (isLoading) {
    return <div style={{ fontSize: "13px", color: "var(--text-muted)" }}>Loading webhook triggers...</div>;
  }

  const activeTrigger = triggers[0];

  return (
    <div
      data-testid="webhook-trigger-card"
      style={{
        background: "var(--surface)",
        borderRadius: "8px",
        border: "1px solid var(--border)",
        padding: "16px",
        marginTop: "20px",
      }}
    >
      <h3 style={{ margin: "0 0 12px 0", fontSize: "15px", fontWeight: "600", color: "var(--text)" }}>
        Webhook Trigger
      </h3>

      {error && (
        <div
          data-testid="webhook-trigger-error"
          style={{
            background: "var(--danger-bg)",
            color: "var(--danger-fg)",
            padding: "8px 12px",
            borderRadius: "4px",
            fontSize: "12px",
            marginBottom: "12px",
          }}
        >
          {error}
        </div>
      )}

      {activeTrigger ? (
        <div>
          <div style={{ marginBottom: "12px" }}>
            <span style={{ fontSize: "12px", color: "var(--text-muted)", display: "block", marginBottom: "4px" }}>
              Webhook Ingest URL:
            </span>
            <code
              data-testid="webhook-url-display"
              style={{
                display: "block",
                background: "var(--surface-2)",
                padding: "8px 12px",
                borderRadius: "4px",
                fontSize: "12px",
                color: "var(--text)",
                wordBreak: "break-all",
              }}
            >
              {activeTrigger.webhook_url}
            </code>
          </div>

          <div style={{ marginTop: "12px" }}>
            <span style={{ fontSize: "12px", color: "var(--text-muted)", display: "block", marginBottom: "4px" }}>
              Example Signed Ingestion (curl):
            </span>
            <pre
              data-testid="webhook-curl-snippet"
              style={{
                background: "var(--code-bg)",
                color: "var(--text)",
                padding: "12px",
                borderRadius: "6px",
                fontSize: "11px",
                overflowX: "auto",
              }}
            >
{`TIMESTAMP=$(date +%s)
SIGNATURE=$(echo -n "$TIMESTAMP.{\\"event_type\\":\\"order\\"}" | openssl dgst -sha256 -hmac "$SECRET" | sed 's/^.* //')

curl -X POST https://flowforge.example.com${activeTrigger.webhook_url} \\
  -H "Content-Type: application/json" \\
  -H "X-FlowForge-Timestamp: $TIMESTAMP" \\
  -H "X-FlowForge-Signature: v1=$SIGNATURE" \\
  -d '{"event_type":"order"}'`}
            </pre>
          </div>
        </div>
      ) : (
        <div>
          <p style={{ fontSize: "13px", color: "var(--text-muted)", margin: "0 0 12px 0" }}>
            No webhook trigger configured for this workflow. Create one to enable HMAC-SHA256 authenticated event triggers.
          </p>

          <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
            <select
              data-testid="trigger-credential-select"
              value={selectedCredentialId}
              onChange={(e) => setSelectedCredentialId(e.target.value)}
              style={{
                padding: "6px 10px",
                borderRadius: "4px",
                border: "1px solid var(--border)",
                fontSize: "13px",
              }}
            >
              {credentials.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name} ({c.provider})
                </option>
              ))}
            </select>

            <button
              data-testid="create-webhook-trigger-btn"
              onClick={handleCreateTrigger}
              disabled={isCreating || credentials.length === 0}
              style={{
                padding: "6px 14px",
                borderRadius: "4px",
                background: "var(--grad-primary)",
                color: "#fff",
                border: "none",
                fontWeight: "500",
                fontSize: "13px",
                cursor: isCreating ? "not-allowed" : "pointer",
              }}
            >
              {isCreating ? "Creating..." : "Create Webhook Trigger"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
