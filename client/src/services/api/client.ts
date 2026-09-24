/**
 * Single source of truth for where the API lives. One resolver feeds every
 * HTTP fetch AND both WebSocket URLs, so they can never disagree:
 *
 * - `VITE_API_URL` set   → DIRECT mode: HTTP + WS target that origin as-is.
 *   CORS applies (backend regex allow-list must cover this site), and the API
 *   origin must be https:// when the page is https (http → mixed content also
 *   manifests as "Failed to fetch").
 * - `VITE_API_URL` unset → SAME-ORIGIN mode: relative HTTP paths, WS on
 *   location.host. Dev: the Vite proxy (vite.config.ts) forwards /api, /v2,
 *   /health to 127.0.0.1:8000. Prod: vercel.json rewrites forward the same
 *   paths over HTTP — set VITE_API_URL in production if you need /v2/stream
 *   (Vercel rewrites do not proxy WebSocket upgrades).
 */
function resolveOrigins(): { http: string; ws: string } {
  const envUrl = (import.meta.env.VITE_API_URL as string | undefined)?.trim();
  if (envUrl) {
    const origin = envUrl.replace(/\/+$/, '');
    return { http: origin, ws: origin.replace(/^http/, 'ws') };
  }
  if (typeof location === 'undefined') {
    // Non-browser context (unit tests): same-origin has no host to point at.
    return { http: '', ws: 'ws://127.0.0.1:8000' };
  }
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  return { http: '', ws: `${proto}://${location.host}` };
}

const origins = resolveOrigins();

/** HTTP origin — '' means same-origin (proxied/rewritten). */
export const API_BASE = origins.http;
/** Absolute ws://|wss:// origin — the WebSocket constructor needs a full URL. */
export const WS_BASE = origins.ws;
/** Human-readable target for error banners (empty API_BASE reads badly). */
export const API_TARGET = API_BASE || 'same-origin (proxied)';

/** One-line config diagnostic for the agent header / error replies. */
export function apiDiagnostic(): string {
  return import.meta.env.VITE_API_URL
    ? `API base = ${API_BASE} (VITE_API_URL set at build — direct mode; WS ${WS_BASE})`
    : `API base = same-origin (VITE_API_URL NOT set — HTTP via this origin's proxy/rewrite, WS ${origins.ws}). For direct mode set VITE_API_URL to the backend origin.`;
}

async function request<T>(path: string, init?: RequestInit, timeoutMs = 12000): Promise<T> {
  const ctrl = new AbortController();
  const t = window.setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(`${API_BASE}${path}`, { ...init, signal: ctrl.signal, headers: { 'content-type': 'application/json', ...init?.headers } });
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
