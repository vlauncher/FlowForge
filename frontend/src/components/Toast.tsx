/* eslint-disable react-refresh/only-export-components */
import { createContext, useCallback, useContext, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { AlertTriangle, CheckCircle2, Info, X, XCircle } from "lucide-react";

export type ToastKind = "success" | "error" | "warning" | "info";

export interface ToastOptions {
  title: string;
  message?: string;
  kind?: ToastKind;
  duration?: number;
  actionLabel?: string;
  onAction?: () => void;
}

interface ToastItem extends ToastOptions {
  id: number;
  leaving?: boolean;
}

interface ToastApi {
  toast: (opts: ToastOptions) => void;
  success: (title: string, message?: string) => void;
  error: (title: string, message?: string) => void;
  warning: (title: string, message?: string) => void;
  info: (title: string, message?: string) => void;
}

const noop = () => {};
const fallback: ToastApi = { toast: noop, success: noop, error: noop, warning: noop, info: noop };

const ToastContext = createContext<ToastApi>(fallback);

const ICONS = {
  success: CheckCircle2,
  error: XCircle,
  warning: AlertTriangle,
  info: Info,
} as const;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const counter = useRef(0);

  const dismiss = useCallback((id: number) => {
    setItems((prev) => prev.map((t) => (t.id === id ? { ...t, leaving: true } : t)));
    window.setTimeout(() => setItems((prev) => prev.filter((t) => t.id !== id)), 300);
  }, []);

  const toast = useCallback(
    (opts: ToastOptions) => {
      const id = ++counter.current;
      const duration = opts.duration ?? (opts.kind === "error" ? 7000 : 5000);
      setItems((prev) => [...prev.slice(-4), { ...opts, id, duration }]);
      window.setTimeout(() => dismiss(id), duration);
    },
    [dismiss]
  );

  const api = useMemo<ToastApi>(
    () => ({
      toast,
      success: (title, message) => toast({ kind: "success", title, message }),
      error: (title, message) => toast({ kind: "error", title, message }),
      warning: (title, message) => toast({ kind: "warning", title, message }),
      info: (title, message) => toast({ kind: "info", title, message }),
    }),
    [toast]
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="toast-region" role="region" aria-label="Notifications" aria-live="polite">
        {items.map((t) => {
          const kind = t.kind ?? "info";
          const Icon = ICONS[kind];
          return (
            <div
              key={t.id}
              className={`toast toast-${kind}${t.leaving ? " leaving" : ""}`}
              role={kind === "error" ? "alert" : "status"}
              style={{ ["--toast-dur" as string]: `${t.duration}ms` }}
            >
              <div className="toast-ico">
                <Icon size={18} />
              </div>
              <div className="toast-body">
                <div className="toast-title">{t.title}</div>
                {t.message && <div className="toast-msg">{t.message}</div>}
                {t.actionLabel && (
                  <button
                    className="toast-action"
                    onClick={() => {
                      t.onAction?.();
                      dismiss(t.id);
                    }}
                  >
                    {t.actionLabel}
                  </button>
                )}
              </div>
              <button className="toast-close" aria-label="Dismiss notification" onClick={() => dismiss(t.id)}>
                <X size={15} />
              </button>
              <span className="toast-progress" />
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  return useContext(ToastContext);
}
