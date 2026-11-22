import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CheckCircle2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router";

import { Badge, Button, Card, CardTitle, ErrorState, PageHeader, Skeleton, statusTone, Table, Td } from "../../components/ui";
import { api } from "../../lib/api";
import { isRtl } from "../../lib/chatClient";
import { formatDateTime, formatMs, formatUsd, LANGUAGE_LABELS } from "../../lib/format";
import type { ConversationDetail as Detail, ConversationMessage } from "../../lib/types";

function Flags({ message }: { message: ConversationMessage }) {
  const flags = message.flags as {
    guard?: { action: string; score: number; categories: string[] };
    route?: { tier: string; score: number; reasons: string[] };
    plan?: { intent: string; tools: string[] };
    plan_source?: string;
    validation?: { ok?: boolean; problems?: string[]; skipped?: boolean };
    retrieval?: { confidence: number; candidates: number; latency_ms: number } | null;
    degraded?: boolean;
  };
  return (
    <div className="mt-2 flex flex-wrap gap-1.5 text-xs">
      {message.outcome && <Badge tone={statusTone(message.outcome)}>{message.outcome}</Badge>}
      {flags.plan && <Badge>intent: {flags.plan.intent}</Badge>}
      {flags.plan_source && <Badge tone={flags.plan_source === "llm" ? "blue" : "neutral"}>planner: {flags.plan_source}</Badge>}
      {flags.route?.tier && <Badge>tier: {flags.route.tier}</Badge>}
      {message.model && <Badge>{message.model}</Badge>}
      {flags.guard && flags.guard.action !== "allow" && (
        <Badge tone="red">guard: {flags.guard.action} ({flags.guard.categories.join(", ")})</Badge>
      )}
      {flags.retrieval && <Badge>retrieval {flags.retrieval.confidence.toFixed(2)}</Badge>}
      {flags.validation?.problems?.length ? <Badge tone="amber">validation: {flags.validation.problems.join(", ")}</Badge> : null}
      {flags.degraded && <Badge tone="amber">degraded mode</Badge>}
      {message.latency_ms !== null && <Badge>{formatMs(message.latency_ms)}</Badge>}
      {message.cost_usd > 0 && <Badge>{formatUsd(message.cost_usd)}</Badge>}
    </div>
  );
}

