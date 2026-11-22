import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { Badge, Card, CardTitle, EmptyState, ErrorState, PageHeader, Skeleton, Stat, statusTone, Table, Td } from "../../components/ui";
import { api } from "../../lib/api";
import { formatMs, formatPercent, formatUsd, LANGUAGE_LABELS } from "../../lib/format";
import type { Overview } from "../../lib/types";

const AXIS = { fontSize: 12, fill: "#64748b" };

export default function Dashboard() {
  const [days, setDays] = useState(30);
  const overview = useQuery({ queryKey: ["overview", days], queryFn: () => api<Overview>(`/api/v1/admin/overview?days=${days}`) });

  const header = (
    <PageHeader
      title="Dashboard"
      description="Conversations, resolution, response times, model usage and cost for your shop."
      actions={
        <select value={days} onChange={(e) => setDays(Number(e.target.value))} className="rounded-md border border-slate-300 bg-transparent px-2 py-1.5 text-sm dark:border-slate-700" aria-label="Period">
          <option value={1}>Last 24 hours</option>
          <option value={7}>Last 7 days</option>
          <option value={30}>Last 30 days</option>
          <option value={365}>Last 12 months</option>
        </select>
      }
    />
  );

  if (overview.isLoading) {
    return (
      <>
        {header}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-24" />)}
        </div>
      </>
    );
  }
  if (overview.isError) return <>{header}<ErrorState error={overview.error} onRetry={() => void overview.refetch()} /></>;
  const o = overview.data!;
  const answeredRate = o.replies.total ? o.replies.answered / o.replies.total : null;
  const unknownRate = o.replies.total ? o.replies.unknown / o.replies.total : null;
  const toolTotals = Object.values(
    o.tools.reduce<Record<string, { tool: string; success: number; other: number }>>((acc, t) => {
      acc[t.tool] ??= { tool: t.tool, success: 0, other: 0 };
      if (t.status === "success") acc[t.tool].success += t.calls;
      else acc[t.tool].other += t.calls;
      return acc;
    }, {}),
  );

  return (
    <>
      {header}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Conversations" value={o.conversations.active} hint={`${o.conversations.total} sessions started`} />
        <Stat label="Resolved" value={o.conversations.resolved} hint="marked resolved by the team" />
        <Stat label="Escalated" value={o.conversations.escalated} hint="handed over to a human" />
        <Stat label="Answered by the agent" value={formatPercent(answeredRate)} hint={`${o.replies.total} replies, ${formatPercent(unknownRate)} "I don't know"`} />
        <Stat label="Avg response time" value={formatMs(o.replies.avg_latency_ms)} hint={`p95 ${formatMs(o.replies.p95_latency_ms)}`} />
        <Stat label="Estimated model cost" value={formatUsd(o.replies.cost_usd)} hint="from token usage and the price table" />
        <Stat label="Refused requests" value={o.replies.refused} hint="injection or manipulation attempts" />
        <Stat
          label="Latest evaluation"
          value={o.latest_eval?.overall?.pass_rate !== undefined ? formatPercent(o.latest_eval.overall.pass_rate) : "—"}
          hint={o.latest_eval ? <Link className="underline" to="/admin/evaluations">{o.latest_eval.mode} run · {o.latest_eval.passed_cases}/{o.latest_eval.total_cases} passed</Link> : "no run yet"}
        />
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <Card>
          <CardTitle>Conversations per day</CardTitle>
          {o.per_day.length === 0 ? (
            <EmptyState title="No conversations in this period" />
          ) : (
            <div className="h-64" dir="ltr">
              <ResponsiveContainer>
                <BarChart data={o.per_day}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
                  <XAxis dataKey="day" tick={AXIS} />
                  <YAxis allowDecimals={false} tick={AXIS} width={32} />
                  <Tooltip />
                  <Bar dataKey="conversations" fill="#0f766e" name="Conversations" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="escalated" fill="#f59e0b" name="Escalated" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>
        <Card>
          <CardTitle>Tool calls</CardTitle>
          {toolTotals.length === 0 ? (
            <EmptyState title="No tool calls yet" />
          ) : (
            <div className="h-64" dir="ltr">
              <ResponsiveContainer>
                <BarChart data={toolTotals} layout="vertical" margin={{ left: 40 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" horizontal={false} />
                  <XAxis type="number" allowDecimals={false} tick={AXIS} />
                  <YAxis type="category" dataKey="tool" tick={AXIS} width={140} />
                  <Tooltip />
                  <Bar dataKey="success" stackId="a" fill="#0f766e" name="Success" />
                  <Bar dataKey="other" stackId="a" fill="#94a3b8" name="Denied / not found / invalid" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-[2fr_1fr]">
        <Card>
          <CardTitle>Model usage</CardTitle>
          {o.models.length === 0 ? (
            <EmptyState title="No model calls in this period">
              Replies came from the rule-based planner and templates (no LLM provider configured or reachable).
            </EmptyState>
          ) : (
            <Table head={["Model", "Tier", "Calls", "Tokens in / out", "Avg latency", "Fallback", "Failed", "Cost"]}>
              {o.models.map((m) => (
                <tr key={`${m.model}-${m.tier}`}>
                  <Td className="font-medium">{m.model}</Td>
                  <Td><Badge tone={m.tier === "smart" ? "blue" : "neutral"}>{m.tier}</Badge></Td>
                  <Td className="tabular-nums">{m.calls}</Td>
                  <Td className="tabular-nums">{m.prompt_tokens.toLocaleString()} / {m.completion_tokens.toLocaleString()}</Td>
                  <Td className="tabular-nums">{formatMs(m.avg_latency_ms)}</Td>
                  <Td className="tabular-nums">{m.fallback_calls}</Td>
                  <Td className="tabular-nums">{m.failed_calls}</Td>
                  <Td className="tabular-nums">{formatUsd(m.cost_usd)}</Td>
                </tr>
              ))}
            </Table>
          )}
        </Card>
        <Card>
          <CardTitle>Reply languages</CardTitle>
          {o.languages.length === 0 ? (
            <EmptyState title="No replies yet" />
          ) : (
            <ul className="space-y-2 text-sm">
              {o.languages.sort((a, b) => b.replies - a.replies).map((l) => (
                <li key={l.language} className="flex items-center justify-between">
                  <span>{LANGUAGE_LABELS[l.language] ?? l.language}</span>
                  <Badge tone={statusTone("")}>{l.replies}</Badge>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </>
  );
}
