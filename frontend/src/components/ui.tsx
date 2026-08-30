import { ReactNode } from "react";

export function Kpi({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="card kpi">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {hint && <div className="hint">{hint}</div>}
    </div>
  );
}

const ACTION_CLASS: Record<string, string> = {
  ALLOW: "b-green", MONITOR: "b-yellow", VERIFY: "b-yellow", MODIFY: "b-orange",
  SAFE_FALLBACK: "b-orange", HUMAN_REVIEW: "b-red", BLOCK: "b-red", STOP_EXECUTION: "b-red",
};
const SEV_CLASS: Record<string, string> = {
  none: "b-grey", low: "b-green", medium: "b-yellow", high: "b-orange", critical: "b-red",
};

export function ActionBadge({ action }: { action: string }) {
  return <span className={`badge ${ACTION_CLASS[action] ?? "b-grey"}`}>{action.replace("_", " ")}</span>;
}
export function SeverityBadge({ severity }: { severity: string }) {
  return <span className={`badge ${SEV_CLASS[severity] ?? "b-grey"}`}>{severity}</span>;
}
export function TierBadge({ tier }: { tier: number }) {
  const c = tier >= 2 ? "b-orange" : "b-green";
  return <span className={`badge ${c}`}>{tier >= 2 ? "DEEP" : "FAST"} · T{tier}</span>;
}

export function RiskBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color = value >= 0.75 ? "var(--red)" : value >= 0.5 ? "var(--orange)"
    : value >= 0.25 ? "var(--yellow)" : "var(--green)";
  return (
    <div className="riskbar" title={`${pct}%`}>
      <span style={{ width: `${Math.max(2, pct)}%`, background: color }} />
    </div>
  );
}

export function DimRow({ label, risk, confidence }: { label: string; risk: number; confidence?: number }) {
  return (
    <div className="dimrow">
      <div>{label}</div>
      <RiskBar value={risk} />
      <div className="num">
        {(risk * 100).toFixed(0)}%{confidence !== undefined && <span className="muted"> · c{(confidence * 100).toFixed(0)}</span>}
      </div>
    </div>
  );
}

export function Loading() {
  return <div className="loading">Loading…</div>;
}

export function useTimeFmt() {
  return (t: number) => new Date(t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}
