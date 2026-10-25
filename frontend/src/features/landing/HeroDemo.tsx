import { useEffect, useState } from "react";
import { Bot, CheckCheck, Globe, ShieldCheck, Webhook, Zap } from "lucide-react";
import type { ComponentType } from "react";

interface NodeDef {
  id: string;
  label: string;
  sub: string;
  x: number;
  y: number;
  icon: ComponentType<{ size?: number }>;
}

const NODES: NodeDef[] = [
  { id: "trigger", label: "Webhook", sub: "HMAC verified", x: 60, y: 60, icon: Webhook },
  { id: "classify", label: "Classify ticket", sub: "LLM · schema-guarded", x: 250, y: 150, icon: Bot },
  { id: "approve", label: "Human approval", sub: "bound to run + version", x: 60, y: 240, icon: ShieldCheck },
  { id: "charge", label: "POST /refunds", sub: "ledgered write", x: 250, y: 330, icon: Globe },
  { id: "done", label: "Succeeded", sub: "audited", x: 60, y: 420, icon: CheckCheck },
];

type NodeState = "idle" | "running" | "waiting" | "done" | "crashed";

interface Frame {
  states: NodeState[];
  edge: number; // index of active edge, -1 none
  log?: { tone: "ok" | "warn" | "err" | "info"; text: string };
}

const FRAMES: Frame[] = [
  { states: ["running", "idle", "idle", "idle", "idle"], edge: -1, log: { tone: "info", text: "run.created  QUEUED  epoch=0" } },
  { states: ["done", "running", "idle", "idle", "idle"], edge: 0, log: { tone: "ok", text: "outbox → worker-1 claimed lease  epoch=1" } },
  { states: ["done", "done", "waiting", "idle", "idle"], edge: 1, log: { tone: "warn", text: "WAITING_APPROVAL  refund > $200" } },
  { states: ["done", "done", "done", "running", "idle"], edge: 2, log: { tone: "ok", text: "approved by ops@acme  ✓ bound to version 3" } },
  { states: ["done", "done", "done", "crashed", "idle"], edge: -1, log: { tone: "err", text: "SIGKILL worker-1  ✕ lease abandoned" } },
  { states: ["done", "done", "done", "running", "idle"], edge: 2, log: { tone: "info", text: "sweeper reclaimed lease → worker-2  epoch=2" } },
  { states: ["done", "done", "done", "done", "idle"], edge: 3, log: { tone: "ok", text: "ledger COMMITTED → duplicate call skipped" } },
  { states: ["done", "done", "done", "done", "done"], edge: -1, log: { tone: "ok", text: "run SUCCEEDED · 1 external effect · 0 duplicates" } },
  { states: ["done", "done", "done", "done", "done"], edge: -1 },
];

const PATHS = [
  "M 60 60 C 60 105, 250 105, 250 150",
  "M 250 150 C 250 195, 60 195, 60 240",
  "M 60 240 C 60 285, 250 285, 250 330",
  "M 250 330 C 250 375, 60 375, 60 420",
];

export function HeroDemo() {
  const [frame, setFrame] = useState(0);
  useEffect(() => {
    const reduce = typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (reduce) {
      setFrame(FRAMES.length - 2);
      return;
    }
    const id = window.setInterval(() => setFrame((f) => (f + 1) % FRAMES.length), 1500);
    return () => window.clearInterval(id);
  }, []);

  const current = FRAMES[frame];
  const logs = FRAMES.slice(0, frame + 1)
    .filter((f) => f.log)
    .slice(-6);

  return (
    <div className="demo" aria-label="Animated demonstration of a workflow surviving a worker crash">
      <div className="demo-chrome">
        <span className="dot r" />
        <span className="dot y" />
        <span className="dot g" />
        <span className="demo-title">refund-flow · v3 · live run</span>
        <span className={`demo-status ${current.states.includes("crashed") ? "bad" : "good"}`}>
          {current.states.includes("crashed") ? "worker down" : "healthy"}
        </span>
      </div>
      <div className="demo-body">
        <svg viewBox="0 0 380 500" className="demo-graph" role="img" aria-hidden="true">
          <defs>
            <linearGradient id="edge-g" x1="0" y1="0" x2="1" y2="1">
              <stop stopColor="#22d3ee" />
              <stop offset="1" stopColor="#a855f7" />
            </linearGradient>
            <filter id="glow">
              <feGaussianBlur stdDeviation="3.5" result="b" />
              <feMerge>
                <feMergeNode in="b" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>
          {PATHS.map((d, i) => (
            <g key={i}>
              <path d={d} className="edge-base" />
              <path d={d} className={`edge-flow${current.edge === i ? " active" : ""}`} />
              {current.edge === i && (
                <circle r="5" fill="#fff" filter="url(#glow)">
                  <animateMotion dur="1.2s" repeatCount="1" path={d} fill="freeze" />
                </circle>
              )}
            </g>
          ))}
        </svg>
        {NODES.map((n, i) => {
          const st = current.states[i];
          return (
            <div key={n.id} className={`dnode ${st}`} style={{ left: `${(n.x / 380) * 100}%`, top: `${(n.y / 500) * 100}%` }}>
              <span className="dnode-ico">
                <n.icon size={18} />
              </span>
              <span className="dnode-txt">
                <b>{n.label}</b>
                <small>{n.sub}</small>
              </span>
              <span className="dnode-state">
                {st === "running" && <i className="spinner" />}
                {st === "done" && "✓"}
                {st === "waiting" && "⏸"}
                {st === "crashed" && "✕"}
              </span>
            </div>
          );
        })}
        {current.states.includes("crashed") && (
          <div className="boom" aria-hidden="true">
            <Zap size={16} /> SIGKILL
          </div>
        )}
      </div>
      <div className="demo-log" aria-live="off">
        {logs.map((f, i) => (
          <div key={`${frame}-${i}`} className={`log-line ${f.log?.tone}`} style={{ animationDelay: i === logs.length - 1 ? "0s" : "0s" }}>
            <span className="log-ts">{String(i).padStart(2, "0")}</span>
            {f.log?.text}
          </div>
        ))}
      </div>
    </div>
  );
}
