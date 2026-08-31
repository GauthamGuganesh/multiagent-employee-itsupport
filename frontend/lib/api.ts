/** Typed client for FastAPI.
 *
 * Production (Vercel): set NEXT_PUBLIC_API_URL to the public backend origin
 * (e.g. https://your-service.onrender.com). The browser then calls the backend
 * directly with credentials; the backend allows this via CORS_ORIGINS and a
 * `Secure; SameSite=None` session cookie.
 *
 * Local dev: leave NEXT_PUBLIC_API_URL unset. Calls stay relative (`/api/*`)
 * and next.config.ts rewrites them to BACKEND_URL (default localhost:8000),
 * so they're same-origin and need no CORS. */
const API_ORIGIN = process.env.NEXT_PUBLIC_API_URL?.trim().replace(/\/+$/, "") || "";

export function apiUrl(path: string): string {
  return `${API_ORIGIN}${path}`;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(apiUrl(path), {
    ...init,
    credentials: "include", // Same-origin rewrites auto-include cookies, but be explicit.
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) }),
};

/** Identify 401s so page-level loads can return to the sign-in landing page. */
export function isAuthError(e: unknown): boolean {
  return e instanceof ApiError && e.status === 401;
}
