import clsx from "clsx";
import { AlertTriangle, Inbox, LoaderCircle } from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";

export function Button({
  variant = "primary",
  size = "md",
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "ghost" | "danger"; size?: "sm" | "md" }) {
  return (
    <button
      className={clsx(
        "inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600 disabled:cursor-not-allowed disabled:opacity-50",
        size === "sm" ? "px-2.5 py-1.5 text-sm" : "px-4 py-2 text-sm",
        variant === "primary" && "bg-brand-700 text-white hover:bg-brand-800",
        variant === "secondary" &&
          "border border-slate-300 bg-white text-slate-800 hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:hover:bg-slate-800",
        variant === "ghost" && "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800",
        variant === "danger" && "bg-red-600 text-white hover:bg-red-700",
        className,
      )}
      {...props}
    />
  );
}

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <div className={clsx("rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900", className)}>
      {children}
    </div>
  );
}

export function CardTitle({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="mb-4 flex items-center justify-between gap-3">
      <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-200">{children}</h2>
      {action}
    </div>
  );
}

const BADGE_TONES = {
  neutral: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
  green: "bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300",
  amber: "bg-amber-50 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  red: "bg-red-50 text-red-700 dark:bg-red-950 dark:text-red-300",
  blue: "bg-sky-50 text-sky-700 dark:bg-sky-950 dark:text-sky-300",
};

export function Badge({ tone = "neutral", children }: { tone?: keyof typeof BADGE_TONES; children: ReactNode }) {
  return (
    <span className={clsx("inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium", BADGE_TONES[tone])}>
      {children}
    </span>
  );
}

export function statusTone(status: string): keyof typeof BADGE_TONES {
  if (["ready", "resolved", "answered", "success", "completed", "in_stock", "passed"].includes(status)) return "green";
  if (["pending", "processing", "open", "low_stock", "needs_info", "ticket_created", "running"].includes(status)) return "amber";
  if (["failed", "denied", "error", "refused", "out_of_stock", "invalid"].includes(status)) return "red";
  if (["escalated", "unknown", "not_found"].includes(status)) return "blue";
  return "neutral";
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-2 text-sm text-slate-500">
      <LoaderCircle className="size-4 animate-spin" aria-hidden />
      <span>{label}…</span>
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx("animate-pulse rounded-md bg-slate-200 dark:bg-slate-800", className)} />;
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-slate-300 px-6 py-12 text-center dark:border-slate-700">
      <Inbox className="size-6 text-slate-400" aria-hidden />
      <p className="font-medium text-slate-700 dark:text-slate-200">{title}</p>
      {children && <div className="max-w-md text-sm text-slate-500">{children}</div>}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message = error instanceof Error ? error.message : "Something went wrong.";
  return (
    <div role="alert" className="flex items-start gap-3 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
      <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div className="flex-1">
        <p className="font-medium">Could not load this data</p>
        <p className="mt-1 opacity-90">{message}</p>
      </div>
      {onRetry && (
        <Button size="sm" variant="secondary" onClick={onRetry}>
          Retry
        </Button>
      )}
    </div>
  );
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <Card className="p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-2 text-2xl font-semibold tabular-nums">{value}</p>
      {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
    </Card>
  );
}

export function PageHeader({ title, description, actions }: { title: string; description?: string; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-1 max-w-2xl text-sm text-slate-500">{description}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Table({ head, children }: { head: ReactNode[]; children: ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-200 text-start text-xs uppercase tracking-wide text-slate-500 dark:border-slate-800">
            {head.map((h, i) => (
              <th key={i} className="px-3 py-2 text-start font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 dark:divide-slate-800">{children}</tbody>
      </table>
    </div>
  );
}

export function Td({ children, className }: { children: ReactNode; className?: string }) {
  return <td className={clsx("px-3 py-2.5 align-top", className)}>{children}</td>;
}
