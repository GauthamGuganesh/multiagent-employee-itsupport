"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { api } from "@/lib/api";
import { ThemeToggle } from "@/components/theme";
import { cx } from "@/components/ui";

const NAV = [
  ["/ops", "Overview"],
  ["/ops/sessions", "Live sessions"],
  ["/ops/tickets", "Tickets"],
  ["/ops/approvals", "Approvals"],
  ["/ops/escalations", "Escalations"],
  ["/ops/audit", "Audit"],
  ["/ops/org", "Organization"],
] as const;

export function OpsShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();

  async function signOut() {
    await api.post("/api/auth/logout");
    router.push("/admin/login");
  }
  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-40 border-b border-border-token bg-surface/95 backdrop-blur">
        <div className="mx-auto flex min-h-14 max-w-[1440px] items-center gap-4 px-4 sm:px-6">
          <Link href="/ops" className="flex shrink-0 items-center gap-2.5"><span className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary text-xs font-semibold text-white">GA</span><span className="text-sm font-semibold tracking-tight">GA-VoiceAI Ops</span></Link>
          <nav className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto" aria-label="Command center navigation">
            {NAV.map(([href, label]) => <Link key={href} href={href} className={cx("whitespace-nowrap rounded-lg px-2.5 py-1.5 text-sm transition-colors", pathname === href || (href !== "/ops" && pathname.startsWith(`${href}/`)) ? "bg-surface-muted font-medium text-foreground" : "text-muted hover:bg-surface-muted hover:text-foreground")}>{label}</Link>)}
          </nav>
          <ThemeToggle />
          <button onClick={signOut} className="rounded-lg px-2.5 py-1.5 text-sm text-muted transition-colors hover:bg-surface-muted hover:text-foreground">Sign out</button>
        </div>
      </header>
      {children}
    </div>
  );
}
