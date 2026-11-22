import { useQuery } from "@tanstack/react-query";
import {
  BookOpen,
  Gauge,
  Globe2,
  Headset,
  LockKeyhole,
  Mic,
  Route as RouteIcon,
  ShieldCheck,
  Wrench,
} from "lucide-react";
import { Link } from "react-router";

import { Card, ErrorState, Skeleton } from "../components/ui";
import { api } from "../lib/api";
import { formatPercent } from "../lib/format";

const FEATURES = [
  { icon: Globe2, title: "Arabic, Tunisian, French, English", text: "Detects the language (including Tunisian Arabizi such as \"chnowa el prix?\") and replies in it. Right-to-left layout for Arabic." },
  { icon: BookOpen, title: "Grounded answers with sources", text: "Hybrid vector + keyword search over PDF, DOCX, TXT and Markdown, cross-lingual queries, a cross-encoder reranker and citations." },
  { icon: Wrench, title: "Real tools, real data", text: "Order status, stock, product search and details, tickets and hand-off run against PostgreSQL through an MCP-compatible tool registry." },
  { icon: ShieldCheck, title: "Never invents facts", text: "Numbers in a draft must exist in the evidence; failed drafts are replaced by answers built from tool data, or by \"I don't know\" and a human." },
  { icon: LockKeyhole, title: "Security in the backend", text: "Row-level security per shop, server-side tool authorisation, prompt-injection filters, rate limits and redacted logs." },
  { icon: RouteIcon, title: "Model router with fallback", text: "Cheap model for simple turns, capable model for hard ones, a second provider when the first fails, and every call costed." },
  { icon: Mic, title: "Voice in and out", text: "Speech-to-text (local Whisper or OpenAI) and text-to-speech (browser voices or OpenAI) behind swappable providers." },
  { icon: Headset, title: "Human hand-off", text: "Escalations create a ticket, flag the conversation for the team, and human replies appear in the customer's chat." },
  { icon: Gauge, title: "Measured", text: "Evaluation suite with 100+ questions in four languages, per-metric and per-language scores, and Langfuse traces." },
];

const STEPS = [
  ["Guard", "normalise, detect language, scan for injection"],
  ["Route", "pick the fast or the capable model"],
  ["Plan", "intent, tools, entities, translated search queries"],
  ["Execute", "permission-checked tools + hybrid retrieval"],
  ["Respond", "answer only from evidence, with citations"],
  ["Validate", "numbers, contacts, promises, leaks, language"],
];

interface PublicSummary {
  full: Summary | null;
  offline: Summary | null;
}
interface Summary {
  started_at: string;
  mode: string;
  total_cases: number;
  passed_cases: number;
  overall: Record<string, number> | null;
  by_language: Record<string, Record<string, number>> | null;
}

function EvalSummary() {
  const summary = useQuery({ queryKey: ["eval-summary"], queryFn: () => api<PublicSummary>("/api/v1/public/eval-summary") });
  if (summary.isLoading) return <Skeleton className="h-32" />;
  if (summary.isError) return <ErrorState error={summary.error} onRetry={() => void summary.refetch()} />;
  const runs = [summary.data?.full, summary.data?.offline].filter(Boolean) as Summary[];
  if (!runs.length) {
    return <p className="text-sm text-slate-500">No evaluation has been run on this deployment yet. Run <code>python -m evals.run</code>.</p>;
  }
  const keys = ["pass_rate", "correctness", "retrieval_hit_rate", "hallucination_rate", "language_consistency", "tool_selection", "injection_resistance"];
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {runs.map((run) => (
        <Card key={run.mode}>
          <p className="text-sm font-semibold">{run.mode === "full" ? "Full run (LLM agent + judge)" : "Offline run (no LLM: rule-based planner and templates)"}</p>
          <p className="mt-1 text-xs text-slate-500">
            {run.passed_cases}/{run.total_cases} cases passed · {new Date(run.started_at).toLocaleString()}
          </p>
          <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm">
            {keys.filter((k) => run.overall?.[k] !== undefined && run.overall?.[k] !== null).map((k) => (
              <div key={k} className="flex justify-between gap-2">
                <dt className="text-slate-500">{k.replaceAll("_", " ")}</dt>
                <dd className="font-medium tabular-nums">{formatPercent(run.overall![k])}</dd>
              </div>
            ))}
          </dl>
        </Card>
      ))}
    </div>
  );
}

