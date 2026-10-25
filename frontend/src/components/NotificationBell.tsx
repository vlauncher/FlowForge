import { useEffect, useRef, useState } from "react";
import { AlertTriangle, Bell, CheckCircle2, Info, XCircle } from "lucide-react";
import { useLive } from "./Live";
import { useRouter } from "../router/Router";

function ago(ts: number): string {
  const s = Math.max(1, Math.floor((Date.now() - ts) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  return `${Math.floor(s / 3600)}h ago`;
}

const KIND_STYLE = {
  success: { Icon: CheckCircle2, bg: "var(--success-bg)", fg: "var(--success-fg)" },
  error: { Icon: XCircle, bg: "var(--danger-bg)", fg: "var(--danger-fg)" },
  warning: { Icon: AlertTriangle, bg: "var(--warn-bg)", fg: "var(--warn-fg)" },
  info: { Icon: Info, bg: "var(--info-bg)", fg: "var(--info-fg)" },
} as const;

export function NotificationBell() {
  const { notifications, unread, markAllRead, markRead, clear } = useLive();
  const { navigate } = useRouter();
  const [open, setOpen] = useState(false);
  const [ring, setRing] = useState(false);
  const prev = useRef(unread);
  const wrap = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (unread > prev.current) {
      setRing(true);
      const t = window.setTimeout(() => setRing(false), 1000);
      prev.current = unread;
      return () => window.clearTimeout(t);
    }
    prev.current = unread;
  }, [unread]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (wrap.current && !wrap.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="notif-wrap" ref={wrap}>
      <button
        className="icon-btn"
        aria-label={`Notifications${unread ? `, ${unread} unread` : ""}`}
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        data-testid="notification-bell"
      >
        <Bell size={17} className={ring ? "bell-ring" : undefined} />
        {unread > 0 && <span className="dot">{unread > 9 ? "9+" : unread}</span>}
      </button>
      {open && (
        <div className="notif-panel" role="dialog" aria-label="Notifications">
          <div className="notif-head">
            <span>Notifications</span>
            <span style={{ display: "flex", gap: "0.9rem" }}>
              <button onClick={markAllRead}>Mark all read</button>
              <button onClick={clear}>Clear</button>
            </span>
          </div>
          {notifications.length === 0 ? (
            <div className="notif-empty">
              You're all caught up.
              <br />
              Run results and approval requests will appear here live.
            </div>
          ) : (
            notifications.map((n) => {
              const { Icon, bg, fg } = KIND_STYLE[n.kind];
              return (
                <button
                  key={n.id}
                  className={`notif-item${n.read ? "" : " unread"}`}
                  onClick={() => {
                    markRead(n.id);
                    setOpen(false);
                    if (n.href) navigate(n.href);
                  }}
                >
                  <span className="notif-ico" style={{ background: bg, color: fg }}>
                    <Icon size={17} />
                  </span>
                  <span>
                    <div className="notif-title">{n.title}</div>
                    <div className="notif-msg">{n.message}</div>
                    <div className="notif-time">{ago(n.at)}</div>
                  </span>
                </button>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}
