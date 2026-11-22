import clsx from "clsx";
import {
  BookOpen,
  FlaskConical,
  LayoutDashboard,
  LogOut,
  MessageSquareText,
  Moon,
  Sun,
} from "lucide-react";
import { Link, NavLink, Navigate, Outlet, useLocation } from "react-router";

import { useAuth } from "../lib/auth";
import { useI18n, type UiLanguage } from "../lib/i18n";
import { useTheme } from "../lib/theme";
import { Spinner } from "./ui";

function Logo() {
  return (
    <Link to="/" className="flex items-center gap-2 font-semibold">
      <span className="grid size-7 place-items-center rounded-lg bg-brand-700 text-white">
        <MessageSquareText className="size-4" aria-hidden />
      </span>
      <span>Support Agent</span>
    </Link>
  );
}

function Toolbar() {
  const { dark, toggle } = useTheme();
  const { lang, setLang, t } = useI18n();
  return (
    <div className="flex items-center gap-1">
      <label className="sr-only" htmlFor="ui-lang">
        {t("ui_language")}
      </label>
      <select
        id="ui-lang"
        value={lang}
        onChange={(e) => setLang(e.target.value as UiLanguage)}
        className="rounded-md border border-slate-300 bg-transparent px-2 py-1 text-sm dark:border-slate-700"
      >
        <option value="en">EN</option>
        <option value="fr">FR</option>
        <option value="ar">عربي</option>
      </select>
      <button
        type="button"
        onClick={toggle}
        aria-label={t("theme")}
        title={t("theme")}
        className="rounded-md p-2 text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
      >
        {dark ? <Sun className="size-4" /> : <Moon className="size-4" />}
      </button>
    </div>
  );
}

export function PublicLayout() {
  const { t } = useI18n();
  const link = ({ isActive }: { isActive: boolean }) =>
    clsx("rounded-md px-3 py-1.5 text-sm", isActive ? "bg-slate-100 font-medium dark:bg-slate-800" : "text-slate-600 hover:text-slate-900 dark:text-slate-300");
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/90 backdrop-blur dark:border-slate-800 dark:bg-slate-950/90">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between gap-4 px-4">
          <Logo />
          <nav className="hidden items-center gap-1 sm:flex">
            <NavLink to="/" end className={link}>
              {t("nav_home")}
            </NavLink>
            <NavLink to="/chat" className={link}>
              {t("nav_chat")}
            </NavLink>
            <a href="/demo-store.html" className="rounded-md px-3 py-1.5 text-sm text-slate-600 hover:text-slate-900 dark:text-slate-300">
              {t("nav_store")}
            </a>
            <NavLink to="/admin" className={link}>
              {t("nav_admin")}
            </NavLink>
          </nav>
          <Toolbar />
        </div>
        <nav className="flex gap-1 overflow-x-auto px-4 pb-2 sm:hidden">
          <NavLink to="/" end className={link}>
            {t("nav_home")}
          </NavLink>
          <NavLink to="/chat" className={link}>
            {t("nav_chat")}
          </NavLink>
          <NavLink to="/admin" className={link}>
            {t("nav_admin")}
          </NavLink>
        </nav>
      </header>
      <Outlet />
    </div>
  );
}

const ADMIN_LINKS = [
  { to: "/admin", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/admin/conversations", label: "Conversations", icon: MessageSquareText, end: false },
  { to: "/admin/knowledge", label: "Knowledge base", icon: BookOpen, end: false },
  { to: "/admin/evaluations", label: "Evaluations", icon: FlaskConical, end: false },
];

export function AdminLayout() {
  const { user, shop, loading, logout } = useAuth();
  const location = useLocation();
  if (loading) {
    return (
      <div className="grid min-h-screen place-items-center">
        <Spinner />
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;

  return (
    <div className="flex min-h-screen flex-col md:flex-row">
      <aside className="relative border-b border-slate-200 bg-white md:sticky md:top-0 md:h-screen md:w-60 md:shrink-0 md:border-e md:border-b-0 dark:border-slate-800 dark:bg-slate-900">
        <div className="flex h-14 items-center justify-between px-4">
          <Logo />
          <div className="flex items-center md:hidden">
            <Toolbar />
            <button onClick={logout} className="rounded-md p-2 text-slate-500" title="Sign out" aria-label="Sign out">
              <LogOut className="size-4" />
            </button>
          </div>
        </div>
        <nav className="flex gap-1 overflow-x-auto px-2 pb-2 md:flex-col md:pb-0">
          {ADMIN_LINKS.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                clsx(
                  "flex shrink-0 items-center gap-2 rounded-md px-3 py-2 text-sm",
                  isActive
                    ? "bg-brand-50 font-medium text-brand-800 dark:bg-slate-800 dark:text-brand-100"
                    : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800",
                )
              }
            >
              <Icon className="size-4" aria-hidden />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="hidden border-t border-slate-200 p-4 text-sm md:absolute md:inset-x-0 md:bottom-0 md:block dark:border-slate-800">
          <p className="font-medium">{shop?.name}</p>
          <p className="truncate text-xs text-slate-500">
            {user.full_name} · {user.role}
          </p>
          <div className="mt-3 flex items-center justify-between">
            <Toolbar />
            <button onClick={logout} className="rounded-md p-2 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800" title="Sign out" aria-label="Sign out">
              <LogOut className="size-4" />
            </button>
          </div>
        </div>
      </aside>
      <main className="min-w-0 flex-1 px-4 py-6 md:px-8">
        <Outlet />
      </main>
    </div>
  );
}