export default function ConversationDetail() {
  const { id } = useParams();
  const queryClient = useQueryClient();
  const [reply, setReply] = useState("");
  const detail = useQuery({
    queryKey: ["conversation", id],
    queryFn: () => api<Detail>(`/api/v1/admin/conversations/${id}`),
    refetchInterval: 10_000,
  });
  const send = useMutation({
    mutationFn: (content: string) =>
      api(`/api/v1/admin/conversations/${id}/reply`, { method: "POST", body: JSON.stringify({ content }) }),
    onSuccess: () => {
      setReply("");
      void queryClient.invalidateQueries({ queryKey: ["conversation", id] });
    },
  });
  const resolve = useMutation({
    mutationFn: () => api(`/api/v1/admin/conversations/${id}/resolve`, { method: "POST" }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["conversation", id] }),
  });

  const back = (
    <Link to="/admin/conversations" className="mb-4 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-900 dark:hover:text-slate-100">
      <ArrowLeft className="size-4 rtl:-scale-x-100" /> Conversations
    </Link>
  );
  if (detail.isLoading) return <>{back}<Skeleton className="h-96" /></>;
  if (detail.isError) return <>{back}<ErrorState error={detail.error} onRetry={() => void detail.refetch()} /></>;
  const d = detail.data!;
  const toolsByMessage = d.tool_calls.reduce<Record<string, Detail["tool_calls"]>>((acc, t) => {
    (acc[t.message_id ?? "none"] ??= []).push(t);
    return acc;
  }, {});

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (reply.trim()) send.mutate(reply.trim());
  }

  return (
    <>
      {back}
      <PageHeader
        title="Conversation"
        description={`${formatDateTime(d.started_at)} · ${d.customer_id ? "signed-in customer" : "guest"} · ${d.language ? LANGUAGE_LABELS[d.language] ?? d.language : "language not detected yet"}`}
        actions={
          <>
            <Badge tone={statusTone(d.status)}>{d.status}</Badge>
            {d.status !== "resolved" && (
              <Button size="sm" variant="secondary" onClick={() => resolve.mutate()} disabled={resolve.isPending}>
                <CheckCircle2 className="size-4" /> Mark resolved
              </Button>
            )}
          </>
        }
      />
      <div className="grid gap-6 xl:grid-cols-[1fr_380px]">
        <Card>
          <CardTitle>Messages</CardTitle>
          <ol className="space-y-5">
            {d.messages.map((m) => (
              <li key={m.id} className="border-b border-slate-100 pb-5 last:border-0 dark:border-slate-800">
                <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
                  {m.role === "user" ? "Customer" : m.role === "assistant" ? "Agent" : `Human agent${(m.flags as { author?: string }).author ? ` · ${(m.flags as { author?: string }).author}` : ""}`} · {formatDateTime(m.created_at)}
                </p>
                <p dir={m.language ? (isRtl(m.language) ? "rtl" : "ltr") : "auto"} className="mt-1 whitespace-pre-wrap">{m.content}</p>
                {m.role === "assistant" && <Flags message={m} />}
                {toolsByMessage[m.id]?.length ? (
                  <ul className="mt-2 space-y-1 text-xs">
                    {toolsByMessage[m.id].map((t) => (
                      <li key={t.id} className="flex flex-wrap items-center gap-2 rounded-md bg-slate-50 px-2 py-1.5 dark:bg-slate-800">
                        <span className="font-mono font-medium">{t.tool}</span>
                        <Badge tone={statusTone(t.status)}>{t.status}{t.error ? `: ${t.error}` : ""}</Badge>
                        <span className="font-mono text-slate-500" dir="ltr">{JSON.stringify(t.arguments)}</span>
                        <span className="text-slate-400">{formatMs(t.latency_ms)}</span>
                      </li>
                    ))}
                  </ul>
                ) : null}
                {m.sources?.length ? (
                  <ul className="mt-2 space-y-1 text-xs text-slate-500">
                    {m.sources.map((s) => (
                      <li key={s.id} dir="auto">[{s.id}] {s.title}{s.heading ? ` > ${s.heading}` : ""} ({s.score.toFixed(2)})</li>
                    ))}
                  </ul>
                ) : null}
              </li>
            ))}
          </ol>
          <form onSubmit={onSubmit} className="mt-4 border-t border-slate-200 pt-4 dark:border-slate-800">
            <label className="mb-1 block text-sm font-medium" htmlFor="human-reply">Reply as a human agent</label>
            <textarea id="human-reply" dir="auto" rows={3} value={reply} onChange={(e) => setReply(e.target.value)} className="w-full rounded-md border border-slate-300 bg-transparent px-3 py-2 text-sm dark:border-slate-700" />
            {send.isError && <p className="mt-1 text-sm text-red-600">{(send.error as Error).message}</p>}
            <Button type="submit" size="sm" className="mt-2" disabled={send.isPending || !reply.trim()}>Send reply</Button>
          </form>
        </Card>
        <div className="space-y-6">
          <Card>
            <CardTitle>Tickets and escalations</CardTitle>
            {d.tickets.length === 0 ? <p className="text-sm text-slate-500">None.</p> : (
              <ul className="space-y-2 text-sm">
                {d.tickets.map((t) => (
                  <li key={t.ticket_number} className="flex items-start justify-between gap-2">
                    <div>
                      <p className="font-medium">{t.ticket_number}</p>
                      <p className="text-xs text-slate-500">{t.subject}</p>
                    </div>
                    <div className="flex gap-1">
                      {t.is_escalation && <Badge tone="blue">hand-off</Badge>}
                      <Badge tone={t.priority === "high" ? "red" : "neutral"}>{t.priority}</Badge>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <Card>
            <CardTitle>Model calls</CardTitle>
            {d.llm_calls.length === 0 ? <p className="text-sm text-slate-500">No LLM calls (rule-based planner and templates).</p> : (
              <Table head={["Step", "Model", "Tokens", "Latency"]}>
                {d.llm_calls.map((c, i) => (
                  <tr key={i}>
                    <Td>{c.purpose}{c.fallback_used ? " (fallback)" : ""}{!c.success ? " ✗" : ""}</Td>
                    <Td className="text-xs">{c.model}</Td>
                    <Td className="tabular-nums">{c.prompt_tokens}/{c.completion_tokens}</Td>
                    <Td className="tabular-nums">{formatMs(c.latency_ms)}</Td>
                  </tr>
                ))}
              </Table>
            )}
          </Card>
        </div>
      </div>
    </>
  );
}
