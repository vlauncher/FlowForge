import { useEffect, useState } from "react";
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
import { LandingPage } from "./features/landing/LandingPage";
import { ToastProvider } from "./components/Toast";
import { LiveProvider } from "./components/Live";
import { Sidebar } from "./components/Sidebar";
import { Logo } from "./components/Logo";
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
  const [sidebarOpen, setSidebarOpen] = useState(false);

  useEffect(() => {
    const toggle = () => setSidebarOpen((o) => !o);
    window.addEventListener("ff:toggle-sidebar", toggle);
    return () => window.removeEventListener("ff:toggle-sidebar", toggle);
  }, []);

  useEffect(() => {
    if (isLoading) return;

    const isPublic = path === "/login" || path === "/signup" || path === "/health" || path === "/";

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
      <div className="boot" role="status" aria-label="Loading FlowForge">
        <div className="boot-inner">
          <div className="boot-ring" />
          <Logo size={34} />
          Loading FlowForge...
        </div>
      </div>
    );
  }

  if (!user && path === "/") {
    return <LandingPage />;
  }

  const page = renderRoute();
  if (path === "/login" || path === "/signup" || !user) {
    return page;
  }
  return (
    <div className="shell">
      <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
      <div className="shell-main">{page}</div>
    </div>
  );

  function renderRoute() {
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
    <div className="notfound">
      <div>
        <div className="big">404</div>
        <h2 style={{ marginTop: "0.5rem" }}>Page Not Found</h2>
        <p style={{ color: "var(--text-muted)", margin: "0.5rem 0 1.5rem" }}>
          This route drifted off the graph.
        </p>
        <button className="btn" onClick={() => navigate("/orgs")}>
          Go to Organizations
        </button>
      </div>
    </div>
  );
  }
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <RouterProvider>
          <AuthProvider>
            <LiveProvider>
              <AppRoutes />
            </LiveProvider>
          </AuthProvider>
        </RouterProvider>
      </ToastProvider>
    </QueryClientProvider>
  );
}

export default App;
