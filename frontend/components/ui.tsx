"use client";

/** Shared UI primitives — restrained enterprise system. No decorative-only
 * controls: everything rendered is functional. */
import { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, useState } from "react";

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

export function Button({
  variant = "primary",
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger" | "success";
}) {
  const styles = {
    primary:
      "bg-primary text-white hover:bg-primary-hover focus-visible:ring-indigo-400",
    secondary:
      "bg-surface border border-border-token text-foreground hover:bg-surface-muted focus-visible:ring-slate-400",
    ghost: "text-muted hover:text-foreground hover:bg-surface-muted focus-visible:ring-slate-400",
    danger: "bg-red-600 text-white hover:bg-red-700 focus-visible:ring-red-400",
    success: "bg-emerald-600 text-white hover:bg-emerald-700 focus-visible:ring-emerald-400",
  }[variant];
  return (
    <button
      className={cx(
        "inline-flex items-center justify-center gap-1.5 rounded-lg px-3.5 py-2 text-sm font-medium",
        "transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-1",
        "disabled:opacity-50 disabled:pointer-events-none",
        styles,
        className
      )}
      {...props}
    />
  );
}

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={cx(
        "w-full rounded-lg border border-border-token bg-surface px-3 py-2 text-sm",
        "placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-indigo-400/60",
        props.className
      )}
    />
  );
}

export function PasswordInput({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  const [visible, setVisible] = useState(false);
  return (
    <div className="relative">
      <Input {...props} type={visible ? "text" : "password"} className={cx("pr-11", className)} />
      <button
        type="button"
        onClick={() => setVisible((value) => !value)}
        aria-label={visible ? "Hide password" : "Show password"}
        aria-pressed={visible}
        className="absolute inset-y-0 right-0 flex w-10 items-center justify-center rounded-r-lg text-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-indigo-400"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4.5 w-4.5" aria-hidden="true">
          {visible ? (
            <><path d="M3 3l18 18" /><path d="M10.6 10.6a2 2 0 0 0 2.8 2.8" /><path d="M9.9 4.2A10.6 10.6 0 0 1 12 4c5.5 0 9.3 4.4 10 8-.3 1.4-1.1 2.8-2.2 4" /><path d="M6.1 6.1C4.3 7.5 2.9 9.7 2 12c.7 3.6 4.5 8 10 8 1.6 0 3.1-.4 4.3-1.1" /></>
          ) : (
            <><path d="M2 12s3.5-8 10-8 10 8 10 8-3.5 8-10 8S2 12 2 12Z" /><circle cx="12" cy="12" r="3" /></>
          )}
        </svg>
        <span className="sr-only">{visible ? "Hide password" : "Show password"}</span>
      </button>
    </div>
  );
}

export function Select(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      {...props}
      className={cx(
        "rounded-lg border border-border-token bg-surface px-2.5 py-1.5 text-sm text-foreground",
        "focus:outline-none focus:ring-2 focus:ring-indigo-400/60",
        props.className
      )}
    />
  );
}

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <div className={cx("rounded-xl border border-border-token bg-surface", className)}>
      {children}
    </div>
  );
}

export function Badge({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <span
      className={cx(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap",
        className ?? "bg-slate-100 text-slate-700 dark:bg-slate-500/15 dark:text-slate-300"
      )}
    >
      {children}
    </span>
  );
}

export function Spinner({ className }: { className?: string }) {
  return (
    <span
      role="status"
      aria-label="loading"
      className={cx(
        "inline-block h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-indigo-500",
        className
      )}
    />
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("animate-pulse rounded-md bg-surface-muted", className)} />;
}

export function EmptyState({
  title,
  hint,
  icon,
}: {
  title: string;
  hint?: string;
  icon?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-12 text-center">
      {icon && <div className="text-muted">{icon}</div>}
      <p className="text-sm font-medium text-foreground">{title}</p>
      {hint && <p className="text-sm text-muted max-w-sm">{hint}</p>}
    </div>
  );
}

export function ErrorState({ message, retry }: { message: string; retry?: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-12 text-center">
      <p className="text-sm font-medium text-red-600 dark:text-red-400">{message}</p>
      {retry && (
        <Button variant="secondary" onClick={retry}>
          Try again
        </Button>
      )}
    </div>
  );
}

export function Drawer({
  open,
  onClose,
  title,
  children,
  wide,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  children: ReactNode;
  wide?: boolean;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50" role="dialog" aria-modal="true">
      <div
        className="absolute inset-0 bg-slate-900/40 dark:bg-black/60"
        onClick={onClose}
        aria-hidden
      />
      <div
        className={cx(
          "absolute right-0 top-0 h-full overflow-y-auto bg-surface border-l border-border-token shadow-xl",
          wide ? "w-full max-w-3xl" : "w-full max-w-xl"
        )}
      >
        <div className="sticky top-0 z-10 flex items-center justify-between gap-4 border-b border-border-token bg-surface px-5 py-3">
          <h2 className="text-sm font-semibold truncate">{title}</h2>
          <button
            onClick={onClose}
            aria-label="Close panel"
            className="rounded-md p-1.5 text-muted hover:bg-surface-muted hover:text-foreground"
          >
            ✕
          </button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}
