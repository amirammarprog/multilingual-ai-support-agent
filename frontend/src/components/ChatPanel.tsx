import clsx from "clsx";
import { FileText, Headset, Mic, Package, SendHorizontal, Square, Volume2, VolumeX } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";

import {
  ApiError,
  ChatClient,
  isRtl,
  startRecording,
  textDirection,
  type ProductRef,
  type Source,
} from "../lib/chatClient";
import { useI18n, type MessageKey } from "../lib/i18n";
import { Badge, statusTone } from "./ui";

export interface ChatItem {
  id: string;
  role: "user" | "assistant" | "human_agent" | "system";
  content: string;
  language?: string | null;
  outcome?: string | null;
  sources?: Source[];
  products?: ProductRef[];
  latencyMs?: number;
}

function Bubble({ item }: { item: ChatItem }) {
  const { t } = useI18n();
  const mine = item.role === "user";
  const dir = item.language ? (isRtl(item.language) ? "rtl" : "ltr") : textDirection(item.content);
  return (
    <div className={clsx("flex flex-col gap-1.5", mine ? "items-end" : "items-start")}>
      {item.role === "human_agent" && <span className="text-xs font-medium text-brand-700">{t("chat_human_reply")}</span>}
      <div
        dir={dir}
        lang={item.language?.split("-")[0] ?? undefined}
        className={clsx(
          "max-w-[85%] whitespace-pre-wrap rounded-2xl px-4 py-2.5 text-[15px] leading-relaxed",
          mine
            ? "bg-brand-700 text-white"
            : item.role === "system"
              ? "border border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200"
              : "border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-800",
        )}
      >
        {item.content}
      </div>
      {!!item.products?.length && (
        <div className="flex max-w-[85%] flex-wrap gap-2">
          {item.products.map((p) => (
            <div key={p.sku} className="flex min-w-44 items-start gap-2 rounded-lg border border-slate-200 bg-white p-2.5 text-xs dark:border-slate-700 dark:bg-slate-900">
              <Package className="mt-0.5 size-4 shrink-0 text-slate-400" aria-hidden />
              <div className="min-w-0">
                <p dir="auto" className="truncate font-medium">{p.name ?? p.sku}</p>
                <p className="text-slate-500">{p.sku}</p>
                <div className="mt-1 flex items-center gap-2">
                  {p.price && (
                    <span className="font-semibold tabular-nums">
                      {p.price} {p.currency}
                    </span>
                  )}
                  {p.stock_status && <Badge tone={statusTone(p.stock_status)}>{t(p.stock_status as MessageKey)}</Badge>}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
      {!!item.sources?.length && (
        <details className="max-w-[85%] text-xs text-slate-500">
          <summary className="cursor-pointer select-none">
            {t("chat_sources")} ({item.sources.length})
          </summary>
          <ul className="mt-1.5 space-y-1.5">
            {item.sources.map((s) => (
              <li key={s.id} className="rounded-md border border-slate-200 p-2 dark:border-slate-700">
                <p dir="auto" className="flex items-center gap-1 font-medium text-slate-700 dark:text-slate-200">
                  <FileText className="size-3.5" aria-hidden /> {s.title}
                </p>
                {s.heading && <p dir="auto" className="text-slate-500">{s.heading}</p>}
                <p dir="auto" className="mt-1 line-clamp-3">{s.snippet}</p>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function Typing() {
  const { t } = useI18n();
  return (
    <div className="flex items-center gap-2 text-sm text-slate-500" role="status" aria-live="polite">
      <span className="flex gap-1" aria-hidden>
        {[0, 150, 300].map((d) => (
          <span key={d} className="size-1.5 animate-bounce rounded-full bg-slate-400" style={{ animationDelay: `${d}ms` }} />
        ))}
      </span>
      {t("chat_typing")}
    </div>
  );
}

export function ChatPanel({
  client,
  items,
  onItems,
  ready,
  className,
  queued,
  onQueuedSent,
}: {
  client: ChatClient;
  items: ChatItem[];
  onItems: (update: (items: ChatItem[]) => ChatItem[]) => void;
  ready: boolean;
  className?: string;
  /** A message to send as soon as possible (e.g. a clicked suggestion). */
  queued?: string | null;
  onQueuedSent?: () => void;
}) {
  const { t, lang } = useI18n();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [speak, setSpeak] = useState(false);
  const [recording, setRecording] = useState<{ stop: () => Promise<Blob> } | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" }), [items, busy]);

  const push = (item: ChatItem) => onItems((prev) => [...prev, item]);

  useEffect(() => {
    if (queued && ready && !busy) {
      onQueuedSent?.();
      void send(queued);
    }
  }, [queued, ready]);

  async function send(message: string) {
    const trimmed = message.trim();
    if (!trimmed || busy || !ready) return;
    setBusy(true);
    setFailed(null);
    push({ id: crypto.randomUUID(), role: "user", content: trimmed });
    setText("");
    try {
      const reply = await client.send(trimmed);
      push({
        id: reply.message_id,
        role: "assistant",
        content: reply.answer,
        language: reply.language,
        outcome: reply.outcome,
        sources: reply.sources,
        products: reply.products,
        latencyMs: reply.latency_ms,
      });
      if (speak) client.speak(reply.answer, reply.language).catch(() => undefined);
    } catch (error) {
      const rateLimited = error instanceof ApiError && error.status === 429;
      push({ id: crypto.randomUUID(), role: "system", content: rateLimited ? t("chat_rate_limited") : t("chat_error") });
      setFailed(trimmed);
    } finally {
      setBusy(false);
    }
  }

  async function toggleRecording() {
    if (recording) {
      const audio = await recording.stop();
      setRecording(null);
      setBusy(true);
      try {
        const transcript = await client.transcribe(audio, lang);
        setBusy(false);
        if (transcript.text) await send(transcript.text);
      } catch {
        setBusy(false);
        push({ id: crypto.randomUUID(), role: "system", content: t("chat_error") });
      }
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      push({ id: crypto.randomUUID(), role: "system", content: t("chat_voice_unsupported") });
      return;
    }
    try {
      setRecording(await startRecording());
    } catch {
      push({ id: crypto.randomUUID(), role: "system", content: t("chat_voice_unsupported") });
    }
  }

  async function escalate() {
    setBusy(true);
    try {
      const result = await client.escalate();
      push({
        id: crypto.randomUUID(),
        role: "system",
        content: `${t("chat_escalated")}${result.ticket_number ? ` (${result.ticket_number})` : ""}`,
      });
    } catch {
      push({ id: crypto.randomUUID(), role: "system", content: t("chat_error") });
    } finally {
      setBusy(false);
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void send(text);
  }

  return (
    <div className={clsx("flex min-h-0 flex-col", className)}>
      <div className="flex-1 space-y-4 overflow-y-auto p-4" aria-live="polite">
        {items.length === 0 && <p className="mx-auto max-w-sm pt-10 text-center text-sm text-slate-500">{t("chat_empty")}</p>}
        {items.map((item) => (
          <Bubble key={item.id} item={item} />
        ))}
        {busy && <Typing />}
        {failed && !busy && (
          <button className="text-sm font-medium text-brand-700 underline" onClick={() => void send(failed)}>
            {t("chat_retry")}
          </button>
        )}
        <div ref={endRef} />
      </div>
      <form onSubmit={onSubmit} className="border-t border-slate-200 p-3 dark:border-slate-800">
        <div className="flex items-end gap-2">
          <textarea
            dir="auto"
            rows={1}
            value={text}
            maxLength={2000}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send(text);
              }
            }}
            placeholder={t("chat_placeholder")}
            aria-label={t("chat_placeholder")}
            className="max-h-32 min-h-10 flex-1 resize-none rounded-lg border border-slate-300 bg-white px-3 py-2 text-[15px] outline-none focus:border-brand-600 dark:border-slate-700 dark:bg-slate-900"
          />
          <button
            type="button"
            onClick={() => void toggleRecording()}
            disabled={!ready || (busy && !recording)}
            aria-label={recording ? t("chat_stop") : t("chat_mic")}
            title={recording ? t("chat_stop") : t("chat_mic")}
            className={clsx(
              "grid size-10 place-items-center rounded-lg border disabled:opacity-50",
              recording ? "border-red-300 bg-red-50 text-red-600" : "border-slate-300 text-slate-600 dark:border-slate-700 dark:text-slate-300",
            )}
          >
            {recording ? <Square className="size-4" /> : <Mic className="size-4" />}
          </button>
          <button
            type="submit"
            disabled={!ready || busy || !text.trim()}
            aria-label={t("chat_send")}
            className="grid size-10 place-items-center rounded-lg bg-brand-700 text-white hover:bg-brand-800 disabled:opacity-50"
          >
            <SendHorizontal className="size-4 rtl:-scale-x-100" />
          </button>
        </div>
        <div className="mt-2 flex items-center justify-between text-xs">
          <button type="button" onClick={() => void escalate()} disabled={!ready || busy} className="flex items-center gap-1 text-slate-600 hover:text-brand-700 disabled:opacity-50 dark:text-slate-300">
            <Headset className="size-3.5" aria-hidden /> {t("chat_human")}
          </button>
          <button type="button" onClick={() => setSpeak((s) => !s)} aria-pressed={speak} className="flex items-center gap-1 text-slate-600 hover:text-brand-700 dark:text-slate-300">
            {speak ? <Volume2 className="size-3.5" /> : <VolumeX className="size-3.5" />} {t("chat_speak")}
          </button>
        </div>
      </form>
    </div>
  );
}
