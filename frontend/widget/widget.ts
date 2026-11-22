/**
 * Embeddable support widget.
 *
 *   <script src="https://support.example.com/widget.js" data-shop-id="demo-shop" defer></script>
 *
 * Optional attributes:
 *   data-api-base        API origin (default: the origin widget.js was loaded from)
 *   data-customer-token  identity token signed by the shop's backend for a signed-in customer
 *   data-language        en | fr | ar (default: detected from each message)
 *   data-position        right | left (default: right; mirrored automatically for Arabic pages)
 *
 * The widget lives in a shadow root (no CSS leaks either way) and holds only a short-lived chat-session
 * token. The server binds that token to one shop and checks the page's origin against the shop's list.
 */

import { ApiError, ChatClient, isRtl, startRecording, textDirection, type HistoryMessage, type ProductRef, type Source } from "../src/lib/chatClient";
import { WIDGET_CSS } from "./styles";

type Lang = "en" | "fr" | "ar";

const TEXT: Record<Lang, Record<string, string>> = {
  en: { open: "Chat with us", close: "Close chat", placeholder: "Type your message…", send: "Send", human: "Talk to a person", typing: "Typing", sources: "Sources", mic: "Voice message", stop: "Stop", error: "Message not sent. Please try again.", slow: "Too many messages, please wait a moment.", escalated: "A team member will follow up", welcome: "Hello! Ask me about your order, products, shipping, returns or warranty.", unavailable: "Chat is unavailable on this site.", team: "Support team", voice_off: "Voice input is not available in this browser." },
  fr: { open: "Discuter avec nous", close: "Fermer", placeholder: "Écrivez votre message…", send: "Envoyer", human: "Parler à un conseiller", typing: "Écrit", sources: "Sources", mic: "Message vocal", stop: "Arrêter", error: "Message non envoyé. Réessayez.", slow: "Trop de messages, patientez un instant.", escalated: "Un conseiller va vous recontacter", welcome: "Bonjour ! Posez-moi vos questions sur votre commande, nos produits, la livraison, les retours ou la garantie.", unavailable: "Le chat n'est pas disponible sur ce site.", team: "Équipe support", voice_off: "La saisie vocale n'est pas disponible dans ce navigateur." },
  ar: { open: "تحدث معنا", close: "إغلاق", placeholder: "اكتب رسالتك…", send: "إرسال", human: "التحدث مع موظف", typing: "يكتب", sources: "المصادر", mic: "رسالة صوتية", stop: "إيقاف", error: "لم تُرسل الرسالة. حاول مرة أخرى.", slow: "رسائل كثيرة، انتظر قليلًا.", escalated: "سيتواصل معك أحد أعضاء الفريق", welcome: "مرحبًا! اسألني عن طلبك أو المنتجات أو التوصيل أو الإرجاع أو الضمان.", unavailable: "المحادثة غير متاحة على هذا الموقع.", team: "فريق الدعم", voice_off: "الإدخال الصوتي غير متاح في هذا المتصفح." },
};

const ICONS = {
  chat: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5h16a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H9l-5 4v-4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/></svg>',
  close: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
  send: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 12l16-8-6 16-2-7-8-1z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/></svg>',
  mic: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="3" width="6" height="11" rx="3" fill="none" stroke="currentColor" stroke-width="2"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
  stop: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor"/></svg>',
};

function el<K extends keyof HTMLElementTagNameMap>(tag: K, attrs: Record<string, string> = {}, text?: string): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (text !== undefined) node.textContent = text; // textContent only: replies are never parsed as HTML
  return node;
}

class SupportWidget {
  private client: ChatClient;
  private root: ShadowRoot;
  private panel!: HTMLDivElement;
  private log!: HTMLDivElement;
  private input!: HTMLTextAreaElement;
  private micButton!: HTMLButtonElement;
  private typing!: HTMLDivElement;
  private seen = new Set<string>();
  private started = false;
  private busy = false;
  private recorder: { stop: () => Promise<Blob> } | null = null;
  private poll: number | undefined;
  private lang: Lang;
  private storageKey: string;

  constructor(
    shop: string,
    apiBase: string,
    private customerToken: string | null,
    private fixedLanguage: Lang | null,
    position: "left" | "right",
  ) {
    this.client = new ChatClient(apiBase, shop);
    const pageLang = (document.documentElement.lang || navigator.language || "en").slice(0, 2);
    this.lang = fixedLanguage ?? (pageLang === "fr" || pageLang === "ar" ? pageLang : "en");
    this.storageKey = `support-widget:${shop}`;
    const host = el("div", { "data-support-widget": shop });
    document.body.appendChild(host);
    this.root = host.attachShadow({ mode: "closed" });
    const style = el("style");
    style.textContent = WIDGET_CSS;
    this.root.appendChild(style);
    this.build(position === "left" !== (document.documentElement.dir === "rtl") ? "left" : "right");
  }

