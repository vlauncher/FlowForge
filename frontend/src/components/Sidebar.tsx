import { Activity, Building2, CheckSquare, GitBranch, KeyRound, PlayCircle, ScrollText, WalletCards } from "lucide-react";
import type { ComponentType } from "react";
import { useRouter } from "../router/Router";
import { useLive } from "./Live";
import { Logo } from "./Logo";

interface NavDef {
  label: string;
  to: string;
  icon: ComponentType<{ size?: number }>;
  match: RegExp;
  badge?: number;
}

export function Sidebar({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { path, navigate } = useRouter();
  const { pendingApprovals } = useLive();
  const orgId = path.match(/^\/orgs\/([^/]+)/)?.[1];

  const go = (to: string) => {
    navigate(to);
    onClose();
  };

  const orgNav: NavDef[] = orgId
    ? [
        { label: "Workflows", to: `/orgs/${orgId}/workflows`, icon: GitBranch, match: /\/workflows/ },
        { label: "Runs", to: `/orgs/${orgId}/runs`, icon: PlayCircle, match: /\/runs/ },
        { label: "Approvals", to: `/orgs/${orgId}/approvals`, icon: CheckSquare, match: /\/approvals/, badge: pendingApprovals },
        { label: "Usage & Budget", to: `/orgs/${orgId}/usage`, icon: WalletCards, match: /\/usage/ },
        { label: "Credentials", to: `/orgs/${orgId}/credentials`, icon: KeyRound, match: /\/credentials/ },
        { label: "Audit log", to: `/orgs/${orgId}/audit`, icon: ScrollText, match: /\/audit/ },
      ]
    : [];

  return (
    <>
      {open && <div className="sidebar-scrim" onClick={onClose} />}
      <aside className={`sidebar${open ? " open" : ""}`} aria-label="Primary navigation">
        <button className="sidebar-brand" onClick={() => go("/orgs")}>
          <Logo size={30} />
          <span>FlowForge</span>
        </button>

        <div className="sidebar-label">Workspace</div>
        <button className={`nav-item${path === "/orgs" ? " active" : ""}`} onClick={() => go("/orgs")}>
          <Building2 size={18} /> Organizations
        </button>

        {orgNav.length > 0 && <div className="sidebar-label">Organization</div>}
        {orgNav.map((n) => (
          <button
            key={n.label}
            className={`nav-item${n.match.test(path) ? " active" : ""}`}
            onClick={() => go(n.to)}
          >
            <n.icon size={18} />
            {n.label}
            {!!n.badge && n.badge > 0 && <span className="nav-badge">{n.badge}</span>}
          </button>
        ))}

        <div className="sidebar-label">System</div>
        <button className={`nav-item${path === "/health" ? " active" : ""}`} onClick={() => go("/health")}>
          <Activity size={18} /> System health
        </button>

        <div className="sidebar-foot">
          <span className="live-dot" /> Live event stream connected
        </div>
      </aside>
    </>
  );
}
