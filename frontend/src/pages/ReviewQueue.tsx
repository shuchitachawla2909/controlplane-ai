import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { ReviewCase } from "../types";
import { ActionBadge, Loading } from "../components/ui";

const VERDICTS = ["correct", "incorrect", "unsafe", "privacy_issue", "biased", "cost_issue", "false_positive", "other"];

export default function ReviewQueue() {
  const [cases, setCases] = useState<ReviewCase[] | null>(null);
  const [status, setStatus] = useState("pending");
  const [comment, setComment] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState("");

  const load = () => api.reviewQueue(status).then(setCases).catch(() => {});
  useEffect(() => { load(); }, [status]);

  async function submit(caseId: string, verdict: string) {
    const r = await api.submitReview(caseId, verdict, comment[caseId] ?? "");
    setMsg(r.pattern
      ? `Validated. Trusted failure pattern "${r.pattern}" is now ${r.pattern_status} and will influence routing of similar traces.`
      : `Validated as ${verdict}.`);
    load();
  }

  return (
    <>
      <div className="page-head">
        <div><h2>Review Queue</h2><div className="sub">Raw feedback → pending validation → validated evidence (feeds the learning loop).</div></div>
        <select value={status} onChange={(e) => setStatus(e.target.value)} style={{ width: 160 }}>
          <option value="pending">pending</option><option value="validated">validated</option>
          <option value="dismissed">dismissed</option><option value="all">all</option>
        </select>
      </div>

      {msg && <div className="callout" style={{ marginBottom: 12 }}>{msg}</div>}
      {!cases ? <Loading /> : cases.length === 0 ? (
        <div className="callout">Nothing in the queue. Submit 👎 feedback on a trace, or run demo scenario B/C/F.</div>
      ) : (
        <div className="stack">
          {cases.map((c) => (
            <div className="card" key={c.case_id}>
              <div className="spread">
                <div><b>{c.workflow}</b> · <span className="muted small">{c.reason}</span></div>
                <div className="pill-row">
                  {c.action && <ActionBadge action={c.action} />}
                  {c.overall_risk != null && <span className="tag">risk {(c.overall_risk * 100).toFixed(0)}%</span>}
                  <span className={`badge ${c.status === "pending" ? "b-yellow" : "b-green"}`}>{c.status}</span>
                </div>
              </div>
              <div className="small muted" style={{ margin: "8px 0" }}>
                <div><b>Q:</b> {c.request_preview}</div>
                <div><b>A:</b> {c.response_preview}</div>
                <Link to={`/trace/${c.trace_id}`} className="small">open trace →</Link>
              </div>
              {c.status === "pending" && (
                <>
                  <textarea placeholder="reviewer note / corrected answer (optional)" rows={2}
                    value={comment[c.case_id] ?? ""} onChange={(e) => setComment({ ...comment, [c.case_id]: e.target.value })} />
                  <div className="pill-row" style={{ marginTop: 8 }}>
                    {VERDICTS.map((v) => (
                      <button key={v} className="btn small secondary" onClick={() => submit(c.case_id, v)}>{v.replace("_", " ")}</button>
                    ))}
                  </div>
                </>
              )}
              {c.validator_verdict && <div className="small">verdict: <b>{c.validator_verdict}</b></div>}
            </div>
          ))}
        </div>
      )}
    </>
  );
}
