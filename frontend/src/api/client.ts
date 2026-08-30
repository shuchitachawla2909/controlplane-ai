const BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${text}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => req<{ status: string; demo_mode: boolean; llm_provider: string }>("/health"),

  overview: () => req<import("../types").Overview>("/api/metrics/overview"),
  risk: () => req<any>("/api/metrics/risk"),
  latency: () => req<any>("/api/metrics/latency"),
  learning: () => req<any>("/api/metrics/learning"),

  traces: (params: Record<string, string | number | undefined> = {}) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => v !== undefined && v !== "" && qs.set(k, String(v)));
    return req<import("../types").DecisionRow[]>(`/api/traces?${qs.toString()}`);
  },
  trace: (id: string) => req<import("../types").TraceDetail>(`/api/traces/${id}`),

  reviewQueue: (status = "pending") =>
    req<import("../types").ReviewCase[]>(`/api/review-queue?status=${status}`),
  submitReview: (caseId: string, verdict: string, comment: string) =>
    req<any>(`/api/review/${caseId}`, { method: "POST", body: JSON.stringify({ verdict, comment }) }),
  feedback: (trace_id: string, thumbs: "up" | "down", reason: string) =>
    req<any>("/api/feedback", { method: "POST", body: JSON.stringify({ trace_id, thumbs, reason }) }),

  policies: () => req<import("../types").PolicySummary[]>("/api/policies"),
  policy: (workflow: string) => req<any>(`/api/policies/${workflow}`),
  updatePolicy: (workflow: string, body: any, note: string) =>
    req<any>(`/api/policies/${workflow}`, { method: "PUT", body: JSON.stringify({ body, note }) }),

  scenarios: () => req<any[]>("/api/demo/scenarios"),
  runScenario: (key: string) => req<any>(`/api/demo/run/${key}`, { method: "POST" }),
  seed: (count = 1200) => req<any>(`/api/demo/seed?count=${count}`, { method: "POST" }),

  benchmarkResults: () => req<import("../types").BenchmarkRun[]>("/api/benchmark/results"),
  runBenchmark: (count: number, profile = "mixed", deep_eval_sim_latency_ms = 0) =>
    req<any>("/api/benchmark/run", {
      method: "POST",
      body: JSON.stringify({ count, profile, deep_eval_sim_latency_ms }),
    }),
};
