import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router";

import { Button, Card } from "../components/ui";
import { useAuth } from "../lib/auth";

export default function Login() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("admin@brightcart.example.com");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const target = (location.state as { from?: string } | null)?.from ?? "/admin";

  if (user) return <Navigate to={target} replace />;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
      navigate(target, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="grid min-h-[80vh] place-items-center px-4">
      <Card className="w-full max-w-sm">
        <h1 className="text-lg font-semibold">Admin sign-in</h1>
        <p className="mt-1 text-sm text-slate-500">
          Demo accounts are listed in the README (fictional shops only).
        </p>
        <form onSubmit={onSubmit} className="mt-6 space-y-4">
          <label className="block text-sm">
            <span className="mb-1 block font-medium">E-mail</span>
            <input type="email" required autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} className="w-full rounded-md border border-slate-300 bg-transparent px-3 py-2 dark:border-slate-700" />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium">Password</span>
            <input type="password" required autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} className="w-full rounded-md border border-slate-300 bg-transparent px-3 py-2 dark:border-slate-700" />
          </label>
          {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
          <Button type="submit" disabled={busy} className="w-full">
            {busy ? "Signing in…" : "Sign in"}
          </Button>
        </form>
      </Card>
    </main>
  );
}
