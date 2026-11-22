import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileUp, RefreshCw, Search, Trash2 } from "lucide-react";
import { Fragment, useRef, useState, type DragEvent, type FormEvent } from "react";

import { Badge, Button, Card, CardTitle, EmptyState, ErrorState, PageHeader, Skeleton, Spinner, statusTone, Table, Td } from "../../components/ui";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { formatBytes, formatDateTime } from "../../lib/format";
import type { KnowledgeDocument, RetrievalDebug } from "../../lib/types";

const ACCEPT = ".pdf,.docx,.txt,.md";

function Chunks({ id }: { id: string }) {
  const chunks = useQuery({
    queryKey: ["chunks", id],
    queryFn: () => api<{ index: number; heading: string; content: string; language: string; tokens: number; quarantined: boolean }[]>(`/api/v1/admin/documents/${id}/chunks`),
  });
  if (chunks.isLoading) return <Spinner />;
  if (chunks.isError) return <ErrorState error={chunks.error} />;
  return (
    <ol className="max-h-96 space-y-2 overflow-y-auto">
      {chunks.data!.map((c) => (
        <li key={c.index} className="rounded-md border border-slate-200 p-2 text-xs dark:border-slate-700">
          <div className="mb-1 flex flex-wrap gap-1.5">
            <Badge>#{c.index}</Badge>
            <Badge>{c.language}</Badge>
            <Badge>{c.tokens} tokens</Badge>
            {c.quarantined && <Badge tone="red">quarantined: looks like instructions to the AI</Badge>}
          </div>
          {c.heading && <p dir="auto" className="font-medium">{c.heading}</p>}
          <p dir="auto" className="whitespace-pre-wrap text-slate-600 dark:text-slate-300">{c.content}</p>
        </li>
      ))}
    </ol>
  );
}

function SearchTester() {
  const [query, setQuery] = useState("");
  const search = useMutation({
    mutationFn: (q: string) => api<RetrievalDebug>("/api/v1/admin/search", { method: "POST", body: JSON.stringify({ query: q }) }),
  });
  function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (query.trim().length >= 2) search.mutate(query.trim());
  }
  return (
    <Card>
      <CardTitle>Test retrieval</CardTitle>
      <form onSubmit={onSubmit} className="flex gap-2">
        <input dir="auto" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="e.g. Can I return opened headphones?" className="flex-1 rounded-md border border-slate-300 bg-transparent px-3 py-2 text-sm dark:border-slate-700" />
        <Button type="submit" disabled={search.isPending}><Search className="size-4" /> Search</Button>
      </form>
      {search.isPending && <div className="mt-3"><Spinner label="Searching" /></div>}
      {search.isError && <div className="mt-3"><ErrorState error={search.error} /></div>}
      {search.data && (
        <div className="mt-4 text-sm">
          <p className="text-slate-500">
            Confidence {search.data.confidence.toFixed(3)} (threshold {search.data.threshold}) ·{" "}
            {search.data.confidence >= search.data.threshold ? <Badge tone="green">answerable</Badge> : <Badge tone="amber">"I don't know" path</Badge>} ·{" "}
            {search.data.candidates} candidates · {search.data.latency_ms} ms
          </p>
          <ol className="mt-3 space-y-2">
            {search.data.chunks.map((c) => (
              <li key={c.source_id} className="rounded-md border border-slate-200 p-2.5 dark:border-slate-700">
                <div className="flex flex-wrap items-center gap-1.5 text-xs">
                  <Badge tone="blue">rerank {c.rerank_score.toFixed(3)}</Badge>
                  <Badge>vector #{c.vector_rank ?? "—"}</Badge>
                  <Badge>keyword #{c.keyword_rank ?? "—"}</Badge>
                  <Badge>{c.language}</Badge>
                </div>
                <p dir="auto" className="mt-1.5 font-medium">{c.title}{c.heading ? ` > ${c.heading}` : ""}</p>
                <p dir="auto" className="mt-1 line-clamp-3 text-slate-600 dark:text-slate-300">{c.content}</p>
              </li>
            ))}
          </ol>
        </div>
      )}
    </Card>
  );
}

