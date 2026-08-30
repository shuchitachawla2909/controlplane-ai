import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";

/** DEMO MODE (§84): one-click curated scenarios. The real engine processes each. */
export default function DemoBar() {
  const [scenarios, setScenarios] = useState<any[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string>("");
  const nav = useNavigate();

  useEffect(() => { api.scenarios().then(setScenarios).catch(() => {}); }, []);

  async function run(key: string) {
    setBusy(key); setMsg("");
    try {
      const r = await api.runScenario(key);
      if (r.multi_turn) {
        const last = r.turns[r.turns.length - 1];
        setMsg(`Scenario ${key}: final action ${last.action} (risk propagated across ${r.turns.length} turns)`);
      } else {
        setMsg(`Scenario ${key}: ${r.decision.action} — ${r.decision.what_we_did}`);
        nav(`/trace/${r.trace_id}`);
      }
    } catch (e: any) { setMsg(String(e)); }
    finally { setBusy(null); }
  }

  return (
    <div className="demobar">
      <h3>Demo mode · curated scenarios (processed live by the risk engine)</h3>
      <div className="pill-row">
        {scenarios.map((s) => (
          <button key={s.key} className="scenario-btn" disabled={!!busy} onClick={() => run(s.key)}>
            <b>{busy === s.key ? "Running…" : `${s.key}. ${s.title}`}</b>
            <span>{s.summary}</span>
          </button>
        ))}
      </div>
      {msg && <div style={{ marginTop: 10, fontSize: 13 }}>{msg}</div>}
    </div>
  );
}
