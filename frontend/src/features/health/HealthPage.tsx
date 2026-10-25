import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../../api/client";
import { ApiError } from "../../api/errors";

interface HealthResponse {
  status: string;
}

interface ReadyResponse {
  status: string;
  checks: Record<string, string>;
}

export function HealthPage() {
  const healthQuery = useQuery<HealthResponse, ApiError>({
    queryKey: ["health"],
    queryFn: () => apiFetch<HealthResponse>("/health"),
    refetchInterval: 10_000,
    retry: false,
  });

  const readyQuery = useQuery<ReadyResponse, ApiError>({
    queryKey: ["ready"],
    queryFn: () => apiFetch<ReadyResponse>("/ready"),
    refetchInterval: 10_000,
    retry: false,
  });

  const isLoading = healthQuery.isLoading || readyQuery.isLoading;
  const isError = healthQuery.isError || readyQuery.isError;
  const error = (healthQuery.error || readyQuery.error) as ApiError | null;

  const handleRetry = () => {
    healthQuery.refetch();
    readyQuery.refetch();
  };

  return (
    <div className="app-container">
      <header>
        <h1>FlowForge Platform</h1>
        <p className="subtitle">Durable Workflow Automation & AI Orchestration</p>
      </header>

      <main>
        <section className="card" aria-labelledby="status-heading">
          <h2 id="status-heading" style={{ fontSize: "1.25rem", marginBottom: "1rem" }}>
            API System Status
          </h2>

          {isLoading && (
            <div role="status" aria-live="polite" style={{ padding: "1.5rem 0", color: "var(--text-muted)" }}>
              Checking API…
            </div>
          )}

          {isError && (
            <div role="alert" style={{ marginTop: "0.5rem" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "1rem" }}>
                <span className="badge badge-danger">Offline / Error</span>
                <span style={{ fontWeight: 600 }}>{error?.detail || error?.message || "Service check failed"}</span>
              </div>

              {error?.code && (
                <p className="meta-field" style={{ marginBottom: "0.5rem" }}>
                  <strong>Code:</strong> {error.code}
                </p>
              )}

              {error?.requestId && (
                <p className="meta-field" style={{ marginBottom: "1rem" }}>
                  <strong>Request ID:</strong> {error.requestId}
                </p>
              )}

              <button type="button" className="btn" onClick={handleRetry} autoFocus>
                Retry
              </button>
            </div>
          )}

          {!isLoading && !isError && (
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", marginBottom: "1.5rem" }}>
                <span className="badge badge-success">✓ API healthy</span>
                <span style={{ color: "var(--text-muted)", fontSize: "0.875rem" }}>All core services responsive</span>
              </div>

              <h3 style={{ fontSize: "1rem", color: "var(--text-muted)", marginBottom: "0.5rem" }}>
                Subsystem Readiness Checks
              </h3>

              {readyQuery.data && Object.keys(readyQuery.data.checks).length > 0 ? (
                <ul className="status-list" aria-label="Readiness subsystem checks">
                  {Object.entries(readyQuery.data.checks).map(([name, status]) => (
                    <li key={name} className="status-item">
                      <span style={{ textTransform: "capitalize", fontWeight: 500 }}>{name}</span>
                      <span
                        className={`badge ${status === "ok" ? "badge-success" : "badge-danger"}`}
                        aria-label={`${name}: ${status}`}
                      >
                        {status === "ok" ? "✓ ok" : "✗ fail"}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p style={{ color: "var(--text-muted)", fontSize: "0.875rem", fontStyle: "italic" }}>
                  No subsystem checks registered (Phase 1 baseline).
                </p>
              )}
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