  private t(key: string): string {
    return TEXT[this.lang][key] ?? TEXT.en[key];
  }

  private build(side: "left" | "right") {
    const launcher = el("button", { class: `launcher ${side}`, "aria-label": this.t("open"), type: "button" });
    launcher.innerHTML = ICONS.chat;
    this.panel = el("div", { class: `panel ${side}`, role: "dialog", "aria-label": this.t("open"), hidden: "" });

    const header = el("div", { class: "header" });
    const title = el("div", { class: "title" }, "…");
    const langSelect = el("select", { "aria-label": "Language" }) as HTMLSelectElement;
    for (const [code, label] of [["en", "EN"], ["fr", "FR"], ["ar", "عربي"]]) {
      const option = el("option", { value: code }, label);
      if (code === this.lang) option.selected = true;
      langSelect.appendChild(option);
    }
    langSelect.addEventListener("change", () => {
      this.lang = langSelect.value as Lang;
      this.applyDirection();
    });
    const close = el("button", { class: "icon", "aria-label": this.t("close"), type: "button" });
    close.innerHTML = ICONS.close;
    close.addEventListener("click", () => this.toggle(false));
    header.append(title, langSelect, close);

    this.log = el("div", { class: "log", "aria-live": "polite" });
    this.typing = el("div", { class: "typing", hidden: "" });
    this.typing.append(el("span"), el("span"), el("span"));

    const form = el("form", { class: "composer" });
    this.input = el("textarea", { rows: "1", dir: "auto", maxlength: "2000", "aria-label": this.t("placeholder"), placeholder: this.t("placeholder") });
    this.input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        void this.send(this.input.value);
      }
    });
    this.micButton = el("button", { class: "icon", type: "button", "aria-label": this.t("mic") });
    this.micButton.innerHTML = ICONS.mic;
    this.micButton.addEventListener("click", () => void this.toggleRecording());
    const send = el("button", { class: "send", type: "submit", "aria-label": this.t("send") });
    send.innerHTML = ICONS.send;
    form.append(this.input, this.micButton, send);
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      void this.send(this.input.value);
    });

    const footer = el("div", { class: "footer" });
    const human = el("button", { type: "button", class: "link" }, this.t("human"));
    human.addEventListener("click", () => void this.escalate());
    footer.append(human);

    this.panel.append(header, this.log, this.typing, form, footer);
    launcher.addEventListener("click", () => this.toggle(Boolean(this.panel.hidden)));
    this.root.append(launcher, this.panel);
    this.applyDirection();

    this.client.config().then((config) => {
      title.textContent = config.name;
      if (config.theme?.primary && /^#[0-9a-f]{6}$/i.test(config.theme.primary)) {
        (this.root.host as HTMLElement).style.setProperty("--sw-primary", config.theme.primary);
      }
      if (!config.voice.stt) this.micButton.hidden = true;
    }).catch(() => {
      title.textContent = "Support";
    });
  }

  private applyDirection() {
    this.panel.setAttribute("dir", isRtl(this.lang) ? "rtl" : "ltr");
    this.input.placeholder = this.t("placeholder");
  }

  private toggle(open: boolean) {
    this.panel.hidden = !open;
    if (open) {
      void this.ensureSession();
      this.input.focus();
    }
  }

  private async ensureSession() {
    if (this.started) return;
    this.started = true;
    try {
      const saved = sessionStorage.getItem(this.storageKey);
      if (saved) {
        this.client.restore(saved);
        const history = await this.client.history();
        history.forEach((m) => this.render(m));
        if (history.length === 0) this.system(this.t("welcome"));
        this.startPolling();
        return;
      }
    } catch {
      /* expired or storage blocked: start a new session */
    }
    try {
      const session = await this.client.start({ customerToken: this.customerToken, language: this.fixedLanguage });
      try {
        sessionStorage.setItem(this.storageKey, session.session_token);
      } catch {
        /* storage blocked: the conversation lasts as long as the page */
      }
      this.system(this.t("welcome"));
      this.startPolling();
    } catch (error) {
      this.started = false;
      this.system(error instanceof ApiError && error.status === 403 ? this.t("unavailable") : this.t("error"));
    }
  }

  /** Picks up replies written by a human agent in the admin console. */
  private startPolling() {
    window.clearInterval(this.poll);
    this.poll = window.setInterval(async () => {
      if (this.panel.hidden || this.busy) return;
      try {
        // Only human replies are new here: the visitor's and the assistant's messages are already shown.
        (await this.client.history()).filter((m) => m.role === "human_agent").forEach((m) => this.render(m));
      } catch {
        /* transient */
      }
    }, 10_000);
  }

  private render(m: Pick<HistoryMessage, "id" | "role" | "content" | "language"> & { sources?: Source[]; products?: ProductRef[] }) {
    if (this.seen.has(m.id)) return;
    this.seen.add(m.id);
    const row = el("div", { class: `row ${m.role === "user" ? "mine" : "theirs"}` });
    if (m.role === "human_agent") row.append(el("div", { class: "who" }, this.t("team")));
    const bubble = el("div", { class: "bubble", dir: m.language ? (isRtl(m.language) ? "rtl" : "ltr") : textDirection(m.content) }, m.content);
    row.append(bubble);
    for (const p of m.products ?? []) {
      const card = el("div", { class: "product" });
      card.append(el("strong", { dir: "auto" }, p.name ?? p.sku), el("span", {}, [p.sku, p.price ? `${p.price} ${p.currency ?? ""}` : ""].filter(Boolean).join(" · ")));
      row.append(card);
    }
    if (m.sources?.length) {
      const details = el("details", { class: "sources" });
      details.append(el("summary", {}, `${this.t("sources")} (${m.sources.length})`));
      for (const s of m.sources) details.append(el("p", { dir: "auto" }, `${s.title}${s.heading ? ` › ${s.heading}` : ""}`));
      row.append(details);
    }
    this.log.append(row);
    this.log.scrollTop = this.log.scrollHeight;
  }

  private system(text: string) {
    const row = el("div", { class: "row system" });
    row.append(el("div", { class: "bubble", dir: textDirection(text) }, text));
    this.log.append(row);
    this.log.scrollTop = this.log.scrollHeight;
  }

  private setBusy(busy: boolean) {
    this.busy = busy;
    this.typing.hidden = !busy;
  }

  private async send(text: string) {
    const message = text.trim();
    if (!message || this.busy) return;
    await this.ensureSession();
    this.input.value = "";
    this.render({ id: `local-${Date.now()}`, role: "user", content: message, language: null });
    this.setBusy(true);
    try {
      const reply = await this.client.send(message);
      this.render({ id: reply.message_id, role: "assistant", content: reply.answer, language: reply.language, sources: reply.sources, products: reply.products });
    } catch (error) {
      this.system(error instanceof ApiError && error.status === 429 ? this.t("slow") : this.t("error"));
    } finally {
      this.setBusy(false);
    }
  }

  private async toggleRecording() {
    if (this.recorder) {
      const audio = await this.recorder.stop();
      this.recorder = null;
      this.micButton.innerHTML = ICONS.mic;
      this.micButton.classList.remove("recording");
      this.setBusy(true);
      try {
        const transcript = await this.client.transcribe(audio, this.lang);
        this.setBusy(false);
        if (transcript.text) await this.send(transcript.text);
      } catch {
        this.setBusy(false);
        this.system(this.t("error"));
      }
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      this.system(this.t("voice_off"));
      return;
    }
    try {
      await this.ensureSession();
      this.recorder = await startRecording();
      this.micButton.innerHTML = ICONS.stop;
      this.micButton.classList.add("recording");
    } catch {
      this.system(this.t("voice_off"));
    }
  }

  private async escalate() {
    await this.ensureSession();
    this.setBusy(true);
    try {
      const result = await this.client.escalate("Visitor pressed the 'talk to a person' button in the widget");
      this.system(`${this.t("escalated")}${result.ticket_number ? ` (${result.ticket_number})` : ""}.`);
    } catch {
      this.system(this.t("error"));
    } finally {
      this.setBusy(false);
    }
  }
}

(function boot() {
  const script = (document.currentScript as HTMLScriptElement | null) ?? document.querySelector<HTMLScriptElement>("script[data-shop-id]");
  if (!script) return;
  const shop = script.dataset.shopId ?? "";
  if (!/^[a-z0-9-]{2,64}$/.test(shop)) {
    console.error("[support-widget] data-shop-id is missing or invalid");
    return;
  }
  const apiBase = (script.dataset.apiBase ?? new URL(script.src, location.href).origin).replace(/\/$/, "");
  const language = script.dataset.language;
  const start = () =>
    new SupportWidget(
      shop,
      apiBase,
      script.dataset.customerToken ?? null,
      language === "en" || language === "fr" || language === "ar" ? language : null,
      script.dataset.position === "left" ? "left" : "right",
    );
  if (document.body) start();
  else document.addEventListener("DOMContentLoaded", start);
})();
