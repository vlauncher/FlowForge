import { useState, useEffect, useCallback } from "react";
import { Header } from "../../components/Header";
import { apiFetch } from "../../api/client";
import { ApiError } from "../../api/errors";
import type { components } from "../../api/schema";

type AuditEvent = components["schemas"]["AuditEventOut"];
type AuditEventsPageResponse = components["schemas"]["AuditEventsPageResponse"];
type OrgPage = components["schemas"]["Page_OrganizationResponse_"];

interface AuditEventsPageProps {
  orgId: string;
}

export function AuditEventsPage({ orgId }: AuditEventsPageProps) {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [actionFilter, setActionFilter] = useState("");
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [userRole, setUserRole] = useState<string>("viewer");

  useEffect(() => {
    apiFetch<OrgPage>("/v1/organizations")
      .then((data) => {
        const found = data.items.find((o) => o.id === orgId);
        if (found) setUserRole(found.my_role);
      })
      .catch(() => {});
  }, [orgId]);

  const fetchEvents = useCallback(
    async (cursor?: string) => {
      try {
        setIsLoading(true);
        setError(null);

        const params = new URLSearchParams();
        params.set("limit", "25");
        if (actionFilter.trim()) {
          params.set("action", actionFilter.trim());
        }
        if (cursor) {
          params.set("cursor", cursor);
        }

        const data = await apiFetch<AuditEventsPageResponse>(
          `/v1/organizations/${orgId}/audit-events?${params.toString()}`
        );

        if (cursor) {
          setEvents((prev) => [...prev, ...data.items]);
        } else {
          setEvents(data.items);
        }
        setNextCursor(data.next_cursor || null);
      } catch (err: unknown) {
        if (err instanceof ApiError) {
          if (err.status === 403) {
            setError("Access denied: only organization owners and admins can view audit events.");
          } else {
            setError(err.detail || err.message);
          }
        } else {
          setError("Failed to load audit events");
        }
      } finally {
        setIsLoading(false);
      }
    },
    [orgId, actionFilter]
  );

  useEffect(() => {
    fetchEvents();
  }, [fetchEvents]);

  const isRestrictedRole = userRole !== "owner" && userRole !== "admin";

  return (
    <div style={{ minHeight: "100vh", background: "var(--surface-2)" }}>
      <Header currentOrgId={orgId} />
      <main style={{ maxWidth: "1200px", margin: "24px auto", padding: "0 16px" }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: "20px",
          }}
        >
          <div>
            <h1 style={{ margin: "0 0 4px 0", fontSize: "22px", fontWeight: "700" }}>
              Audit Events
            </h1>
            <p style={{ margin: 0, fontSize: "14px", color: "var(--text-muted)" }}>
              Append-only immutable record of administrative, execution, and security events.
            </p>
          </div>
          <div style={{ display: "flex", gap: "12px" }}>
            <a
              href={`/orgs/${orgId}/approvals`}
              data-testid="link-to-approvals"
              style={{ color: "var(--link)", textDecoration: "none", fontSize: "14px", fontWeight: "500" }}
            >
              Approvals →
            </a>
            <a
              href={`/orgs/${orgId}/workflows`}
              data-testid="link-to-workflows"
              style={{ color: "var(--link)", textDecoration: "none", fontSize: "14px", fontWeight: "500" }}
            >
              Workflows →
            </a>
          </div>
        </div>

        {/* Filter bar */}
        <div style={{ display: "flex", gap: "12px", marginBottom: "20px" }}>
          <input
            data-testid="audit-action-filter"
            type="text"
            placeholder="Filter by action (e.g. org.created, member.added)..."
            value={actionFilter}
            onChange={(e) => setActionFilter(e.target.value)}
            style={{
              padding: "8px 12px",
              borderRadius: "6px",
              border: "1px solid var(--border)",
              fontSize: "13px",
              width: "360px",
            }}
          />
        </div>

        {isRestrictedRole && error ? (
          <div
            data-testid="audit-forbidden-warning"
            style={{
              padding: "24px",
              background: "var(--danger-bg)",
              border: "1px solid var(--danger-border)",
              color: "var(--danger-fg)",
              borderRadius: "8px",
            }}
          >
            <h3 style={{ margin: "0 0 8px 0" }}>Forbidden</h3>
            <p style={{ margin: 0 }}>{error}</p>
          </div>
        ) : isLoading && events.length === 0 ? (
          <div
            data-testid="audit-loading"
            style={{ padding: "40px", textAlign: "center", color: "var(--text-muted)" }}
          >
            Loading audit events...
          </div>
        ) : error ? (
          <div
            data-testid="audit-error"
            style={{
              padding: "16px",
              background: "var(--danger-bg)",
              color: "var(--danger-fg)",
              borderRadius: "8px",
            }}
          >
            {error}
          </div>
        ) : events.length === 0 ? (
          <div
            data-testid="no-audit-events-message"
            style={{
              padding: "48px",
              textAlign: "center",
              background: "var(--surface)",
              borderRadius: "8px",
              border: "1px solid var(--border)",
              color: "var(--text-muted)",
            }}
          >
            No audit events found.
          </div>
        ) : (
          <div
            style={{
              background: "var(--surface)",
              borderRadius: "8px",
              border: "1px solid var(--border)",
              overflowX: "auto",
            }}
          >
            <table
              data-testid="audit-table"
              style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px", textAlign: "left" }}
            >
              <thead>
                <tr style={{ background: "var(--surface-2)", borderBottom: "1px solid var(--border)" }}>
                  <th style={{ padding: "12px 16px" }}>Timestamp</th>
                  <th style={{ padding: "12px 16px" }}>Action</th>
                  <th style={{ padding: "12px 16px" }}>Actor</th>
                  <th style={{ padding: "12px 16px" }}>Target</th>
                  <th style={{ padding: "12px 16px" }}>Request ID</th>
                  <th style={{ padding: "12px 16px" }}>Metadata</th>
                </tr>
              </thead>
              <tbody>
                {events.map((ev) => (
                  <tr
                    key={ev.id}
                    data-testid={`audit-row-${ev.id}`}
                    style={{ borderBottom: "1px solid var(--border-soft)" }}
                  >
                    <td style={{ padding: "12px 16px", whiteSpace: "nowrap", color: "var(--text-muted)" }}>
                      {new Date(ev.created_at).toLocaleString()}
                    </td>
                    <td style={{ padding: "12px 16px" }}>
                      <span
                        data-testid={`audit-action-${ev.id}`}
                        style={{
                          padding: "2px 8px",
                          background: "var(--surface-2)",
                          borderRadius: "4px",
                          fontFamily: "monospace",
                          fontWeight: "600",
                          color: "var(--text)",
                        }}
                      >
                        {ev.action}
                      </span>
                    </td>
                    <td style={{ padding: "12px 16px" }}>
                      <div>{ev.actor_type}</div>
                      {ev.actor_user_id && (
                        <div style={{ fontSize: "11px", color: "var(--text-dim)", fontFamily: "monospace" }}>
                          {ev.actor_user_id}
                        </div>
                      )}
                    </td>
                    <td style={{ padding: "12px 16px" }}>
                      <div>{ev.target_type}</div>
                      {ev.target_id && (
                        <div style={{ fontSize: "11px", color: "var(--text-dim)", fontFamily: "monospace" }}>
                          {ev.target_id}
                        </div>
                      )}
                    </td>
                    <td style={{ padding: "12px 16px", fontFamily: "monospace", fontSize: "12px", color: "var(--text-muted)" }}>
                      {ev.request_id || "—"}
                    </td>
                    <td style={{ padding: "12px 16px" }}>
                      {ev.redacted_metadata && Object.keys(ev.redacted_metadata).length > 0 ? (
                        <pre
                          data-testid={`audit-meta-${ev.id}`}
                          style={{
                            margin: 0,
                            padding: "6px 8px",
                            background: "var(--surface-2)",
                            borderRadius: "4px",
                            fontSize: "11px",
                            fontFamily: "monospace",
                            maxHeight: "80px",
                            overflowY: "auto",
                          }}
                        >
                          {JSON.stringify(ev.redacted_metadata, null, 2)}
                        </pre>
                      ) : (
                        <span style={{ color: "var(--text-dim)" }}>—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {nextCursor && (
              <div style={{ textAlign: "center", padding: "16px" }}>
                <button
                  data-testid="load-more-audit"
                  onClick={() => fetchEvents(nextCursor)}
                  disabled={isLoading}
                  style={{
                    padding: "8px 20px",
                    background: "var(--surface)",
                    border: "1px solid var(--border)",
                    borderRadius: "6px",
                    cursor: "pointer",
                    fontSize: "13px",
                    fontWeight: "500",
                  }}
                >
                  {isLoading ? "Loading..." : "Load More"}
                </button>
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  );
}
