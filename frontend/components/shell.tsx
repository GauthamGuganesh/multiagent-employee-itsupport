"use client";

/** Employee-facing app shell: header, nav, auth hook. */
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { api, isAuthError } from "@/lib/api";
import type { Profile } from "@/lib/types";
import { ThemeToggle } from "@/components/theme";
import { cx } from "@/components/ui";

const PROFILE_CACHE_KEY = "ga-voiceai.employee-profile";

type Me = { employee_id: string; profile: Profile | null };

function cachedMe(): Me | null {
  if (typeof window === "undefined") return null;
  try {
    const stored = window.sessionStorage.getItem(PROFILE_CACHE_KEY);
    return stored ? (JSON.parse(stored) as Me) : null;
  } catch {
    return null;
  }
}

function cacheMe(value: Me) {
  if (typeof window === "undefined" || !value.profile?.name) return;
  window.sessionStorage.setItem(PROFILE_CACHE_KEY, JSON.stringify(value));
}

export function useMe() {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(cachedMe);

  useEffect(() => {
    api
      .get<Me>("/api/auth/me")
      .then((value) => {
        cacheMe(value);
        setMe(value.profile?.name ? value : (cachedMe() ?? value));
      })
      .catch((e) => {
        if (isAuthError(e)) router.replace("/");
      });
  }, [router]);

  return me;
}

export function EmployeeHeader({ employeeName }: { employeeName?: string }) {
  const pathname = usePathname();
  const router = useRouter();

  async function signOut() {
    await api.post("/api/auth/logout");
    window.sessionStorage.removeItem(PROFILE_CACHE_KEY);
    router.push("/");
  }

  const nav = [
    { href: "/support", label: "Support" },
    { href: "/requests", label: "My requests" },
  ];

  return (
    <header className="sticky top-0 z-40 border-b border-border-token bg-surface/90 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-4xl items-center justify-between gap-4 px-4">
        <div className="flex items-center gap-6">
          <Link href="/support" className="flex items-center gap-2.5">
            <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary text-sm font-semibold text-white">
              GA
            </span>
            <span className="text-sm font-semibold tracking-tight">GA-VoiceAI IT</span>
          </Link>
          <nav className="flex items-center gap-1" aria-label="Main">
            {nav.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className={cx(
                  "rounded-lg px-3 py-1.5 text-sm transition-colors",
                  pathname === item.href
                    ? "bg-surface-muted font-medium text-foreground"
                    : "text-muted hover:text-foreground"
                )}
              >
                {item.label}
              </Link>
            ))}
          </nav>
        </div>
        <div className="flex items-center gap-1.5">
          {employeeName && (
            <span className="hidden sm:block text-sm text-muted mr-1">{employeeName}</span>
          )}
          <ThemeToggle />
          <button
            onClick={signOut}
            className="rounded-lg px-3 py-1.5 text-sm text-muted hover:bg-surface-muted hover:text-foreground transition-colors"
          >
            Sign out
          </button>
        </div>
      </div>
    </header>
  );
}
