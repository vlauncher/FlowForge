import { useEffect } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider, useAuth } from "./auth/AuthProvider";
import { RouterProvider, useRouter } from "./router/Router";
import { LoginPage } from "./features/auth/LoginPage";
import { SignupPage } from "./features/auth/SignupPage";
import { OrgsPage } from "./features/orgs/OrgsPage";
import { WorkflowsPage } from "./features/workflows/WorkflowsPage";
import { WorkflowDetailPage } from "./features/workflows/WorkflowDetailPage";
import { RunsListPage } from "./features/runs/RunsListPage";
import { RunDetailPage } from "./features/runs/RunDetailPage";
import { ApprovalsPage } from "./features/approvals/ApprovalsPage";
import { AuditEventsPage } from "./features/audit/AuditEventsPage";
import { UsageDashboardPage } from "./features/usage/UsageDashboardPage";
import { CredentialsPage } from "./features/credentials/CredentialsPage";
import { HealthPage } from "./features/health/HealthPage";
import "./styles.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: false,
    },
  },
});

function AppRoutes() {
  const { user, isLoading } = useAuth();
  const { path, navigate, setRedirectAfterLogin, redirectAfterLogin } = useRouter();

  useEffect(() => {
    if (isLoading) return;

    const isPublic = path === "/login" || path === "/signup" || path === "/health";

    if (!user && !isPublic) {
      setRedirectAfterLogin(path);
      navigate("/login");
    } else if (user && (path === "/login" || path === "/signup")) {
      const target = redirectAfterLogin || "/orgs";
      setRedirectAfterLogin(null);
      navigate(target);
    } else if (user && path === "/") {
      const lastOrg = localStorage.getItem("ff.lastOrg");
      if (lastOrg) {
        navigate(`/orgs/${lastOrg}/workflows`);
      } else {
        navigate("/orgs");
      }
    }
  }, [user, isLoading, path, navigate, setRedirectAfterLogin, redirectAfterLogin]);

  if (isLoading) {
    return (
      <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: "100vh" }}>
        <p style={{ color: "#64748b" }}>Loading FlowForge...</p>
      </div>
    );
  }

  // Route dispatching
  if (path === "/login") {
    return <LoginPage />;
  }

  if (path === "/signup") {
    return <SignupPage />;
  }

  if (path === "/health") {
    return <HealthPage />;
  }

  const credentialsMatch = path.match(/^\/orgs\/([^/]+)\/credentials$/);
  if (credentialsMatch) {
    const orgId = credentialsMatch[1];
    return <CredentialsPage orgId={orgId} />;
  }

  const approvalsMatch = path.match(/^\/orgs\/([^/]+)\/approvals$/);
  if (approvalsMatch) {
    const orgId = approvalsMatch[1];
    return <ApprovalsPage orgId={orgId} />;
  }

  const auditMatch = path.match(/^\/orgs\/([^/]+)\/audit$/);
  if (auditMatch) {
    const orgId = auditMatch[1];
    return <AuditEventsPage orgId={orgId} />;
  }

  const usageMatch = path.match(/^\/orgs\/([^/]+)\/usage$/);
  if (usageMatch) {
    const orgId = usageMatch[1];
    return <UsageDashboardPage orgId={orgId} />;
  }

  const runDetailMatch = path.match(/^\/orgs\/([^/]+)\/runs\/([^/]+)$/);
  if (runDetailMatch) {
    const orgId = runDetailMatch[1];
    const runId = runDetailMatch[2];
    return <RunDetailPage orgId={orgId} runId={runId} />;
  }

  const runsMatch = path.match(/^\/orgs\/([^/]+)\/runs$/);
  if (runsMatch) {
    const orgId = runsMatch[1];
    return <RunsListPage orgId={orgId} />;
  }

  const workflowDetailMatch = path.match(/^\/orgs\/([^/]+)\/workflows\/([^/]+)$/);
  if (workflowDetailMatch) {
    const orgId = workflowDetailMatch[1];
    const workflowId = workflowDetailMatch[2];
    return <WorkflowDetailPage orgId={orgId} workflowId={workflowId} />;
  }

  const workflowsMatch = path.match(/^\/orgs\/([^/]+)\/workflows$/);
  if (workflowsMatch) {
    const orgId = workflowsMatch[1];
    return <WorkflowsPage orgId={orgId} />;
  }

  if (path === "/orgs" || path === "/") {
    return <OrgsPage />;
  }

  return (
    <div style={{ padding: "40px", textAlign: "center" }}>
      <h2>Page Not Found</h2>
      <button onClick={() => navigate("/orgs")} style={{ marginTop: "16px" }}>
        Go to Organizations
      </button>
    </div>
  );
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider>
        <AuthProvider>
          <AppRoutes />
        </AuthProvider>
      </RouterProvider>
    </QueryClientProvider>
  );
}

export default App;
