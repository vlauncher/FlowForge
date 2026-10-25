import { useEffect, useState } from "react";
import { useAuth } from "../auth/AuthProvider";
import { useRouter } from "../router/Router";
import { apiFetch } from "../api/client";
import { LogOut, Menu } from "lucide-react";
import { Logo } from "./Logo";
import { NotificationBell } from "./NotificationBell";
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

  const initials = (user?.display_name || "?")
    .split(/\s+/)
    .map((w) => w[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();

  return (
    <header className="header">
      <div className="header-left">
        <button
          className="icon-btn menu-btn"
          aria-label="Open navigation"
          onClick={() => window.dispatchEvent(new Event("ff:toggle-sidebar"))}
        >
          <Menu size={18} />
        </button>
        <button className="header-brand" onClick={() => navigate("/orgs")}>
          <Logo size={24} animated={false} /> FlowForge
        </button>
        {user && orgs.length > 0 && (
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <label htmlFor="org-select" className="header-label">
              Organization:
            </label>
            <select id="org-select" data-testid="org-switcher" value={currentOrgId || ""} onChange={handleOrgChange}>
              <option value="" disabled>
                Select Organization
              </option>
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
        <div className="header-right">
          <NotificationBell />
          <div className="user-chip">
            <span className="avatar" aria-hidden="true">
              {initials}
            </span>
            <span data-testid="user-display-name">{user.display_name}</span>
          </div>
          <button
            data-testid="logout-button"
            className="btn btn-ghost"
            style={{ padding: "0.4rem 0.8rem", fontSize: "0.8rem" }}
            onClick={handleLogout}
          >
            <LogOut size={14} /> Log out
          </button>
        </div>
      ) : (
        <div className="header-right">
          <button className="btn btn-ghost" onClick={() => navigate("/login")}>
            Log in
          </button>
          <button className="btn" onClick={() => navigate("/signup")}>
            Sign up
          </button>
        </div>
      )}
    </header>
  );
}
