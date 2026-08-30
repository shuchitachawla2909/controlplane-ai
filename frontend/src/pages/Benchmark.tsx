import { useEffect, useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { api } from "../api/client";
import type { BenchmarkRun } from "../types";
import { Kpi, Loading } from "../components/ui";

const ARMS = [
  ["A_no_checker", "A · No checker"],
  ["B_always_deep", "B · Always deep"],
  ["C_controlplane", "C · ControlPlane"],
] as const;

export default function Benchmark() {
  const [runs, setRuns] = useState<BenchmarkRun[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [count, setCount] = useState(1500);
  const [sim, setSim] = useState(0);

  const load = () => api.benchmarkResults().then(setRuns).catch(() => setRuns([]));
  useEffect(() => { load(); }, []);

  async function run() {
    setBusy(true);
    try { await api.runBenchmark(count, "mixed", sim); await load(); } finally { setBusy(false); }
  }

  if (!runs) return <Loading />;
  const latest = runs[0] as any;
  const p = latest?.params ?? {};
  const structural = p.structural;
  const runtime = p.runtime_local;
  const simCost = p.simulated_cost;
  const A = structural?.A_no_checker ?? latest?.arms?.A_no_checker;
  const B = structural?.B_always_deep ?? latest?.arms?.B_always_deep;
  const C = structural?.C_controlplane ?? latest?.arms?.C_controlplane;

  return (
    <>
      <div className="page-head">
        <div><h2>Performance Benchmark</h2><div className="sub">no-checker vs always-deep vs ControlPlane · synthetic ground truth · results split into structural / measured-local / simulated-cost</div></div>
        <div className="pill-row">
          <select value={count} onChange={(e) => setCount(Number(e.target.value))} style={{ width: 110 }}>
            {[500, 1000, 1500, 3000].map((n) => <option key={n} value={n}>{n} traces</option>)}
          </select>
          <select value={sim} onChange={(e) => setSim(Number(e.target.value))} style={{ width: 190 }} title="illustrative deep-path latency">
            {[0, 150, 300, 800].map((n) => <option key={n} value={n}>{n === 0 ? "no sim deep latency" : `+${n}ms sim deep path`}</option>)}
          </select>
          <button className="btn" onClick={run} disabled={busy}>{busy ? "Running…" : "Run benchmark"}</button>
        </div>
      </div>

      {!latest ? (
        <div className="callout">No benchmark runs yet. Click “Run benchmark”. A 1,500-trace run takes a few seconds.</div>
      ) : (
        <>
          {/* ---------- Tier 1: structural ---------- */}
          <div className="card" style={{ marginBottom: 16 }}>
            <h3>Structural metrics — deterministic, machine-independent (the headline)</h3>
            <div className="grid kpi-grid" style={{ marginBottom: 12 }}>
              <Kpi label="ControlPlane fast-path rate" value={`${((C?.fast_path_pct ?? 0) * 100).toFixed(1)}%`} />
              <Kpi label="ControlPlane deep-eval rate" value={`${((C?.deep_eval_pct ?? 0) * 100).toFixed(1)}%`} />
              <Kpi label="Recall retained vs always-deep"
                value={structural?.recall_retained_vs_always_deep != null ? `${(structural.recall_retained_vs_always_deep * 100).toFixed(0)}%` : "—"} />
              <Kpi label="FPR vs always-deep" value={C ? C.false_positive_rate : "—"}
                hint={B ? `always-deep: ${B.false_positive_rate}` : ""} />
            </div>
            <table>
              <thead><tr><th>Metric</th>{ARMS.map(([k, l]) => <th key={k}>{l}</th>)}</tr></thead>
              <tbody>
                {[
                  ["recall", (a: any) => a?.recall],
                  ["precision", (a: any) => a?.precision],
                  ["false positive rate", (a: any) => a?.false_positive_rate],
                  ["false negatives", (a: any) => a?.false_negatives],
                  ["fast-path %", (a: any) => ((a?.fast_path_pct ?? 0) * 100).toFixed(1) + "%"],
                  ["deep-eval %", (a: any) => ((a?.deep_eval_pct ?? 0) * 100).toFixed(1) + "%"],
                  ["intervention %", (a: any) => ((a?.intervention_pct ?? 0) * 100).toFixed(1) + "%"],
                ].map(([label, get]: any) => (
                  <tr key={label}>
                    <td>{label}</td>
                    {[A, B, C].map((arm, i) => <td key={i} className="mono small right">{String(get(arm))}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
            {structural?.uncertainty_handling && (
              <p className="small muted" style={{ marginTop: 8 }}>
                No-ground-truth handling: {structural.uncertainty_handling.no_ground_truth_cases} cases ·
                confidence lowered {structural.uncertainty_handling.confidence_lowered_rate} ·
                high-impact escalated {structural.uncertainty_handling.high_impact_escalated_rate}
              </p>
            )}
          </div>

          <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", marginBottom: 16 }}>
            <div className="card">
              <h3>Deep-eval % by arm</h3>
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={[A, B, C].map((a, i) => ({ name: ARMS[i][1], v: (a?.deep_eval_pct ?? 0) }))}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="name" tick={{ fontSize: 11 }} /><YAxis domain={[0, 1]} tick={{ fontSize: 12 }} /><Tooltip />
                  <Bar dataKey="v" radius={[4, 4, 0, 0]}><Cell fill="#8a929e" /><Cell fill="#b3261e" /><Cell fill="#2e7d4f" /></Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="card">
              <h3>Recall by arm</h3>
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={[A, B, C].map((a, i) => ({ name: ARMS[i][1], v: (a?.recall ?? 0) }))}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="name" tick={{ fontSize: 11 }} /><YAxis domain={[0, 1]} tick={{ fontSize: 12 }} /><Tooltip />
                  <Bar dataKey="v" radius={[4, 4, 0, 0]}><Cell fill="#8a929e" /><Cell fill="#b3261e" /><Cell fill="#2e7d4f" /></Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* ---------- Tier 2: measured local runtime ---------- */}
          {runtime && (
            <div className="card" style={{ marginBottom: 16 }}>
              <h3>Measured local runtime — this machine, mock evaluators (not portable)</h3>
              <p className="small muted">{runtime.note}</p>
              <table>
                <thead><tr><th>Metric</th><th>B: always deep</th><th>C: ControlPlane</th></tr></thead>
                <tbody>
                  <tr><td>measured p50 overhead ms</td><td className="mono small right">{runtime.B_always_deep.measured_p50_overhead_ms}</td><td className="mono small right">{runtime.C_controlplane.measured_p50_overhead_ms}</td></tr>
                  <tr><td>measured p95 overhead ms</td><td className="mono small right">{runtime.B_always_deep.measured_p95_overhead_ms}</td><td className="mono small right">{runtime.C_controlplane.measured_p95_overhead_ms}</td></tr>
                  <tr><td>p95 with +{p.deep_eval_sim_latency_ms ?? 0}ms sim deep path</td><td className="mono small right">{runtime.B_always_deep.illustrative_p95_with_sim_deep_latency_ms}</td><td className="mono small right">{runtime.C_controlplane.illustrative_p95_with_sim_deep_latency_ms}</td></tr>
                </tbody>
              </table>
              <p className="small muted" style={{ marginTop: 6 }}>{runtime.expected_added_latency_formula}</p>
            </div>
          )}

          {/* ---------- Tier 3: simulated cost ---------- */}
          {simCost && (
            <div className="card" style={{ marginBottom: 16 }}>
              <h3>Simulated cost — synthetic compute-unit model (NOT dollars)</h3>
              <p className="small muted">{simCost.note}</p>
              <p className="small">
                mean checker cost/request: always-deep ${Number(simCost.B_always_deep.mean_checker_cost_usd).toExponential(2)} ·
                ControlPlane ${Number(simCost.C_controlplane.mean_checker_cost_usd).toExponential(2)} ·
                checker-work reduction <b>{simCost.checker_work_reduction_vs_always_deep}</b> (depends on assigned cost_units)
              </p>
            </div>
          )}

          <div className="callout">
            <b>Safe claim:</b> {latest.north_star?.claim ??
              "ControlPlane reduces unnecessary deep verification while retaining comparable detection coverage in this controlled benchmark."}
          </div>
        </>
      )}
    </>
  );
}
