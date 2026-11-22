import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { Badge, Card, CardTitle, EmptyState, ErrorState, PageHeader, Skeleton, Table, Td } from "../../components/ui";
import { api } from "../../lib/api";
import { formatDateTime, formatPercent, LANGUAGE_LABELS } from "../../lib/format";
import type { EvalResult, EvalRun } from "../../lib/types";

const AXIS = { fontSize: 12, fill: "#64748b" };
const METRICS: [string, string][] = [
  ["pass_rate", "Pass rate"],
  ["correctness", "Correctness (deterministic)"],
  ["judge_correctness", "Correctness (LLM judge)"],
  ["retrieval_hit_rate", "Retrieval hit rate"],
  ["retrieval_mrr", "Retrieval MRR"],
  ["faithfulness", "Faithfulness"],
  ["hallucination_rate", "Hallucination rate (lower is better)"],
  ["language_consistency", "Language consistency"],
  ["tool_selection", "Tool selection"],
  ["tool_execution", "Tool execution"],
  ["injection_resistance", "Injection resistance"],
];

function RunDetail({ id }: { id: string }) {
  const [failedOnly, setFailedOnly] = useState(true);
  const run = useQuery({
    queryKey: ["eval-run", id, failedOnly],
    queryFn: () => api<EvalRun & { results: EvalResult[] }>(`/api/v1/evals/runs/${id}?failed_only=${failedOnly}`),
  });
  if (run.isLoading) return <Skeleton className="h-96" />;
  if (run.isError) return <ErrorState error={run.error} onRetry={() => void run.refetch()} />;
  const r = run.data!;
  const overall = r.metrics.overall ?? {};
  const comparison = r.metrics.comparison ?? {};
  const byLanguage = Object.entries(r.metrics.by_language ?? {}).map(([language, m]) => ({ language: LANGUAGE_LABELS[language] ?? language, ...m }));
  const byCategory = Object.entries(r.metrics.by_category ?? {});

  return (
    <div className="space-y-6">
      <Card>
        <CardTitle action={<Badge tone={r.mode === "full" ? "blue" : "neutral"}>{r.mode === "full" ? "full: LLM agent + judge" : "offline: no LLM"}</Badge>}>
          Run of {formatDateTime(r.started_at)} · {r.passed_cases}/{r.total_cases} passed
        </CardTitle>
        <div className="grid gap-x-8 gap-y-2 text-sm sm:grid-cols-2 lg:grid-cols-3">
          {METRICS.filter(([k]) => overall[k] !== undefined && overall[k] !== null).map(([k, label]) => (
            <div key={k} className="flex items-baseline justify-between gap-2 border-b border-slate-100 py-1.5 dark:border-slate-800">
              <span className="text-slate-500">{label}</span>
              <span className="font-semibold tabular-nums">
                {formatPercent(overall[k])}
                {comparison[k] && Math.abs(comparison[k].delta) >= 0.0005 && (
                  <span className={`ms-2 text-xs ${(k === "hallucination_rate" ? -comparison[k].delta : comparison[k].delta) > 0 ? "text-emerald-600" : "text-red-600"}`}>
                    {comparison[k].delta > 0 ? "+" : ""}{(comparison[k].delta * 100).toFixed(1)} pt
                  </span>
                )}
              </span>
            </div>
          ))}
        </div>
        <details className="mt-4 text-xs text-slate-500">
          <summary className="cursor-pointer">Configuration</summary>
          <pre className="mt-2 overflow-x-auto rounded-md bg-slate-50 p-3 dark:bg-slate-950" dir="ltr">{JSON.stringify({ ...r.config, git_sha: r.git_sha, dataset: r.dataset_version }, null, 2)}</pre>
        </details>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardTitle>By language</CardTitle>
          <div className="h-64" dir="ltr">
            <ResponsiveContainer>
              <BarChart data={byLanguage}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
                <XAxis dataKey="language" tick={AXIS} />
                <YAxis domain={[0, 1]} tickFormatter={(v: number) => `${Math.round(v * 100)}%`} tick={AXIS} width={40} />
                <Tooltip formatter={(v) => formatPercent(Number(v))} />
                <Bar dataKey="pass_rate" name="Pass rate" fill="#0f766e" radius={[4, 4, 0, 0]} />
                <Bar dataKey="language_consistency" name="Language consistency" fill="#38bdf8" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
        <Card>
          <CardTitle>By category</CardTitle>
          <Table head={["Category", "Cases", "Pass rate"]}>
            {byCategory.map(([category, m]) => (
              <tr key={category}>
                <Td>{category}</Td>
                <Td className="tabular-nums">{m.cases}</Td>
                <Td className="tabular-nums">{formatPercent(m.pass_rate)}</Td>
              </tr>
            ))}
          </Table>
        </Card>
      </div>

      <Card className="p-0">
        <div className="flex items-center justify-between p-4">
          <h2 className="text-sm font-semibold">{failedOnly ? "Failed cases" : "All cases"}</h2>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={failedOnly} onChange={(e) => setFailedOnly(e.target.checked)} /> Failed only
          </label>
        </div>
        {r.results.length === 0 ? (
          <div className="p-4"><EmptyState title={failedOnly ? "No failed cases" : "No results"} /></div>
        ) : (
          <Table head={["Case", "Question", "Answer", "Why it failed"]}>
            {r.results.map((c) => (
              <tr key={c.case_id}>
                <Td className="whitespace-nowrap">
                  <p className="font-mono text-xs">{c.case_id}</p>
                  <div className="mt-1 flex gap-1"><Badge>{c.language}</Badge>{c.passed ? <Badge tone="green">pass</Badge> : <Badge tone="red">fail</Badge>}</div>
                </Td>
                <Td className="max-w-xs"><p dir="auto">{c.question}</p></Td>
                <Td className="max-w-md"><p dir="auto" className="line-clamp-4 text-slate-600 dark:text-slate-300">{c.answer}</p></Td>
                <Td className="max-w-xs text-xs text-red-700 dark:text-red-300">{c.failure_reasons.join("; ") || "—"}</Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </div>
  );
}

export default function Evaluations() {
  const runs = useQuery({ queryKey: ["eval-runs"], queryFn: () => api<EvalRun[]>("/api/v1/evals/runs?limit=30") });
  const [selected, setSelected] = useState<string | null>(null);
  const header = <PageHeader title="Evaluations" description="Scores from real runs of the evaluation suite (100+ questions in English, French, Arabic and Tunisian Arabic)." />;

  if (runs.isLoading) return <>{header}<Skeleton className="h-64" /></>;
  if (runs.isError) return <>{header}<ErrorState error={runs.error} onRetry={() => void runs.refetch()} /></>;
  const list = runs.data!;
  if (list.length === 0) {
    return <>{header}<EmptyState title="No evaluation runs yet">Run <code>python -m evals.run --mode offline</code> (or <code>--mode full</code> with an LLM configured).</EmptyState></>;
  }
  const current = selected ?? list[0].id;
  const history = [...list].reverse().map((r) => ({
    date: new Date(r.started_at).toLocaleDateString(),
    [r.mode]: r.metrics.overall?.pass_rate ?? null,
  }));

  return (
    <>
      {header}
      <div className="grid gap-6 lg:grid-cols-[280px_1fr]">
        <div className="space-y-4">
          <Card className="p-0">
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">
              {list.map((r) => (
                <li key={r.id}>
                  <button onClick={() => setSelected(r.id)} className={`w-full px-4 py-3 text-start text-sm ${current === r.id ? "bg-brand-50 dark:bg-slate-800" : "hover:bg-slate-50 dark:hover:bg-slate-800/50"}`}>
                    <div className="flex items-center justify-between">
                      <span className="font-medium">{formatPercent(r.metrics.overall?.pass_rate)}</span>
                      <Badge tone={r.mode === "full" ? "blue" : "neutral"}>{r.mode}</Badge>
                    </div>
                    <p className="mt-0.5 text-xs text-slate-500">{formatDateTime(r.started_at)} · {r.trigger}</p>
                  </button>
                </li>
              ))}
            </ul>
          </Card>
          {list.length > 1 && (
            <Card>
              <CardTitle>Pass rate history</CardTitle>
              <div className="h-40" dir="ltr">
                <ResponsiveContainer>
                  <LineChart data={history}>
                    <XAxis dataKey="date" tick={AXIS} />
                    <YAxis domain={[0, 1]} hide />
                    <Tooltip formatter={(v) => formatPercent(Number(v))} />
                    <Line dataKey="offline" stroke="#64748b" connectNulls dot />
                    <Line dataKey="full" stroke="#0f766e" connectNulls dot />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </Card>
          )}
        </div>
        <RunDetail id={current} />
      </div>
    </>
  );
}
