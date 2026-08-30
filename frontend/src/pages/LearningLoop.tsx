import { useEffect, useState } from "react";
import {
  CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { api } from "../api/client";
import { Kpi, Loading } from "../components/ui";

export default function LearningLoop() {
  const [s, setS] = useState<any>(null);
  useEffect(() => { api.learning().then(setS).catch(() => {}); }, []);
  if (!s) return <Loading />;

  const le = s.learning_effect;

  return (
    <>
      <div className="page-head">
        <div><h2>Learning Loop</h2><div className="sub">Validated outcomes improve the checker — not the underlying model. All data synthetic.</div></div>
      </div>

      <div className="grid kpi-grid" style={{ marginBottom: 16 }}>
        <Kpi label="Feedback received" value={s.feedback_received} />
        <Kpi label="Cases pending" value={s.cases_pending} />
        <Kpi label="Cases validated" value={s.cases_validated} />
        <Kpi label="Validated failures" value={s.validated_failures} />
        <Kpi label="False positives" value={s.false_positives} hint="cool down patterns" />
        <Kpi label="Candidate patterns" value={s.candidate_patterns} />
        <Kpi label="Trusted patterns" value={s.trusted_patterns} hint="influence routing" />
        <Kpi label="Golden cases" value={s.golden_cases} hint="quality baseline anchors" />
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <h3>Evidence pipeline</h3>
        <div className="pill-row" style={{ fontSize: 13 }}>
          <span className="badge b-grey">raw feedback ({s.feedback_received})</span> →
          <span className="badge b-yellow">pending validation ({s.cases_pending})</span> →
          <span className="badge b-green">validated evidence ({s.cases_validated})</span> →
          <span className="badge b-orange">trusted failure patterns ({s.trusted_patterns})</span> →
          <span className="badge b-red">changed routing</span>
        </div>
        <p className="small muted" style={{ marginTop: 8 }}>
          Raw user feedback can never modify critical behaviour on its own. A pattern is promoted to
          <i> trusted</i> only after human or authoritative validation (§49).
        </p>
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <h3>Deep-check rate over time</h3>
        <ResponsiveContainer width="100%" height={240}>
          <LineChart data={s.deep_check_rate_over_time}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="bucket" tick={{ fontSize: 12 }} /><YAxis domain={[0, 1]} tick={{ fontSize: 12 }} />
            <Tooltip />
            <Line type="monotone" dataKey="deep_check_rate" stroke="#2f5bd4" dot={false} name="deep-check rate" />
            <Line type="monotone" dataKey="intervention_rate" stroke="#b3261e" strokeDasharray="4 3" dot={false} name="intervention rate" />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {le && (
        <div className="card">
          <h3>Learning effect (from the benchmark simulation)</h3>
          <div className="grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
            <Kpi label="Deep-check rate — before validated patterns"
              value={`${(le.before.deep_check_rate * 100).toFixed(1)}%`} hint={`recall ${le.before.recall}`} />
            <Kpi label="Deep-check rate — after validated patterns"
              value={`${(le.after.deep_check_rate * 100).toFixed(1)}%`} hint={`recall ${le.after.recall}`} />
          </div>
          <p className="small muted" style={{ marginTop: 8 }}>{le.note}</p>
        </div>
      )}
    </>
  );
}
