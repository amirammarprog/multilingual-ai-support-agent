/**
 * Framework-free client for the customer chat API. Used by the React chat page and by the
 * embeddable widget (which ships without React).
 */

export type Language = "en" | "fr" | "ar";

export interface Source {
  id: string;
  document_id: string;
  title: string;
  heading: string;
  snippet: string;
  score: number;
}

export interface ProductRef {
  sku: string;
  name?: string | null;
  price?: string | null;
  currency?: string | null;
  stock_status?: string | null;
}

export interface ChatReply {
  conversation_id: string;
  message_id: string;
  answer: string;
  language: string;
  outcome: string;
  sources: Source[];
  products: ProductRef[];
  latency_ms: number;
  escalated: boolean;
}

export interface HistoryMessage {
  id: string;
  role: "user" | "assistant" | "human_agent";
  content: string;
  language: string | null;
  created_at: string;
  sources: Source[];
  products: ProductRef[];
  outcome: string | null;
}

export interface WidgetConfig {
  shop: string;
  name: string;
  languages: string[];
  default_language: string;
  theme: { primary?: string };
  support_hours: Record<string, string>;
  voice: { stt: boolean; tts: string };
}

export interface ChatSession {
  session_token: string;
  conversation_id: string;
  expires_in: number;
  customer_name: string | null;
  shop_name: string;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public retryAfter?: number,
  ) {
    super(message);
  }
}

/** Arabic (incl. "ar-tn") is written right to left. */
export function isRtl(language: string | null | undefined): boolean {
  return (language ?? "").split("-")[0] === "ar";
}

/** Direction of a piece of text from its first strong character (for messages of unknown language). */
export function textDirection(text: string): "rtl" | "ltr" {
  const match = text.match(/[A-Za-zÀ-ɏ؀-ۿ]/);
  return match && /[؀-ۿ]/.test(match[0]) ? "rtl" : "ltr";
}

export class ChatClient {
  private token: string | null = null;

  constructor(
    private readonly apiBase: string,
    private readonly shop: string,
  ) {}

  get sessionToken(): string | null {
    return this.token;
  }

  restore(token: string): void {
    this.token = token;
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const headers = new Headers(init.headers);
    if (this.token) headers.set("authorization", `Bearer ${this.token}`);
    if (init.body && !(init.body instanceof FormData)) headers.set("content-type", "application/json");
    const response = await fetch(`${this.apiBase}${path}`, { ...init, headers });
    if (!response.ok) {
      let code = "http_error";
      let message = response.statusText;
      try {
        const body = await response.json();
        code = body?.error?.code ?? code;
        message = body?.error?.message ?? message;
      } catch {
        /* not JSON */
      }
      const retry = Number(response.headers.get("retry-after") ?? "") || undefined;
      throw new ApiError(response.status, code, message, retry);
    }
    const type = response.headers.get("content-type") ?? "";
    return (type.includes("application/json") ? response.json() : response.blob()) as Promise<T>;
  }

  config(): Promise<WidgetConfig> {
    return this.request(`/api/v1/widget/config?shop=${encodeURIComponent(this.shop)}`);
  }

  async start(options: { customerToken?: string | null; language?: Language | null } = {}): Promise<ChatSession> {
    const session = await this.request<ChatSession>("/api/v1/widget/sessions", {
      method: "POST",
      body: JSON.stringify({
        shop: this.shop,
        ...(options.customerToken ? { customer_token: options.customerToken } : {}),
        ...(options.language ? { language: options.language } : {}),
      }),
    });
    this.token = session.session_token;
    return session;
  }

  send(message: string): Promise<ChatReply> {
    return this.request("/api/v1/chat/messages", { method: "POST", body: JSON.stringify({ message }) });
  }

  history(): Promise<HistoryMessage[]> {
    return this.request("/api/v1/chat/messages");
  }

  escalate(reason?: string): Promise<{ ok: boolean; ticket_number?: string; reply_within_hours?: number }> {
    return this.request("/api/v1/chat/escalate", { method: "POST", body: JSON.stringify(reason ? { reason } : {}) });
  }

  async transcribe(audio: Blob, languageHint?: string): Promise<{ text: string; language: string | null }> {
    const form = new FormData();
    form.append("audio", audio, "recording.webm");
    return this.request("/api/v1/voice/transcribe", {
      method: "POST",
      body: form,
      headers: languageHint ? { "x-language-hint": languageHint } : {},
    });
  }

  /** Server TTS when configured, otherwise the browser's own speech synthesis. */
  async speak(text: string, language: string): Promise<void> {
    const result = await this.request<Blob | { provider: string }>("/api/v1/voice/speak", {
      method: "POST",
      body: JSON.stringify({ text: text.slice(0, 2000), language: language === "ar-tn" ? "ar-tn" : language.split("-")[0] }),
    });
    if (result instanceof Blob) {
      const url = URL.createObjectURL(result);
      const audio = new Audio(url);
      audio.onended = () => URL.revokeObjectURL(url);
      await audio.play();
      return;
    }
    browserSpeak(text, language);
  }
}

const SPEECH_LANG: Record<string, string> = { en: "en-US", fr: "fr-FR", ar: "ar-SA", "ar-tn": "ar-TN" };

export function browserSpeak(text: string, language: string): boolean {
  if (typeof window === "undefined" || !("speechSynthesis" in window)) return false;
  const utterance = new SpeechSynthesisUtterance(text);
  const wanted = SPEECH_LANG[language] ?? SPEECH_LANG[language.split("-")[0]] ?? "en-US";
  utterance.lang = wanted;
  const voice = window.speechSynthesis.getVoices().find((v) => v.lang.startsWith(wanted.split("-")[0]));
  if (voice) utterance.voice = voice;
  window.speechSynthesis.cancel();
  window.speechSynthesis.speak(utterance);
  return true;
}

/** Records microphone audio until stop() is called. */
export async function startRecording(maxSeconds = 30): Promise<{ stop: () => Promise<Blob> }> {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const mime = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg", "audio/mp4"].find((m) => MediaRecorder.isTypeSupported(m));
  const recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
  const chunks: BlobPart[] = [];
  recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
  recorder.start();
  const timer = setTimeout(() => recorder.state === "recording" && recorder.stop(), maxSeconds * 1000);
  return {
    stop: () =>
      new Promise<Blob>((resolve) => {
        recorder.onstop = () => {
          clearTimeout(timer);
          stream.getTracks().forEach((t) => t.stop());
          resolve(new Blob(chunks, { type: (recorder.mimeType || "audio/webm").split(";")[0] }));
        };
        if (recorder.state === "recording") recorder.stop();
        else recorder.onstop?.(new Event("stop"));
      }),
  };
}
