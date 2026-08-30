import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { PolicySummary } from "../types";
import { Loading } from "../components/ui";

export default function Policies() {
  const [policies, setPolicies] = useState<PolicySummary[] | null>(null);
  const [sel, setSel] = useState<string>("");
  const [detail, setDetail] = useState<any>(null);
  const [draft, setDraft] = useState("");
  const [msg, setMsg] = useState("");

  const load = () => api.policies().then((p) => { setPolicies(p); if (!sel && p[0]) setSel(p[0].workflow); });
  useEffect(() => { load(); }, []);
  useEffect(() => {
    if (!sel) return;
    api.policy(sel).then((d) => { setDetail(d); setDraft(JSON.stringify(d.active.body, null, 2)); setMsg(""); });
  }, [sel]);

  async function save() {
    try {
      const body = JSON.parse(draft);
      const r = await api.updatePolicy(sel, body, "edited from dashboard");
      setMsg(`Saved as version ${r.new_version}. Existing traces keep the version they were evaluated under.`);
      api.policy(sel).then(setDetail);
      load();
    } catch (e: any) { setMsg("Invalid JSON or save failed: " + e); }
  }

  if (!policies) return <Loading />;

  return (
    <>
      <div className="page-head">
        <div><h2>Policies</h2><div className="sub">Versioned per workflow. Editing creates a new version; a trace preserves the version it ran under.</div></div>
      </div>

      <div className="card" style={{ padding: 0, marginBottom: 14 }}>
        <table>
          <thead><tr><th>Workflow</th><th>Policy</th><th>Version</th><th>Risk class</th><th>Latency budget</th><th>Cost budget</th><th>Verify threshold</th></tr></thead>
          <tbody>
            {policies.map((p) => (
              <tr key={p.workflow} className="row-click" onClick={() => setSel(p.workflow)}
                style={{ background: sel === p.workflow ? "var(--accent-dim)" : undefined }}>
                <td><b>{p.workflow}</b></td><td className="small">{p.name}</td>
                <td><span className="tag">v{p.version}</span></td>
                <td>{p.risk_class}</td><td>{p.latency_budget_ms} ms</td><td>${p.cost_budget_usd}</td>
                <td className="mono small">{p.routing?.verify_value_threshold}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {detail && (
        <div className="grid" style={{ gridTemplateColumns: "1.3fr 1fr" }}>
          <div className="card">
            <h3>Edit — {sel}</h3>
            <textarea rows={22} className="mono" value={draft} onChange={(e) => setDraft(e.target.value)} style={{ fontSize: 12 }} />
            <div className="spread" style={{ marginTop: 10 }}>
              <span className="small muted">Active version: v{detail.active.version}</span>
              <button className="btn" onClick={save}>Save as new version</button>
            </div>
            {msg && <div className="callout" style={{ marginTop: 10 }}>{msg}</div>}
          </div>
          <div className="card">
            <h3>Version history</h3>
            <table>
              <thead><tr><th>Version</th><th>Source</th><th>Active</th></tr></thead>
              <tbody>
                {detail.versions.map((v: any) => (
                  <tr key={v.id}><td><span className="tag">v{v.version}</span></td><td className="small">{v.source}</td>
                    <td>{v.active ? <span className="badge b-green">active</span> : <span className="muted small">—</span>}</td></tr>
                ))}
              </tbody>
            </table>
            <h3 style={{ marginTop: 16 }}>Threshold trade-off (§48)</h3>
            <p className="small muted">
              Lower <span className="mono">verify_value_threshold</span> / <span className="mono">fast_path_below</span> →
              more deep checks, more false positives. Raise them → fewer alerts, more missed risk.
              Tune per workflow, then re-run the benchmark to see the effect on recall vs overhead.
            </p>
          </div>
        </div>
      )}
    </>
  );
}
