import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import type { TraceDetail as TraceDetailT } from "../types";
import { ActionBadge, DimRow, Loading, SeverityBadge, TierBadge, useTimeFmt } from "../components/ui";

function mark(kind: string, supports: boolean) {
  if (kind === "no_ground_truth") return <span className="mark q">?</span>;
  return supports ? <span className="mark ok">✓</span> : <span className="mark cross">✗</span>;
}

export default function TraceDetail() {
  const { id } = useParams();
  const [d, setD] = useState<TraceDetailT | null>(null);
  const [err, setErr] = useState("");
  const [fb, setFb] = useState("");
  const fmt = useTimeFmt();

  const load = () => api.trace(id!).then(setD).catch((e) => setErr(String(e)));
  useEffect(() => { load(); }, [id]);

  if (err) return <div className="callout warn">{err}</div>;
  if (!d) return <Loading />;
  const t = d.trace;
  const dec = d.decision;

  const detectedEntities: string[] = Array.from(
    new Set(
      (dec?.findings ?? [])
        .filter((f) => f.dimension === "responsibility")
        .flatMap((f) => f.evidence ?? [])
        .map((e) => (e.detail || "").match(/^[A-Z_]{3,}/)?.[0] ?? "")
        .filter(Boolean),
    ),
  );

  async function sendFeedback(thumbs: "up" | "down") {
    await api.feedback(t.trace_id, thumbs, thumbs === "down" ? "incorrect" : "");
    setFb(`Feedback recorded as evidence (trust: raw_feedback). It cannot change critical behaviour on its own.`);
  }

  return (
    <>
      <div className="page-head">
        <div><h2>Trace detail</h2><div className="sub mono">{t.trace_id}</div></div>
        {dec && <div className="pill-row"><TierBadge tier={dec.tier} /><ActionBadge action={dec.action} /></div>}
      </div>

      <div className="stack">
        <div className="card">
          <h3>Trace metadata</h3>
          <dl className="kv">
            <dt>Workflow</dt><dd>{t.workflow} <span className="muted">({t.application})</span></dd>
            <dt>Model / provider</dt><dd>{t.model} · {t.provider}</dd>
            <dt>Policy</dt><dd>{dec?.policy_name} <span className="tag">v{dec?.policy_version}</span></dd>
            <dt>Session</dt><dd className="mono small">{t.session_id} · turn {t.turn_index}</dd>
            <dt>Timestamp</dt><dd>{fmt(t.created_at)}</dd>
            <dt>Latency</dt><dd>{t.latency_ms.toFixed(0)} ms</dd>
            <dt>Estimated cost</dt><dd>${t.estimated_cost_usd.toFixed(4)}</dd>
            <dt>Calls</dt><dd>{t.model_calls} model · {t.tool_calls} tool · {t.retrieval_events} retrieval · {t.retries} retries</dd>
            <dt>Ground truth</dt><dd>{String(t.ground_truth_available)}</dd>
          </dl>
        </div>

        <div className="grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
          <div className="card">
            <h3>Execution path</h3>
            <div className="tree">
              <div className="step final">User request<div className="muted">{t.request_preview}</div></div>
              {t.steps.map((s) => (
                <div key={s.step_id} className={`step ${s.type.replace("_call", "").replace("final_response", "final")}`}>
                  {s.type} {s.name ? `· ${s.name}` : ""} {s.tool_name ? `· ${s.tool_name}` : ""}
                  <div className="muted">
                    {s.duration_ms.toFixed(0)}ms · ${s.cost_usd.toFixed(4)}
                    {s.cumulative_cost_usd ? ` · cum $${s.cumulative_cost_usd.toFixed(4)}` : ""}
                    {s.retries ? ` · ${s.retries} retr` : ""}
                    {s.risk_signals?.length ? ` · ⚠ ${s.risk_signals.join(",")}` : ""}
                  </div>
                </div>
              ))}
              <div className="step final">Final response<div className="muted">{t.response_preview}</div></div>
            </div>
          </div>

          <div className="card">
            <h3>Risk panel (components always shown)</h3>
            {dec && <>
              <DimRow label="Performance" risk={dec.performance_risk} confidence={dec.performance_confidence} />
              <DimRow label="Cost" risk={dec.cost_risk} confidence={dec.cost_confidence} />
              <DimRow label="Responsibility" risk={dec.responsibility_risk} confidence={dec.responsibility_confidence} />
              <div className="dimrow" style={{ marginTop: 12 }}>
                <div><b>Overall</b></div>
                <div />
                <div className="num"><b>{(dec.overall_risk * 100).toFixed(0)}%</b></div>
              </div>
              <div className="kv small" style={{ marginTop: 8 }}>
                <dt>Severity</dt><dd><SeverityBadge severity={dec.severity} /></dd>
                <dt>Impact</dt><dd>{dec.impact}</dd>
                <dt>Novelty</dt><dd>{(dec.novelty * 100).toFixed(0)}%</dd>
                <dt>Verification value</dt><dd>{dec.verification_value.toFixed(2)}</dd>
                <dt>Tiers run</dt><dd>{dec.tiers_run.join(" → ")}</dd>
                <dt>Overhead</dt><dd>{dec.controlplane_overhead_ms.toFixed(2)} ms (seq {dec.sequential_check_ms.toFixed(2)} / par {dec.parallel_check_ms.toFixed(2)})</dd>
              </div>
            </>}
          </div>
        </div>

        {dec && (
          <div className="card">
            <h3>Evidence</h3>
            {dec.evidence.length === 0 && <div className="muted small">No evidence recorded.</div>}
            {dec.evidence.map((e, i) => (
              <div className="evidence-line" key={i}>
                {mark(e.kind, e.supports_response)}
                <div><b className="small">{e.kind}</b> — {e.detail} <span className="muted small">(conf {(e.confidence * 100).toFixed(0)})</span></div>
              </div>
            ))}
          </div>
        )}

        {dec && (
          <div className="card">
            <h3>Decision & explanation</h3>
            <div className="pill-row" style={{ marginBottom: 10 }}>
              <ActionBadge action={dec.action} />
              {dec.response_modified && <span className="tag">modified · {dec.modification_method}</span>}
              {dec.execution_stopped && <span className="tag">execution stopped</span>}
              {dec.requires_human_review && <span className="tag">human review</span>}
            </div>
            <dl className="kv">
              <dt>What happened</dt><dd>{dec.what_happened}</dd>
              <dt>How detected</dt><dd>{dec.how_detected}</dd>
              <dt>How confident</dt><dd>{dec.how_confident}</dd>
              <dt>Why this action</dt><dd>{dec.why_action}</dd>
              <dt>What we did</dt><dd>{dec.what_we_did}</dd>
            </dl>
            {dec.projected_cost_usd > 0 && (
              <div className="callout" style={{ marginTop: 10 }}>
                Budget ${dec.cost_budget_usd.toFixed(2)} · projected ${dec.projected_cost_usd.toFixed(3)}
                {dec.prevented_spend_usd > 0 && <> · <b>prevented simulated spend ${dec.prevented_spend_usd.toFixed(3)}</b></>}
              </div>
            )}
            <div style={{ marginTop: 12 }} className="spread">
              <div className="small muted">
                {dec.original_response_redacted ? "Original (redacted for storage)" : "Original"} vs released response
              </div>
              <div className="pill-row">
                <button className="btn small secondary" onClick={() => sendFeedback("up")}>👍 helpful</button>
                <button className="btn small secondary" onClick={() => sendFeedback("down")}>👎 issue</button>
              </div>
            </div>
            {detectedEntities.length > 0 && (
              <div className="small muted" style={{ marginTop: 4 }}>
                Detected sensitive entities: {detectedEntities.join(", ")} (types only — values not stored)
              </div>
            )}
            <div className="grid small" style={{ gridTemplateColumns: "1fr 1fr", marginTop: 6 }}>
              <div className="card" style={{ background: "var(--surface-2)" }}><b>{dec.original_response_redacted ? "Original (redacted for storage)" : "Original"}</b><div className="muted">{dec.original_response || "—"}</div></div>
              <div className="card" style={{ background: "var(--surface-2)" }}><b>Released (safe)</b><div className="muted">{dec.safe_response || "—"}</div></div>
            </div>
            {fb && <div className="callout" style={{ marginTop: 10 }}>{fb}</div>}
          </div>
        )}
      </div>
    </>
  );
}
