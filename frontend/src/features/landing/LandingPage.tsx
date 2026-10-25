import { useEffect, useMemo, useState } from "react";
import {
  ArrowRight,
  Boxes,
  Check,
  Copy,
  DatabaseBackup,
  Eye,
  Fingerprint,
  GitBranch,
  Gauge,
  LifeBuoy,
  Lock,
  ScanSearch,
  ShieldCheck,
  Sparkles,
  UserCheck,
  Wallet,
  Workflow,
} from "lucide-react";
import type { ComponentType, ReactNode } from "react";
import { useAuth } from "../../auth/AuthProvider";
import { useRouter } from "../../router/Router";
import { Logo } from "../../components/Logo";
import { HeroDemo } from "./HeroDemo";
import { useCountUp, useReveal, useSpotlight, useTypewriter } from "./hooks";
import "./landing.css";

const REPO_URL = "https://github.com/vlauncher/FlowForge";

function Reveal({ children, delay = 0, className = "" }: { children: ReactNode; delay?: number; className?: string }) {
  const ref = useReveal<HTMLDivElement>();
  return (
    <div ref={ref} className={`reveal ${className}`} style={{ transitionDelay: `${delay}ms` }}>
      {children}
    </div>
  );
}

function Stat({ value, decimals = 0, prefix = "", suffix = "", label, note }: { value: number; decimals?: number; prefix?: string; suffix?: string; label: string; note: string }) {
  const { ref, text } = useCountUp(value, 1700, decimals);
  return (
    <div className="stat">
      <div className="stat-num">
        {prefix}
        <span ref={ref}>{text}</span>
        {suffix}
      </div>
      <div className="stat-label">{label}</div>
      <div className="stat-note">{note}</div>
    </div>
  );
}

interface Feature {
  icon: ComponentType<{ size?: number }>;
  title: string;
  body: string;
  tag: string;
  span?: string;
}

const FEATURES: Feature[] = [
  { icon: Workflow, title: "Durable by construction", body: "Transactional outbox, leases and fencing tokens mean a crashed worker never loses a run or double-commits a step.", tag: "Outbox · Leases · Epochs", span: "wide" },
  { icon: Fingerprint, title: "Tool-effects ledger", body: "Every external write is recorded INTENDED → COMMITTED before it can ever repeat. Retries are safe, replays are no-ops.", tag: "Zero duplicates" },
  { icon: UserCheck, title: "Human-in-the-loop", body: "Approvals are cryptographically bound to the exact run, step, version, actor and time window.", tag: "Role-gated" },
  { icon: Sparkles, title: "LLM steps you can trust", body: "Schema-validated structured output, injection-hardened prompts, and per-run cost accounting in micro-USD.", tag: "Guardrailed AI", span: "tall" },
  { icon: ShieldCheck, title: "SSRF-proof egress", body: "15 blocked network ranges, DNS-rebinding defense with IP pinning, strict port and host allowlists.", tag: "6/6 vectors blocked" },
  { icon: Wallet, title: "Budget guardrails", body: "Two-phase reservations under row locks. 20 concurrent requests, 15 000 µUSD budget — exactly 5 admitted.", tag: "Race-free" },
  { icon: Eye, title: "Observable end to end", body: "Prometheus metrics, OpenTelemetry traces across API → queue → worker, Grafana dashboards, 8 runbooks.", tag: "Traces · Metrics · Runbooks", span: "wide" },
  { icon: Lock, title: "Strict multi-tenancy", body: "Every query is org-scoped, enforced by static AST checks in CI and a BOLA test matrix.", tag: "Tenant-safe" },
];

function FeatureCard({ f }: { f: Feature }) {
  const ref = useSpotlight<HTMLDivElement>();
  return (
    <div ref={ref} className={`feature ${f.span ?? ""}`}>
      <div className="feature-glow" />
      <div className="feature-ico">
        <f.icon size={22} />
      </div>
      <h3>{f.title}</h3>
      <p>{f.body}</p>
      <span className="feature-tag">{f.tag}</span>
    </div>
  );
}

