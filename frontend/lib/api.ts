/** Typed client for FastAPI. All requests go through same-origin Next.js rewrites
 * (/api/* → BACKEND_URL). Credentials flow naturally; no CORS configuration needed. */

export function apiUrl(path: string): string {
  return path; // Rewrite handles URL transformation; just return the path as-is.
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
