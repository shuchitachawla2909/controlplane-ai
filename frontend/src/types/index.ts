export type Action =
  | "ALLOW" | "MONITOR" | "MODIFY" | "VERIFY" | "BLOCK"
  | "STOP_EXECUTION" | "HUMAN_REVIEW" | "SAFE_FALLBACK";

export interface DecisionRow {
  decision_id: string;
  trace_id: string;
  created_at: number;
  application: string;
  workflow: string;
  action: Action;
  tier: number;
  severity: string;
  overall_risk: number;
  performance_risk: number;
  cost_risk: number;
  responsibility_risk: number;
  evidence_confidence: number;
  controlplane_overhead_ms: number;
  synchronous: boolean;
  requires_human_review: boolean;
  policy_version: string;
}

export interface Evidence {
  kind: string;
  supports_response: boolean;
  detail: string;
  ref_id?: string | null;
  confidence: number;
}

export interface Finding {
  dimension: string;
  score: number;
  confidence: number;
  severity: string;
  label: string;
  reasons: string[];
  evidence: Evidence[];
  evaluator: string;
  tier: number;
  latency_ms: number;
  available: boolean;
}

export interface DecisionRecord extends DecisionRow {
  policy_name: string;
  performance_confidence: number;
  cost_confidence: number;
  responsibility_confidence: number;
  impact: string;
  novelty: number;
  ground_truth_available: boolean;
  tiers_run: number[];
  evaluators_run: string[];
  verification_value: number;
  reasons: string[];
  what_happened: string;
  how_detected: string;
  how_confident: string;
  why_action: string;
  what_we_did: string;
  original_response: string;
  original_response_redacted?: boolean;
  safe_response: string;
  response_modified: boolean;
  modification_method?: string | null;
  projected_cost_usd: number;
  cost_budget_usd: number;
  prevented_spend_usd: number;
  execution_stopped: boolean;
  sequential_check_ms: number;
  parallel_check_ms: number;
  evidence: Evidence[];
  findings: Finding[];
  simulated: boolean;
}

export interface TraceStep {
  step_id: string;
  parent_id?: string | null;
  index: number;
  type: string;
  name?: string | null;
  model?: string | null;
  tool_name?: string | null;
  duration_ms: number;
  usage: { input_tokens: number; output_tokens: number };
  cost_usd: number;
  cumulative_cost_usd: number;
  retries: number;
  retrieved_context: string[];
  risk_signals: string[];
}

export interface TraceDetail {
  trace: {
    trace_id: string;
    session_id: string;
    application: string;
    workflow: string;
    model: string;
    provider: string;
    created_at: number;
    turn_index: number;
    request_preview: string;
    response_preview: string;
    latency_ms: number;
    estimated_cost_usd: number;
    model_calls: number;
    tool_calls: number;
    retrieval_events: number;
    retries: number;
    ground_truth_available: boolean;
    steps: TraceStep[];
  };
  decision: DecisionRecord | null;
}

export interface Overview {
  total_interactions: number;
  fast_path_rate: number;
  deep_evaluation_rate: number;
  high_risk_interventions: number;
  intervention_rate: number;
  estimated_spend_usd: number;
  prevented_runaway_spend_usd: number;
  avg_controlplane_overhead_ms: number;
  avg_fast_path_overhead_ms: number;
  p95_fast_path_overhead_ms: number;
  async_deep_evaluations: number;
  risk_distribution: Record<string, number>;
  elevated_counts: Record<string, number>;
  interventions_by_type: Record<string, number>;
  tier_distribution: Record<string, number>;
  timeseries: any[];
  feedback_trend: any[];
}

export interface ReviewCase {
  case_id: string;
  trace_id: string;
  workflow: string;
  created_at: number;
  status: string;
  reason: string;
  suggested_labels: string[];
  request_preview: string;
  response_preview: string;
  action: string | null;
  overall_risk: number | null;
  validator_verdict: string | null;
}

export interface PolicySummary {
  workflow: string;
  name: string;
  version: string;
  risk_class: string;
  latency_budget_ms: number;
  cost_budget_usd: number;
  thresholds: any;
  routing: any;
  human_review: any;
  data_policy: any;
  profile: any;
}

export interface BenchmarkRun {
  run_id: string;
  created_at: number;
  label: string;
  count: number;
  arms: Record<string, any>;
  north_star: Record<string, any>;
  params: any;
}