export default function Landing() {
  return (
    <main>
      <section className="mx-auto max-w-6xl px-4 pt-16 pb-12">
        <p className="text-sm font-medium text-brand-700">Open-source portfolio project · fictional shops and data</p>
        <h1 className="mt-3 max-w-3xl text-4xl font-semibold tracking-tight sm:text-5xl">
          A multilingual support agent that answers from your data, or says it doesn't know.
        </h1>
        <p className="mt-5 max-w-2xl text-lg text-slate-600 dark:text-slate-300">
          24/7 text and voice support for e-commerce shops in Arabic, Tunisian Arabic, French and English, built with
          FastAPI, LangGraph, PostgreSQL + pgvector and React.
        </p>
        <div className="mt-8 flex flex-wrap gap-3">
          <Link to="/chat" className="rounded-lg bg-brand-700 px-5 py-2.5 text-sm font-medium text-white hover:bg-brand-800">
            Try the live demo
          </Link>
          <a href="/demo-store.html" className="rounded-lg border border-slate-300 px-5 py-2.5 text-sm font-medium hover:bg-slate-100 dark:border-slate-700 dark:hover:bg-slate-900">
            See the embedded widget
          </a>
          <Link to="/admin" className="rounded-lg px-5 py-2.5 text-sm font-medium text-slate-600 hover:text-slate-900 dark:text-slate-300">
            Admin console →
          </Link>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-4 py-10">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map(({ icon: Icon, title, text }) => (
            <Card key={title}>
              <Icon className="size-5 text-brand-700" aria-hidden />
              <h3 className="mt-3 font-semibold">{title}</h3>
              <p className="mt-1.5 text-sm text-slate-600 dark:text-slate-400">{text}</p>
            </Card>
          ))}
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-4 py-10">
        <h2 className="text-2xl font-semibold tracking-tight">How a message is handled</h2>
        <p className="mt-2 max-w-2xl text-sm text-slate-600 dark:text-slate-400">
          A LangGraph state machine. The model plans and writes; the backend decides what it is allowed to see and do,
          and checks what it wrote.
        </p>
        <ol className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
          {STEPS.map(([name, text], i) => (
            <li key={name} className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
              <span className="text-xs font-medium text-slate-400">{i + 1}</span>
              <p className="font-semibold">{name}</p>
              <p className="mt-1 text-xs text-slate-500">{text}</p>
            </li>
          ))}
        </ol>
        <div className="mt-6 grid gap-3 text-sm sm:grid-cols-3">
          <Card className="p-4">
            <p className="font-medium">Browser / widget</p>
            <p className="mt-1 text-slate-500">React app and a 1-file embeddable widget (shadow DOM)</p>
          </Card>
          <Card className="p-4">
            <p className="font-medium">FastAPI + LangGraph</p>
            <p className="mt-1 text-slate-500">Agent, tool registry (also served over MCP), guardrails, router, voice</p>
          </Card>
          <Card className="p-4">
            <p className="font-medium">PostgreSQL 18 + pgvector</p>
            <p className="mt-1 text-slate-500">Row-level security per shop, embeddings, full-text search, audit logs</p>
          </Card>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-4 py-10 pb-20">
        <h2 className="text-2xl font-semibold tracking-tight">Evaluation results</h2>
        <p className="mt-2 mb-6 max-w-2xl text-sm text-slate-600 dark:text-slate-400">
          Read live from this deployment's database: only scores from real runs are shown.
        </p>
        <EvalSummary />
      </section>
    </main>
  );
}