const STEPS = [
  { n: "01", icon: GitBranch, title: "Design", body: "Compose a versioned directed workflow — HTTP tools, LLM steps, conditions and approvals — validated for cycles and unsafe paths." },
  { n: "02", icon: Boxes, title: "Publish", body: "Publishing freezes an immutable, checksummed version. Runs pin to it forever; edits create a new one." },
  { n: "03", icon: Gauge, title: "Run", body: "Trigger by API, webhook or UI. State and events commit together; workers claim leases and heartbeat." },
  { n: "04", icon: LifeBuoy, title: "Recover", body: "Kill a worker mid-flight. The sweeper reclaims, the ledger skips what already happened, the run finishes." },
];

const DRILLS = [
  { icon: Workflow, title: "Kill the worker", result: "SUCCEEDED at epoch 2", detail: "Worker 1 SIGKILLed between step 1 and 2. Exactly 1 external call per step.", metric: "0 duplicate effects" },
  { icon: DatabaseBackup, title: "Restore the database", result: "0.354 s RTO", detail: "pg_dump → fresh DB → pg_restore. 15 tables, row-for-row parity, 0 orphans.", metric: "measured, not claimed" },
  { icon: ScanSearch, title: "Replay duplicate events", result: "Strict no-op", detail: "Re-delivering outbox events to a finished or cancelled run changes nothing.", metric: "idempotent consumers" },
  { icon: ShieldCheck, title: "Rebind the DNS", result: "Blocked", detail: "Decimal, hex, IPv6-mapped and rebinding SSRF vectors all rejected before any socket opens.", metric: "6 of 6 vectors" },
];

const SNIPPET_LINES: [string, string][] = [
  ["c", "# 1 · trigger a run — safe to retry, keyed by Idempotency-Key"],
  ["k", "curl -X POST https://api.flowforge.dev/v1/workflows/$WF/runs \\"],
  ["", '  -H "Authorization: Bearer $TOKEN" \\'],
  ["", '  -H "Idempotency-Key: refund-4812" \\'],
  ["", '  -d \'{"customer_id":"cus_123","amount":250}\''],
  ["c", ""],
  ["o", "← 202 Accepted"],
  ["o", '{ "run_id": "01a17519-…", "state": "QUEUED" }'],
];

function CodeShowcase() {
  const [copied, setCopied] = useState(false);
  const text = useMemo(() => SNIPPET_LINES.map((l) => l[1]).join("\n"), []);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      /* clipboard unavailable */
    }
  };
  return (
    <div className="code-card">
      <div className="code-bar">
        <span className="dot r" />
        <span className="dot y" />
        <span className="dot g" />
        <span className="code-name">quickstart.sh</span>
        <button className="copy-btn" onClick={copy} aria-label="Copy snippet">
          {copied ? <Check size={14} /> : <Copy size={14} />} {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre>
        {SNIPPET_LINES.map(([kind, line], i) => (
          <div key={i} className={`cl ${kind}`} style={{ animationDelay: `${i * 90}ms` }}>
            {line || "\u00a0"}
          </div>
        ))}
      </pre>
    </div>
  );
}

const TECH = ["PostgreSQL 16", "FastAPI", "RabbitMQ", "OpenTelemetry", "Prometheus", "React 19", "SQLAlchemy 2", "Alembic", "OpenRouter", "Argon2id", "Grafana", "Playwright"];

