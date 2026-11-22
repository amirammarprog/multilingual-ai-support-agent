export function formatPercent(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

export function formatMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms)} ms`;
}

export function formatUsd(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (value === 0) return "$0";
  return value < 0.01 ? `$${value.toFixed(4)}` : `$${value.toFixed(2)}`;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function formatDateTime(iso: string | null | undefined, locale = "en"): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat(locale === "ar" ? "ar-TN" : locale, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(iso));
}

export const LANGUAGE_LABELS: Record<string, string> = {
  en: "English",
  fr: "Français",
  ar: "العربية",
  "ar-tn": "تونسي",
};
