import { useEffect, useState } from "react";
import { useAuth } from "../auth/AuthProvider";
import { useRouter } from "../router/Router";
import { apiFetch } from "../api/client";
import type { components } from "../api/schema";

type Org = components["schemas"]["OrganizationResponse"];
type OrgPage = components["schemas"]["Page_OrganizationResponse_"];

export function Header({ currentOrgId }: { currentOrgId?: string }) {
  const { user, logout } = useAuth();
  const { navigate } = useRouter();
  const [orgs, setOrgs] = useState<Org[]>([]);

  useEffect(() => {
    if (!user) return;
    let isMounted = true;
    apiFetch<OrgPage>("/v1/organizations")
      .then((data) => {
        if (isMounted) {
          setOrgs(data.items);
        }
      })
      .catch(() => {});
    return () => {
      isMounted = false;
    };
  }, [user]);

  const handleOrgChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const selectedOrgId = e.target.value;
    if (!selectedOrgId) return;
    localStorage.setItem("ff.lastOrg", selectedOrgId);
    navigate(`/orgs/${selectedOrgId}/workflows`);
  };

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  return (
    <header className="header" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "12px 24px", borderBottom: "1px solid #e2e8f0" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "16px" }}>
        <button
          onClick={() => navigate("/orgs")}
          style={{ background: "none", border: "none", fontSize: "18px", fontWeight: "bold", cursor: "pointer", color: "#1e293b" }}
        >
          FlowForge
        </button>
        {user && orgs.length > 0 && (
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <label htmlFor="org-select" style={{ fontSize: "14px", color: "#64748b" }}>Organization:</label>
            <select
              id="org-select"
              data-testid="org-switcher"
              value={currentOrgId || ""}
              onChange={handleOrgChange}
              style={{ padding: "6px 10px", borderRadius: "4px", border: "1px solid #cbd5e1" }}
            >
              <option value="" disabled>Select Organization</option>
              {orgs.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.name} ({o.my_role})
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      {user ? (
        <div style={{ display: "flex", alignItems: "center", gap: "16px" }}>
          <span data-testid="user-display-name" style={{ fontSize: "14px", color: "#334155" }}>
            {user.display_name}
          </span>
          <button
            data-testid="logout-button"
            onClick={handleLogout}
            style={{ padding: "6px 12px", borderRadius: "4px", background: "#f1f5f9", border: "1px solid #cbd5e1", cursor: "pointer" }}
          >
            Log out
          </button>
        </div>
      ) : (
        <div style={{ display: "flex", gap: "12px" }}>
          <button
            onClick={() => navigate("/login")}
            style={{ padding: "6px 12px", borderRadius: "4px", border: "none", background: "none", cursor: "pointer" }}
          >
            Log in
          </button>
          <button
            onClick={() => navigate("/signup")}
            style={{ padding: "6px 12px", borderRadius: "4px", background: "#3b82f6", color: "#fff", border: "none", cursor: "pointer" }}
          >
            Sign up
          </button>
        </div>
      )}
    </header>
  );
}
