const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? 'http://localhost:8000';
export const API_BASE = BASE;

async function request<T>(path: string, init?: RequestInit, timeoutMs = 6000): Promise<T> {
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
  health: () => request<{ status: string }>('/api/v1/healthz', undefined, 2500),
};
