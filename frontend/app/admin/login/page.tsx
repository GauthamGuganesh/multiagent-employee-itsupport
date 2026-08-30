"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

import { api } from "@/lib/api";
import { Button, Card, Input } from "@/components/ui";

export default function AdminLoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function signIn(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post("/api/auth/admin/login", { username, password });
      router.push("/ops");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Sign-in failed.");
      setBusy(false);
    }
  }

  return (
    <main className="relative flex flex-1 items-center justify-center overflow-hidden px-5 py-10 sm:p-8">
      <div className="absolute inset-0 -z-10 bg-[radial-gradient(circle_at_top_right,_rgba(79,70,229,0.12),transparent_36%),radial-gradient(circle_at_bottom_left,_rgba(15,118,110,0.08),transparent_32%)]" />
      <Card className="w-full max-w-md p-5 shadow-sm sm:p-7">
        <Link href="/" className="text-sm font-medium text-primary hover:underline">← Employee sign in</Link>
        <div className="mt-6"><p className="text-sm font-medium text-primary">GA-VoiceAI</p><h1 className="mt-1 text-2xl font-semibold tracking-tight">Operations Command Center</h1><p className="mt-2 text-sm leading-6 text-muted">Administrator access to live sessions, tickets, approvals, escalations, and the audit timeline.</p></div>
        <form className="mt-6 space-y-4" onSubmit={signIn}>
          <label className="block space-y-1.5"><span className="text-sm font-medium">Administrator username</span><Input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required /></label>
          <label className="block space-y-1.5"><span className="text-sm font-medium">Password</span><Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" autoFocus required /></label>
          {error && <p className="text-sm text-red-600 dark:text-red-400" role="alert">{error}</p>}
          <Button className="w-full" disabled={busy || !username || !password}>{busy ? "Signing in…" : "Open Command Center"}</Button>
        </form>
        <p className="mt-5 border-t border-border-token pt-4 text-sm text-muted">Need the demo administrator credential? <Link className="font-medium text-primary hover:underline" href="/help">View Help me</Link></p>
      </Card>
    </main>
  );
}
