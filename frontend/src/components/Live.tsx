/* eslint-disable react-refresh/only-export-components */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { apiFetch } from "../api/client";
import type { components } from "../api/schema";
import { useAuth } from "../auth/AuthProvider";
import { useRouter } from "../router/Router";
import { useToast } from "./Toast";
import type { ToastKind } from "./Toast";

type RunSummary = components["schemas"]["RunSummary"];

export interface AppNotification {
  id: string;
  kind: ToastKind;
  title: string;
  message: string;
  at: number;
  href?: string;
  read: boolean;
}

interface LiveState {
  notifications: AppNotification[];
  unread: number;
  pendingApprovals: number;
  markAllRead: () => void;
  markRead: (id: string) => void;
  clear: () => void;
}

const LiveContext = createContext<LiveState>({
  notifications: [],
  unread: 0,
  pendingApprovals: 0,
  markAllRead: () => {},
  markRead: () => {},
  clear: () => {},
});

const POLL_MS = 5000;

interface ApprovalLite {
  id: string;
  run_id: string;
  step_id?: string;
}

/**
 * Polls the active organization for run state transitions and pending approvals,
 * raising toasts + persistent notifications ("event triggers") in near-real time.
 * Only mounted by <App/>, so page-level tests never see the extra requests.
 */
export function LiveProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const { path, navigate } = useRouter();
  const toast = useToast();
  const [notifications, setNotifications] = useState<AppNotification[]>([]);
  const [pendingApprovals, setPendingApprovals] = useState(0);

  const orgId = useMemo(() => path.match(/^\/orgs\/([^/]+)/)?.[1] ?? null, [path]);
  const runStates = useRef<Map<string, string>>(new Map());
  const knownApprovals = useRef<Set<string>>(new Set());
  const seeded = useRef<string | null>(null);

  const push = useCallback(
    (n: Omit<AppNotification, "id" | "at" | "read">, actionLabel?: string) => {
      const item: AppNotification = { ...n, id: `${Date.now()}-${Math.random()}`, at: Date.now(), read: false };
      setNotifications((prev) => [item, ...prev].slice(0, 30));
      toast.toast({
        kind: n.kind,
        title: n.title,
        message: n.message,
        actionLabel,
        onAction: n.href ? () => navigate(n.href as string) : undefined,
      });
    },
    [toast, navigate]
  );

  useEffect(() => {
    if (!user || !orgId) {
      setPendingApprovals(0);
      return;
    }
    let cancelled = false;

    if (seeded.current !== orgId) {
      seeded.current = null;
      runStates.current = new Map();
      knownApprovals.current = new Set();
    }

    const tick = async () => {
      try {
        const [runs, approvals] = await Promise.all([
          apiFetch<{ items: RunSummary[] }>(`/v1/organizations/${orgId}/runs?limit=25`),
          apiFetch<{ items: ApprovalLite[] }>(`/v1/organizations/${orgId}/approvals?state=PENDING`),
        ]);
        if (cancelled) return;

        const firstPass = seeded.current !== orgId;

        setPendingApprovals(approvals.items.length);

        for (const a of approvals.items) {
          if (!knownApprovals.current.has(a.id)) {
            knownApprovals.current.add(a.id);
            if (!firstPass) {
              push(
                {
                  kind: "warning",
                  title: "Approval required",
                  message: `A run is waiting for a human decision${a.step_id ? ` at step "${a.step_id}"` : ""}.`,
                  href: `/orgs/${orgId}/approvals`,
                },
                "Review now"
              );
            }
          }
        }

        for (const r of runs.items) {
          const prev = runStates.current.get(r.id);
          runStates.current.set(r.id, r.state);
          if (firstPass || prev === r.state) continue;
          const short = r.id.slice(0, 8);
          const href = `/orgs/${orgId}/runs/${r.id}`;
          if (r.state === "SUCCEEDED") {
            push({ kind: "success", title: "Run succeeded", message: `Run ${short} completed successfully.`, href }, "View run");
          } else if (r.state === "FAILED") {
            push({ kind: "error", title: "Run failed", message: `Run ${short} failed. Open it to inspect the failing step.`, href }, "Investigate");
          } else if (r.state === "CANCELLED") {
            push({ kind: "info", title: "Run cancelled", message: `Run ${short} was cancelled.`, href });
          }
        }
        seeded.current = orgId;
      } catch {
        /* transient polling failures are silent by design */
      }
    };

    void tick();
    const id = window.setInterval(tick, POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [user, orgId, push]);

  const value = useMemo<LiveState>(
    () => ({
      notifications,
      unread: notifications.filter((n) => !n.read).length,
      pendingApprovals,
      markAllRead: () => setNotifications((p) => p.map((n) => ({ ...n, read: true }))),
      markRead: (id) => setNotifications((p) => p.map((n) => (n.id === id ? { ...n, read: true } : n))),
      clear: () => setNotifications([]),
    }),
    [notifications, pendingApprovals]
  );

  return <LiveContext.Provider value={value}>{children}</LiveContext.Provider>;
}

export function useLive(): LiveState {
  return useContext(LiveContext);
}
