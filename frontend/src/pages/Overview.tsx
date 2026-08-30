import { useEffect, useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from "recharts";
import { api } from "../api/client";
import type { Overview as OverviewT } from "../types";
import DemoBar from "../components/DemoBar";
import { Kpi, Loading } from "../components/ui";

const ACTION_COLORS: Record<string, string> = {
  ALLOW: "#2e7d4f", MONITOR: "#9a6a00", VERIFY: "#9a6a00", MODIFY: "#b5531b",
  SAFE_FALLBACK: "#b5531b", HUMAN_REVIEW: "#b3261e", BLOCK: "#b3261e", STOP_EXECUTION: "#b3261e",
};

export default function Overview() {
  const [ov, setOv] = useState<OverviewT | null>(null);
  const [err, setErr] = useState("");
  const [seeding, setSeeding] = useState(false);

  const load = () => api.overview().then(setOv).catch((e) => setErr(String(e)));
  useEffect(() => { load(); }, []);

  async function seed() {
    setSeeding(true);
    try { await api.seed(1200); await load(); } finally { setSeeding(false); }
  }

  if (err) return <div className="callout warn">Could not reach the API. Is the backend running on :8000?<br /><span className="mono small">{err}</span></div>;
  if (!ov) return <Loading />;

  if (ov.total_interactions === 0) {
    return (
      <>
        <div className="page-head"><h2>ControlPlane Overview</h2></div>
        <div className="callout">
          No traces yet. <button className="btn small" onClick={seed} disabled={seeding}>
            {seeding ? "Seeding…" : "Seed synthetic demo data"}</button> or run a scenario below.
        </div>
        <div style={{ height: 16 }} />
        <DemoBar />
      </>
    );
  }

  const interventions = Object.entries(ov.interventions_by_type).map(([name, value]) => ({ name, value }));
  const risk = [
    { name: "Performance", value: ov.risk_distribution.performance },
    { name: "Cost", value: ov.risk_distribution.cost },
    { name: "Responsibility", value: ov.risk_distribution.responsibility },
  ];

  return (
    <>
      <div className="page-head">
        <div><h2>ControlPlane Overview</h2><div className="sub">Synthetic prototype data — decisions computed live by the risk engine.</div></div>
        <button className="btn secondary small" onClick={seed} disabled={seeding}>{seeding ? "Seeding…" : "Re-seed demo data"}</button>
      </div>

      <DemoBar />

      <div className="grid kpi-grid" style={{ marginBottom: 16 }}>
        <Kpi label="Total AI interactions" value={ov.total_interactions.toLocaleString()} />
        <Kpi label="Fast-path rate" value={`${(ov.fast_path_rate * 100).toFixed(1)}%`} hint="no deep evaluation needed" />
        <Kpi label="Deep-evaluation rate" value={`${(ov.deep_evaluation_rate * 100).toFixed(1)}%`} hint="Tier 2 invoked" />
        <Kpi label="High-risk interventions" value={ov.high_risk_interventions} hint="block / stop / human / fallback" />
        <Kpi label="Estimated spend" value={`$${ov.estimated_spend_usd.toFixed(2)}`} hint="simulated model+tool cost" />
        <Kpi label="Prevented runaway spend" value={`$${ov.prevented_runaway_spend_usd.toFixed(2)}`} hint="simulated, stopped agents" />
        <Kpi label="Avg fast-path overhead" value={`${ov.avg_fast_path_overhead_ms.toFixed(2)} ms`} hint={`p95 ${ov.p95_fast_path_overhead_ms.toFixed(2)} ms`} />
        <Kpi label="Async deep evaluations" value={ov.async_deep_evaluations} hint="off the response path" />
      </div>

      <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", marginBottom: 16 }}>
        <div className="card">
          <h3>Mean risk by dimension</h3>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={risk}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="name" tick={{ fontSize: 12 }} /><YAxis domain={[0, 1]} tick={{ fontSize: 12 }} />
              <Tooltip />
              <Bar dataKey="value" radius={[4, 4, 0, 0]} fill="#2f5bd4" />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="card">
          <h3>Interventions by type</h3>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={interventions} layout="vertical" margin={{ left: 24 }}>
              <CartesianGrid strokeDasharray="3 3" horizontal={false} />
              <XAxis type="number" tick={{ fontSize: 12 }} /><YAxis type="category" dataKey="name" width={110} tick={{ fontSize: 11 }} />
              <Tooltip />
              <Bar dataKey="value" radius={[0, 4, 4, 0]}>
                {interventions.map((d) => <Cell key={d.name} fill={ACTION_COLORS[d.name] ?? "#8a929e"} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="card">
        <h3>Risk & deep-check rate over time</h3>
        <ResponsiveContainer width="100%" height={240}>
          <LineChart data={ov.timeseries}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="bucket" tick={{ fontSize: 12 }} /><YAxis domain={[0, 1]} tick={{ fontSize: 12 }} />
            <Tooltip /><Legend />
            <Line type="monotone" dataKey="mean_performance_risk" stroke="#2f5bd4" dot={false} name="performance risk" />
            <Line type="monotone" dataKey="mean_responsibility_risk" stroke="#b3261e" dot={false} name="responsibility risk" />
            <Line type="monotone" dataKey="mean_cost_risk" stroke="#9a6a00" dot={false} name="cost risk" />
            <Line type="monotone" dataKey="deep_check_rate" stroke="#2e7d4f" strokeDasharray="4 3" dot={false} name="deep-check rate" />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </>
  );
}
