const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? 'http://localhost:8000';
export const API_BASE = BASE;

/** One-line config diagnostic for the agent header / error replies. */
export function apiDiagnostic(): string {
  return `API base = ${BASE} (VITE_API_URL ${import.meta.env.VITE_API_URL ? 'set at build' : 'NOT set — defaulting to http://localhost:8000'})`;
}

async function request<T>(path: string, init?: RequestInit, timeoutMs = 12000): Promise<T> {
  const ctrl = new AbortController();
  const t = window.setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(`${BASE}${path}`, { ...init, signal: ctrl.signal, headers: { 'content-type': 'application/json', ...init?.headers } });
    if (!res.ok) throw new Error(`API ${res.status}`);
    return (await res.json()) as T;
  } finally { window.clearTimeout(t); }
}

export const api = {
  get: <T,>(path: string) => request<T>(path),
  post: <T,>(path: string, body: unknown) => request<T>(path, { method: 'POST', body: JSON.stringify(body) }),
  health: () => request<{ status: string }>('/api/v1/healthz', undefined, 8000),
};

/** Render free-tier cold-start resilience: retry healthz on a backoff ladder so the
 *  feed flips to LIVE when the instance wakes, instead of failing on the first probe. */
export async function waitUntilHealthy(tries = [0, 5000, 15000, 30000]): Promise<boolean> {
  for (const d of tries) {
    if (d) await new Promise((r) => setTimeout(r, d));
    try { await request('/api/v1/healthz', undefined, 25000); return true; } catch { /* retry */ }
  }
  return false;
}
