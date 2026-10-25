import type { ReactNode } from "react";
import { ArrowLeft, CheckCircle2 } from "lucide-react";
import { Logo } from "./Logo";
import { useRouter } from "../router/Router";

export function AuthLayout({ title, subtitle, children }: { title: string; subtitle: string; children: ReactNode }) {
  const { navigate } = useRouter();
  return (
    <div className="auth-wrap">
      <aside className="auth-art">
        <div className="orb orb-a" style={{ width: 380, height: 380, top: -120, left: -80, opacity: 0.35, position: "absolute", borderRadius: "50%", filter: "blur(80px)", background: "#4f46e5", animation: "drift 16s ease-in-out infinite" }} />
        <div style={{ position: "relative", display: "flex", alignItems: "center", gap: "0.7rem", fontWeight: 750, fontSize: "1.25rem" }}>
          <Logo size={34} /> FlowForge
        </div>
        <div style={{ position: "relative" }}>
          <h2>
            Workflows that <span className="grad-text">never lose their place.</span>
          </h2>
          <p>Durable AI agent automation with human approvals and exactly-once side effects.</p>
          <ul className="auth-points">
            <li><CheckCircle2 size={18} /> Crash-safe runs with lease takeover</li>
            <li><CheckCircle2 size={18} /> Approvals bound to run, step and version</li>
            <li><CheckCircle2 size={18} /> SSRF-proof tools and budget guardrails</li>
            <li><CheckCircle2 size={18} /> Live notifications for every state change</li>
          </ul>
        </div>
        <div style={{ position: "relative", fontSize: "0.78rem", color: "var(--text-dim)" }}>Open source portfolio project</div>
      </aside>
      <section className="auth-form-side" style={{ position: "relative" }}>
        <button className="btn btn-ghost auth-back" style={{ padding: "0.4rem 0.8rem", fontSize: "0.8rem" }} onClick={() => navigate("/")}>
          <ArrowLeft size={14} /> Home
        </button>
        <div className="auth-card">
          <h2>{title}</h2>
          <p className="auth-sub">{subtitle}</p>
          {children}
        </div>
      </section>
    </div>
  );
}
