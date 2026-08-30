"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

import { api } from "@/lib/api";
import { Button, Card, Input, PasswordInput } from "@/components/ui";

const PROFILE_CACHE_KEY = "ga-voiceai.employee-profile";

export default function LoginPage() {
  const router = useRouter();
  const [employeeId, setEmployeeId] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function signIn(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await api.post<{ employee_id: string; profile: { name?: string } | null }>("/api/auth/login", {
        employee_id: employeeId.trim().toUpperCase(),
        password,
      });
      if (result.profile?.name) {
        window.sessionStorage.setItem(PROFILE_CACHE_KEY, JSON.stringify(result));
      } else {
        window.sessionStorage.removeItem(PROFILE_CACHE_KEY);
      }
      router.push("/support");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Sign-in failed.");
      setBusy(false);
    }
  }

  return (
    <main className="relative flex flex-1 items-center justify-center overflow-hidden px-5 py-10 sm:p-8">
      <div className="absolute inset-0 -z-10 bg-[radial-gradient(circle_at_top_left,_rgba(79,70,229,0.10),transparent_34%),radial-gradient(circle_at_bottom_right,_rgba(14,165,233,0.08),transparent_30%)]" />
      <div className="grid w-full max-w-5xl gap-8 lg:grid-cols-[1.05fr_0.95fr] lg:gap-14">
        <section className="flex flex-col justify-center py-2 sm:py-8">
          <div className="mb-6 flex h-11 w-11 items-center justify-center rounded-xl bg-primary text-lg font-semibold text-white shadow-sm">N</div>
          <p className="text-sm font-medium text-primary">GA-VoiceAI</p>
          <h1 className="mt-2 max-w-xl text-3xl font-semibold tracking-tight sm:text-4xl">IT support that follows through.</h1>
          <p className="mt-4 max-w-xl text-base leading-7 text-muted">Describe an issue, approve only the actions you understand, and keep track of every request in one place.</p>
          <div className="mt-7 grid max-w-xl gap-3 sm:grid-cols-3">
            {[["Investigate", "Guided diagnostics"], ["Confirm", "You stay in control"], ["Track", "Clear ticket updates"]].map(([title, text]) => (
              <div key={title} className="rounded-xl border border-border-token bg-surface/70 p-3">
                <p className="text-sm font-medium">{title}</p>
                <p className="mt-1 text-xs leading-5 text-muted">{text}</p>
              </div>
            ))}
          </div>
        </section>

        <Card className="self-center p-5 shadow-sm sm:p-7">
          <div className="space-y-1">
            <h2 className="text-xl font-semibold tracking-tight">Sign in to IT Support</h2>
            <p className="text-sm text-muted">Use your GA-VoiceAI employee ID and password.</p>
          </div>
          <form className="mt-6 space-y-4" onSubmit={signIn}>
            <label className="block space-y-1.5">
              <span className="text-sm font-medium">Employee ID</span>
              <Input placeholder="EMP-032" value={employeeId} onChange={(e) => setEmployeeId(e.target.value)} autoComplete="username" autoFocus required />
            </label>
            <label className="block space-y-1.5">
              <span className="text-sm font-medium">Password</span>
              <PasswordInput placeholder="Enter your password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
            </label>
            {error && <p className="text-sm text-red-600 dark:text-red-400" role="alert">{error}</p>}
            <Button className="w-full" disabled={busy || !employeeId.trim() || !password}>{busy ? "Signing in…" : "Continue to IT Support"}</Button>
          </form>
          <div className="mt-5 border-t border-border-token pt-4 text-sm text-muted">Need a demonstration account or a quick tour? <Link className="font-medium text-primary hover:underline" href="/help">Help me</Link></div>
          <div className="mt-2 text-sm text-muted">Administrator? <Link className="font-medium text-primary hover:underline" href="/admin/login">Open Command Center sign in</Link></div>
        </Card>
      </div>
      <p className="absolute bottom-4 text-center text-xs text-muted">Fictional organization · portfolio demo · no real accounts</p>
    </main>
  );
}