export function LandingPage() {
  const { user } = useAuth();
  const { navigate } = useRouter();
  const [scrolled, setScrolled] = useState(false);
  const word = useTypewriter(["crashes.", "retries.", "replays.", "outages.", "chaos."]);
  const heroRef = useSpotlight<HTMLElement>();

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 12);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const cta = () => navigate(user ? "/orgs" : "/signup");

  return (
    <div className="landing">
      <nav className={`lnav${scrolled ? " scrolled" : ""}`} aria-label="Main">
        <a className="lnav-brand" href="/" onClick={(e) => (e.preventDefault(), window.scrollTo({ top: 0, behavior: "smooth" }))}>
          <Logo size={30} />
          <span>FlowForge</span>
        </a>
        <div className="lnav-links">
          <a href="#features">Features</a>
          <a href="#how">How it works</a>
          <a href="#reliability">Reliability</a>
          <a href="#start">Quickstart</a>
        </div>
        <div className="lnav-cta">
          {user ? (
            <button className="btn" onClick={() => navigate("/orgs")}>
              Open dashboard <ArrowRight size={16} />
            </button>
          ) : (
            <>
              <button className="btn btn-ghost" onClick={() => navigate("/login")}>
                Log in
              </button>
              <button className="btn" onClick={() => navigate("/signup")}>
                Get started <ArrowRight size={16} />
              </button>
            </>
          )}
        </div>
      </nav>

      {/* ---------------- HERO ---------------- */}
      <header ref={heroRef} className="hero">
        <div className="orb orb-a" />
        <div className="orb orb-b" />
        <div className="orb orb-c" />
        <div className="hero-spot" />
        <div className="hero-grid">
          <div className="hero-copy">
            <div className="pill rise" style={{ animationDelay: "0.05s" }}>
              <span className="pill-dot" /> Durable AI workflow engine · open source
            </div>
            <h1 className="rise" style={{ animationDelay: "0.15s" }}>
              Automation that
              <br />
              survives <span className="grad-text typed">{word}</span>
              <span className="caret" />
            </h1>
            <p className="hero-sub rise" style={{ animationDelay: "0.3s" }}>
              Build versioned AI agent workflows with human approvals, tool calls and LLM steps — on an execution engine
              engineered so a crash can never lose a run or repeat a side effect.
            </p>
            <div className="hero-actions rise" style={{ animationDelay: "0.45s" }}>
              <button className="btn btn-lg" onClick={cta}>
                {user ? "Open dashboard" : "Start building free"} <ArrowRight size={18} />
              </button>
              <a className="btn btn-ghost btn-lg" href={REPO_URL} target="_blank" rel="noreferrer">
                View source
              </a>
            </div>
            <ul className="hero-trust rise" style={{ animationDelay: "0.6s" }}>
              <li><Check size={15} /> Exactly-once external effects</li>
              <li><Check size={15} /> Tenant-isolated by design</li>
              <li><Check size={15} /> 242 automated tests</li>
            </ul>
          </div>
          <div className="hero-visual rise" style={{ animationDelay: "0.35s" }}>
            <HeroDemo />
          </div>
        </div>
        <div className="scroll-hint" aria-hidden="true"><span /></div>
      </header>

      {/* ---------------- MARQUEE ---------------- */}
      <section className="marquee" aria-label="Built with">
        <div className="marquee-track">
          {[...TECH, ...TECH].map((t, i) => (
            <span key={i} className="chip">{t}</span>
          ))}
        </div>
      </section>

      {/* ---------------- STATS ---------------- */}
      <section className="section stats" aria-label="Measured results">
        <Reveal>
          <div className="stat-grid">
            <Stat value={0} label="Duplicate side effects" note="kill-worker drill, epoch 2 recovery" />
            <Stat value={0.354} decimals={3} suffix="s" label="Database restore RTO" note="pg_dump → pg_restore, 15 tables verified" />
            <Stat value={275} suffix="/s" label="Requests per second" note="50 concurrent clients · 0% errors" />
            <Stat value={242} label="Automated tests" note="unit · integration · security · e2e" />
          </div>
          <p className="fine">All figures measured on a single developer machine — reproducible with the scripts in <code>scripts/</code>.</p>
        </Reveal>
      </section>

      {/* ---------------- FEATURES ---------------- */}
      <section id="features" className="section">
        <Reveal>
          <div className="eyebrow">Capabilities</div>
          <h2 className="section-title">Everything an agent platform needs.<br /><span className="grad-text">Nothing you have to babysit.</span></h2>
          <p className="section-sub">Correctness lives in the database and the protocol — not in hope.</p>
        </Reveal>
        <div className="bento">
          {FEATURES.map((f, i) => (
            <Reveal key={f.title} delay={(i % 4) * 70} className={f.span ?? ""}>
              <FeatureCard f={f} />
            </Reveal>
          ))}
        </div>
      </section>

      {/* ---------------- HOW IT WORKS ---------------- */}
      <section id="how" className="section">
        <Reveal>
          <div className="eyebrow">How it works</div>
          <h2 className="section-title">From idea to resilient run <span className="grad-text">in four steps.</span></h2>
        </Reveal>
        <div className="steps">
          <div className="steps-line" />
          {STEPS.map((s, i) => (
            <Reveal key={s.n} delay={i * 110}>
              <div className="step">
                <div className="step-n">{s.n}</div>
                <div className="step-ico"><s.icon size={22} /></div>
                <h3>{s.title}</h3>
                <p>{s.body}</p>
              </div>
            </Reveal>
          ))}
        </div>
      </section>

      {/* ---------------- RELIABILITY ---------------- */}
      <section id="reliability" className="section">
        <Reveal>
          <div className="eyebrow">Proof, not promises</div>
          <h2 className="section-title">We broke it on purpose. <span className="grad-text">Here's what happened.</span></h2>
          <p className="section-sub">Every drill is a script you can run yourself, with its output recorded in the repo.</p>
        </Reveal>
        <div className="drills">
          {DRILLS.map((d, i) => (
            <Reveal key={d.title} delay={i * 90}>
              <div className="drill">
                <div className="drill-top">
                  <span className="drill-ico"><d.icon size={20} /></span>
                  <span className="drill-metric">{d.metric}</span>
                </div>
                <h3>{d.title}</h3>
                <div className="drill-result"><Check size={16} /> {d.result}</div>
                <p>{d.detail}</p>
              </div>
            </Reveal>
          ))}
        </div>
      </section>

      {/* ---------------- QUICKSTART ---------------- */}
      <section id="start" className="section split">
        <Reveal>
          <div className="eyebrow">Developer first</div>
          <h2 className="section-title left">One idempotent call.<br /><span className="grad-text">Any number of retries.</span></h2>
          <p className="section-sub left">
            A typed REST API with OpenAPI, RFC 9457 problem-details errors, keyset pagination and signed webhooks.
            Retry anything — the engine guarantees one effect.
          </p>
          <ul className="check-list">
            <li><Check size={16} /> OpenAPI-generated TypeScript client</li>
            <li><Check size={16} /> HMAC-SHA256 webhooks with replay protection</li>
            <li><Check size={16} /> Per-org budgets and rate limits</li>
          </ul>
        </Reveal>
        <Reveal delay={120}>
          <CodeShowcase />
        </Reveal>
      </section>

      {/* ---------------- CTA ---------------- */}
      <section className="section cta-wrap">
        <Reveal>
          <div className="cta">
            <div className="cta-glow" />
            <h2>Ship workflows you can <span className="grad-text">sleep through.</span></h2>
            <p>Create a workspace in under a minute. Free, open source, and honest about its limits.</p>
            <div className="hero-actions center">
              <button className="btn btn-lg" onClick={cta}>
                {user ? "Open dashboard" : "Create your workspace"} <ArrowRight size={18} />
              </button>
              <a className="btn btn-ghost btn-lg" href={`${REPO_URL}#readme`} target="_blank" rel="noreferrer">
                Read the docs
              </a>
            </div>
          </div>
        </Reveal>
      </section>

      <footer className="lfoot">
        <div className="lfoot-brand"><Logo size={24} animated={false} /> FlowForge</div>
        <div className="lfoot-links">
          <a href={REPO_URL} target="_blank" rel="noreferrer">GitHub</a>
          <a href={`${REPO_URL}/blob/master/docs/case-study.md`} target="_blank" rel="noreferrer">Case study</a>
          <a href={`${REPO_URL}/tree/master/docs/runbooks`} target="_blank" rel="noreferrer">Runbooks</a>
          <button onClick={() => navigate("/health")}>System status</button>
        </div>
        <p className="fine">
          A portfolio engineering project. Metrics shown are measured locally and are not claims of production traffic.
        </p>
      </footer>
    </div>
  );
}
