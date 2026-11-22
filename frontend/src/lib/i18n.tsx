import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export type UiLanguage = "en" | "fr" | "ar";

const STRINGS = {
  en: {
    nav_home: "Overview", nav_chat: "Live demo", nav_store: "Demo store", nav_admin: "Admin",
    chat_title: "Customer chat", chat_placeholder: "Type your message…", chat_send: "Send",
    chat_human: "Talk to a person", chat_typing: "The assistant is typing", chat_sources: "Sources",
    chat_mic: "Record a voice message", chat_stop: "Stop recording", chat_speak: "Read replies aloud",
    chat_new: "New conversation", chat_signed_as: "Signed in as", chat_guest: "Guest visitor",
    chat_identity: "Visitor identity", chat_language: "Language", chat_auto: "Auto-detect",
    chat_empty: "Ask about an order, a product, stock, shipping, returns or warranty.",
    chat_error: "The message could not be sent.", chat_retry: "Try again", chat_escalated: "A team member will follow up.",
    chat_human_reply: "Support team", chat_rate_limited: "You are sending messages too fast. Please wait a moment.",
    chat_voice_unsupported: "Voice input is not available in this browser.",
    in_stock: "In stock", low_stock: "Low stock", out_of_stock: "Out of stock",
    theme: "Toggle dark mode", ui_language: "Interface language",
    chat_shop: "Shop", chat_try: "Try", chat_identity_hint: "Signed-in visitors are vouched for by a token signed with the shop's secret (simulated here).",
  },
  fr: {
    nav_home: "Présentation", nav_chat: "Démo en direct", nav_store: "Boutique de démo", nav_admin: "Administration",
    chat_title: "Chat client", chat_placeholder: "Écrivez votre message…", chat_send: "Envoyer",
    chat_human: "Parler à un conseiller", chat_typing: "L'assistant écrit", chat_sources: "Sources",
    chat_mic: "Enregistrer un message vocal", chat_stop: "Arrêter l'enregistrement", chat_speak: "Lire les réponses à voix haute",
    chat_new: "Nouvelle conversation", chat_signed_as: "Connecté en tant que", chat_guest: "Visiteur invité",
    chat_identity: "Identité du visiteur", chat_language: "Langue", chat_auto: "Détection automatique",
    chat_empty: "Posez une question sur une commande, un produit, le stock, la livraison, les retours ou la garantie.",
    chat_error: "Le message n'a pas pu être envoyé.", chat_retry: "Réessayer", chat_escalated: "Un conseiller va vous recontacter.",
    chat_human_reply: "Équipe support", chat_rate_limited: "Vous envoyez des messages trop vite. Patientez un instant.",
    chat_voice_unsupported: "La saisie vocale n'est pas disponible dans ce navigateur.",
    in_stock: "En stock", low_stock: "Stock faible", out_of_stock: "Rupture de stock",
    theme: "Basculer le mode sombre", ui_language: "Langue de l'interface",
    chat_shop: "Boutique", chat_try: "Essayez", chat_identity_hint: "Un visiteur connecté est garanti par un jeton signé avec le secret de la boutique (simulé ici).",
  },
  ar: {
    nav_home: "نظرة عامة", nav_chat: "تجربة مباشرة", nav_store: "متجر تجريبي", nav_admin: "الإدارة",
    chat_title: "محادثة الزبون", chat_placeholder: "اكتب رسالتك…", chat_send: "إرسال",
    chat_human: "التحدث مع موظف", chat_typing: "المساعد يكتب", chat_sources: "المصادر",
    chat_mic: "تسجيل رسالة صوتية", chat_stop: "إيقاف التسجيل", chat_speak: "قراءة الردود بصوت عالٍ",
    chat_new: "محادثة جديدة", chat_signed_as: "متصل باسم", chat_guest: "زائر",
    chat_identity: "هوية الزائر", chat_language: "اللغة", chat_auto: "اكتشاف تلقائي",
    chat_empty: "اسأل عن طلب أو منتج أو المخزون أو التوصيل أو الإرجاع أو الضمان.",
    chat_error: "تعذر إرسال الرسالة.", chat_retry: "إعادة المحاولة", chat_escalated: "سيتواصل معك أحد أعضاء الفريق.",
    chat_human_reply: "فريق الدعم", chat_rate_limited: "ترسل الرسائل بسرعة كبيرة. انتظر قليلًا من فضلك.",
    chat_voice_unsupported: "الإدخال الصوتي غير متاح في هذا المتصفح.",
    in_stock: "متوفر", low_stock: "كمية محدودة", out_of_stock: "غير متوفر",
    theme: "تبديل الوضع الداكن", ui_language: "لغة الواجهة",
    chat_shop: "المتجر", chat_try: "جرّب", chat_identity_hint: "يُثبت المتجر هوية الزائر المتصل برمز موقّع بسرّه الخاص (محاكاة هنا).",
  },
} as const;

export type MessageKey = keyof (typeof STRINGS)["en"];

interface I18nValue {
  lang: UiLanguage;
  dir: "ltr" | "rtl";
  setLang: (lang: UiLanguage) => void;
  t: (key: MessageKey) => string;
}

const I18nContext = createContext<I18nValue | null>(null);

export function translate(lang: UiLanguage, key: MessageKey): string {
  return STRINGS[lang][key] ?? STRINGS.en[key];
}

function initialLanguage(): UiLanguage {
  try {
    const saved = localStorage.getItem("ui_lang");
    if (saved === "en" || saved === "fr" || saved === "ar") return saved;
  } catch {
    /* ignore */
  }
  const nav = (navigator.language || "en").slice(0, 2);
  return nav === "fr" || nav === "ar" ? nav : "en";
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLang] = useState<UiLanguage>(initialLanguage);
  const dir = lang === "ar" ? "rtl" : "ltr";

  useEffect(() => {
    document.documentElement.lang = lang;
    document.documentElement.dir = dir;
    try {
      localStorage.setItem("ui_lang", lang);
    } catch {
      /* ignore */
    }
  }, [lang, dir]);

  const value = useMemo<I18nValue>(() => ({ lang, dir, setLang, t: (key) => translate(lang, key) }), [lang, dir]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nValue {
  const value = useContext(I18nContext);
  if (!value) throw new Error("useI18n must be used inside I18nProvider");
  return value;
}
