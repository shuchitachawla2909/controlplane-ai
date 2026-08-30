import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { DecisionRow } from "../types";
import { ActionBadge, Loading, SeverityBadge, TierBadge, useTimeFmt } from "../components/ui";

export default function LiveMonitor() {
  const [rows, setRows] = useState<DecisionRow[] | null>(null);
  const [workflow, setWorkflow] = useState("");
  const [action, setAction] = useState("");
  const [auto, setAuto] = useState(true);
  const nav = useNavigate();
  const fmt = useTimeFmt();

  const load = () => api.traces({ workflow, action, limit: 120 }).then(setRows).catch(() => {});
  useEffect(() => { load(); }, [workflow, action]);
  useEffect(() => {
    if (!auto) return;
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, [auto, workflow, action]);

  return (
    <>
      <div className="page-head">
        <div><h2>Live Monitor</h2><div className="sub">Every observed AI execution and the action ControlPlane took.</div></div>
        <label className="small muted"><input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} style={{ width: "auto" }} /> auto-refresh</label>
      </div>

      <div className="card" style={{ marginBottom: 12 }}>
        <div className="pill-row">
          <select value={workflow} onChange={(e) => setWorkflow(e.target.value)} style={{ width: 220 }}>
            <option value="">all workflows</option>
            <option value="customer_support">customer_support</option>
            <option value="internal_assistant">internal_assistant</option>
            <option value="decision_support">decision_support</option>
            <option value="agent_operations">agent_operations</option>
          </select>
          <select value={action} onChange={(e) => setAction(e.target.value)} style={{ width: 200 }}>
            <option value="">all actions</option>
            {["ALLOW", "MONITOR", "VERIFY", "MODIFY", "SAFE_FALLBACK", "HUMAN_REVIEW", "BLOCK", "STOP_EXECUTION"].map((a) =>
              <option key={a} value={a}>{a}</option>)}
          </select>
        </div>
      </div>

      {!rows ? <Loading /> : (
        <div className="card" style={{ padding: 0 }}>
          <table>
            <thead>
              <tr>
                <th>Time</th><th>Application</th><th>Workflow</th><th>Tier</th>
                <th>Perf</th><th>Cost</th><th>Resp</th><th>Conf</th><th>Action</th><th>Overhead</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.decision_id} className="row-click" onClick={() => nav(`/trace/${r.trace_id}`)}>
                  <td className="mono small">{fmt(r.created_at)}</td>
                  <td>{r.application}</td>
                  <td className="small muted">{r.workflow}</td>
                  <td><TierBadge tier={r.tier} /></td>
                  <td className="right mono small">{(r.performance_risk * 100).toFixed(0)}</td>
                  <td className="right mono small">{(r.cost_risk * 100).toFixed(0)}</td>
                  <td className="right mono small">{(r.responsibility_risk * 100).toFixed(0)}</td>
                  <td className="right mono small">{(r.evidence_confidence * 100).toFixed(0)}</td>
                  <td><ActionBadge action={r.action} /> {!r.synchronous && <span className="tag">async</span>}</td>
                  <td className="right mono small">{r.controlplane_overhead_ms.toFixed(2)} ms</td>
                </tr>
              ))}
              {rows.length === 0 && <tr><td colSpan={10} className="muted" style={{ padding: 20 }}>No matching traces.</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
