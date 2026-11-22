import { useQuery } from "@tanstack/react-query";
import { RotateCcw, UserRound } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { ChatPanel, type ChatItem } from "../components/ChatPanel";
import { Button, Card, ErrorState, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { ChatClient, type Language } from "../lib/chatClient";
import { useI18n } from "../lib/i18n";

const SHOPS = [
  { slug: "demo-shop", label: "Brightcart Electronics (TND)" },
  { slug: "casa-lumo", label: "Casa Lumo Home (EUR)" },
];

const SUGGESTIONS: Record<string, string[]> = {
  "demo-shop": [
    "Where is my order BC-10421?",
    "Est-ce que le Orbix X5 256 Go est disponible ?",
    "كم مدة الضمان على الحواسيب المحمولة؟",
    "chnowa el prix mta3 Tessio ANC 700?",
    "Can I return headphones I already opened?",
  ],
  "casa-lumo": ["Quel est le délai de retour ?", "Do you deliver outside France?"],
};

/** The customer view of the agent: pick a demo shop and visitor, then chat (text or voice). */
export default function ChatPage() {
  const { t, lang } = useI18n();
  const [shop, setShop] = useState("demo-shop");
  const [customer, setCustomer] = useState<string>("BC-C-1001");
  const [language, setLanguage] = useState<Language | "">("");
  const [items, setItems] = useState<ChatItem[]>([]);
  const [customerName, setCustomerName] = useState<string | null>(null);
  const [startError, setStartError] = useState<unknown>(null);
  const [ready, setReady] = useState(false);
  const [round, setRound] = useState(0);
  const [queued, setQueued] = useState<string | null>(null);

  const client = useMemo(() => new ChatClient("", shop), [shop]);
  const customers = useQuery({
    queryKey: ["demo-customers", shop],
    queryFn: () => api<{ external_ref: string; name: string }[]>(`/api/v1/demo/customers?shop=${shop}`),
  });

  const start = useCallback(async () => {
    setReady(false);
    setStartError(null);
    setItems([]);
    try {
      let customerToken: string | null = null;
      if (customer) {
        const identity = await api<{ customer_token: string }>("/api/v1/demo/identity", {
          method: "POST",
          body: JSON.stringify({ shop, external_ref: customer }),
        });
        customerToken = identity.customer_token;
      }
      const session = await client.start({ customerToken, language: language || null });
      setCustomerName(session.customer_name);
      setReady(true);
    } catch (error) {
      setStartError(error);
    }
  }, [client, customer, language, shop]);

  useEffect(() => {
    void start();
    // A new session only when the shop, the visitor identity or "new conversation" changes.
  }, [client, customer, round]);

  return (
    <main className="mx-auto grid max-w-6xl gap-6 px-4 py-8 lg:grid-cols-[1fr_320px]">
      <Card className="flex h-[70vh] min-h-[520px] flex-col p-0">
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3 dark:border-slate-800">
          <div>
            <h1 className="font-semibold">{t("chat_title")}</h1>
            <p className="flex items-center gap-1 text-xs text-slate-500">
              <UserRound className="size-3.5" aria-hidden />
              {customerName ? `${t("chat_signed_as")} ${customerName}` : t("chat_guest")}
            </p>
          </div>
          <Button size="sm" variant="secondary" onClick={() => setRound((r) => r + 1)}>
            <RotateCcw className="size-3.5" /> {t("chat_new")}
          </Button>
        </div>
        {startError ? (
          <div className="p-4">
            <ErrorState error={startError} onRetry={() => void start()} />
          </div>
        ) : !ready && items.length === 0 ? (
          <div className="grid flex-1 place-items-center">
            <Spinner />
          </div>
        ) : (
          <ChatPanel
            client={client}
            items={items}
            onItems={setItems}
            ready={ready}
            className="flex-1"
            queued={queued}
            onQueuedSent={() => setQueued(null)}
          />
        )}
      </Card>

      <aside className="space-y-4">
        <Card>
          <div className="space-y-4 text-sm">
            <label className="block">
              <span className="mb-1 block font-medium">{t("chat_shop")}</span>
              <select value={shop} onChange={(e) => { setShop(e.target.value); setCustomer(""); }} className="w-full rounded-md border border-slate-300 bg-transparent px-2 py-1.5 dark:border-slate-700">
                {SHOPS.map((s) => (
                  <option key={s.slug} value={s.slug}>{s.label}</option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className="mb-1 block font-medium">{t("chat_identity")}</span>
              <select value={customer} onChange={(e) => setCustomer(e.target.value)} className="w-full rounded-md border border-slate-300 bg-transparent px-2 py-1.5 dark:border-slate-700">
                <option value="">{t("chat_guest")}</option>
                {customers.data?.map((c) => (
                  <option key={c.external_ref} value={c.external_ref}>{c.name} ({c.external_ref})</option>
                ))}
              </select>
              <span className="mt-1 block text-xs text-slate-500">{t("chat_identity_hint")}</span>
            </label>
            <label className="block">
              <span className="mb-1 block font-medium">{t("chat_language")}</span>
              <select value={language} onChange={(e) => setLanguage(e.target.value as Language | "")} className="w-full rounded-md border border-slate-300 bg-transparent px-2 py-1.5 dark:border-slate-700">
                <option value="">{t("chat_auto")}</option>
                <option value="en">English</option>
                <option value="fr">Français</option>
                <option value="ar">العربية</option>
              </select>
            </label>
          </div>
        </Card>
        <Card>
          <p className="mb-2 text-sm font-medium">{t("chat_try")}</p>
          <ul className="space-y-1.5" dir={lang === "ar" ? "rtl" : "ltr"}>
            {(SUGGESTIONS[shop] ?? []).map((s) => (
              <li key={s}>
                <button
                  dir="auto"
                  className="w-full rounded-md border border-slate-200 px-2.5 py-1.5 text-start text-sm hover:border-brand-600 dark:border-slate-700"
                  onClick={() => setQueued(s)}
                  disabled={!ready}
                >
                  {s}
                </button>
              </li>
            ))}
          </ul>
        </Card>
      </aside>
    </main>
  );
}