export default function Knowledge() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const canEdit = user?.role === "admin" || user?.role === "agent";

  const docs = useQuery({
    queryKey: ["documents"],
    queryFn: () => api<KnowledgeDocument[]>("/api/v1/admin/documents"),
    // Poll while something is being ingested so the status updates by itself.
    refetchInterval: (q) => (q.state.data?.some((d) => d.status === "pending" || d.status === "processing") ? 2000 : false),
  });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["documents"] });
  const upload = useMutation({
    mutationFn: async (files: File[]) => {
      for (const file of files) {
        const form = new FormData();
        form.append("file", file);
        await api("/api/v1/admin/documents", { method: "POST", body: form });
      }
    },
    onSettled: refresh,
  });
  const remove = useMutation({ mutationFn: (id: string) => api(`/api/v1/admin/documents/${id}`, { method: "DELETE" }), onSettled: refresh });
  const reindex = useMutation({ mutationFn: (id: string) => api(`/api/v1/admin/documents/${id}/reindex`, { method: "POST" }), onSettled: refresh });

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragging(false);
    if (canEdit && e.dataTransfer.files.length) upload.mutate(Array.from(e.dataTransfer.files));
  }

  return (
    <>
      <PageHeader title="Knowledge base" description="Documents the agent can quote. Answers about products, shipping, returns and warranty come only from here and from live shop data." />
      {canEdit && (
        <div
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={`mb-6 flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-6 py-8 text-center ${dragging ? "border-brand-600 bg-brand-50 dark:bg-slate-900" : "border-slate-300 dark:border-slate-700"}`}
        >
          <FileUp className="size-6 text-slate-400" aria-hidden />
          <p className="text-sm">Drop PDF, DOCX, TXT or Markdown files here (max 10 MB each)</p>
          <input ref={input} type="file" accept={ACCEPT} multiple hidden onChange={(e) => e.target.files && upload.mutate(Array.from(e.target.files))} />
          <Button size="sm" variant="secondary" onClick={() => input.current?.click()} disabled={upload.isPending}>
            {upload.isPending ? "Uploading…" : "Choose files"}
          </Button>
          {upload.isError && <p role="alert" className="text-sm text-red-600">{(upload.error as Error).message}</p>}
          {upload.isSuccess && <p className="text-sm text-emerald-700">Uploaded. Processing runs in the background.</p>}
        </div>
      )}

      <Card className="p-0">
        {docs.isLoading ? (
          <div className="space-y-2 p-4">{Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-10" />)}</div>
        ) : docs.isError ? (
          <div className="p-4"><ErrorState error={docs.error} onRetry={() => void docs.refetch()} /></div>
        ) : docs.data!.length === 0 ? (
          <div className="p-4"><EmptyState title="No documents yet">Upload your policies, FAQ and product sheets.</EmptyState></div>
        ) : (
          <Table head={["Document", "Type", "Language", "Status", "Chunks", "Size", "Added", ""]}>
            {docs.data!.map((d) => (
              <Fragment key={d.id}>
                <tr>
                  <Td>
                    <button className="text-start font-medium hover:text-brand-700" onClick={() => setOpen(open === d.id ? null : d.id)} dir="auto">
                      {d.title}
                    </button>
                    <p className="text-xs text-slate-500">{d.filename}</p>
                    {d.error && <p className="text-xs text-red-600">{d.error}</p>}
                  </Td>
                  <Td>{d.doc_type}</Td>
                  <Td>{d.language ?? "—"}</Td>
                  <Td>
                    <Badge tone={statusTone(d.status)}>{d.status}</Badge>
                    {d.quarantined_chunks > 0 && <div className="mt-1"><Badge tone="red">{d.quarantined_chunks} quarantined</Badge></div>}
                  </Td>
                  <Td className="tabular-nums">{d.chunk_count}</Td>
                  <Td className="whitespace-nowrap tabular-nums">{formatBytes(d.size_bytes)}</Td>
                  <Td className="whitespace-nowrap text-slate-500">{formatDateTime(d.created_at)}</Td>
                  <Td>
                    {canEdit && (
                      <div className="flex justify-end gap-1">
                        <button title="Re-index" aria-label="Re-index" onClick={() => reindex.mutate(d.id)} className="rounded p-1.5 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"><RefreshCw className="size-4" /></button>
                        {user?.role === "admin" && (
                          <button
                            title="Delete"
                            aria-label="Delete"
                            onClick={() => window.confirm(`Delete "${d.title}" and its chunks?`) && remove.mutate(d.id)}
                            className="rounded p-1.5 text-red-600 hover:bg-red-50 dark:hover:bg-red-950"
                          >
                            <Trash2 className="size-4" />
                          </button>
                        )}
                      </div>
                    )}
                  </Td>
                </tr>
                {open === d.id && (
                  <tr>
                    <td colSpan={8} className="bg-slate-50 p-3 dark:bg-slate-950"><Chunks id={d.id} /></td>
                  </tr>
                )}
              </Fragment>
            ))}
          </Table>
        )}
      </Card>
      <div className="mt-6"><SearchTester /></div>
    </>
  );
}
