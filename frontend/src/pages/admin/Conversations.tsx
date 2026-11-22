import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";

import { Badge, Card, EmptyState, ErrorState, PageHeader, Skeleton, statusTone, Table, Td } from "../../components/ui";
import { api } from "../../lib/api";
import { formatDateTime, LANGUAGE_LABELS } from "../../lib/format";
import type { ConversationListItem } from "../../lib/types";

const FILTERS = [
  { value: "", label: "All" },
  { value: "open", label: "Open" },
  { value: "escalated", label: "Escalated" },
  { value: "resolved", label: "Resolved" },
];

export default function Conversations() {
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const limit = 25;
  const list = useQuery({
    queryKey: ["conversations", status, offset],
    queryFn: () =>
      api<{ total: number; items: ConversationListItem[] }>(
        `/api/v1/admin/conversations?limit=${limit}&offset=${offset}${status ? `&status=${status}` : ""}`,
      ),
    refetchInterval: 15_000,
  });

  return (
    <>
      <PageHeader title="Conversations" description="Every conversation with its messages, tool calls, sources and escalations." />
      <div className="mb-4 flex gap-1" role="tablist">
        {FILTERS.map((f) => (
          <button
            key={f.value}
            role="tab"
            aria-selected={status === f.value}
            onClick={() => { setStatus(f.value); setOffset(0); }}
            className={`rounded-md px-3 py-1.5 text-sm ${status === f.value ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900" : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"}`}
          >
            {f.label}
          </button>
        ))}
      </div>
      <Card className="p-0">
        {list.isLoading ? (
          <div className="space-y-2 p-4">{Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-10" />)}</div>
        ) : list.isError ? (
          <div className="p-4"><ErrorState error={list.error} onRetry={() => void list.refetch()} /></div>
        ) : list.data!.items.length === 0 ? (
          <div className="p-4"><EmptyState title="No conversations yet">Open the live demo or the demo store and send a message.</EmptyState></div>
        ) : (
          <Table head={["First message", "Status", "Language", "Visitor", "Messages", "Last activity"]}>
            {list.data!.items.map((c) => (
              <tr key={c.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/50">
                <Td className="max-w-md">
                  <Link to={`/admin/conversations/${c.id}`} className="line-clamp-2 font-medium hover:text-brand-700" dir="auto">
                    {c.preview || "(no message)"}
                  </Link>
                </Td>
                <Td><Badge tone={statusTone(c.status)}>{c.status}</Badge></Td>
                <Td>{c.language ? LANGUAGE_LABELS[c.language] ?? c.language : "—"}</Td>
                <Td className="text-slate-500">{c.customer_id ? "signed-in customer" : "guest"}</Td>
                <Td className="tabular-nums">{c.message_count}</Td>
                <Td className="whitespace-nowrap text-slate-500">{formatDateTime(c.last_message_at)}</Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
      {list.data && list.data.total > limit && (
        <div className="mt-4 flex items-center justify-between text-sm">
          <span className="text-slate-500">{offset + 1}–{Math.min(offset + limit, list.data.total)} of {list.data.total}</span>
          <div className="flex gap-2">
            <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))} className="rounded-md border px-3 py-1 disabled:opacity-40 dark:border-slate-700">Previous</button>
            <button disabled={offset + limit >= list.data.total} onClick={() => setOffset(offset + limit)} className="rounded-md border px-3 py-1 disabled:opacity-40 dark:border-slate-700">Next</button>
          </div>
        </div>
      )}
    </>
  );
}
