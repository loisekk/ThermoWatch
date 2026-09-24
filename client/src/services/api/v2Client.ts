/**
 * Typed API client for the v2 Phase-4 endpoints. Thin on purpose —
 * TanStack Query owns caching/retry/refetch; this layer only speaks HTTP.
 *
 * NOTE: the FastAPI v2 router is mounted at `/v2` (settings.api_v2), not
 * `/api/v2` — see app/main.py. Health endpoints live at the app root.
 */
import { API_BASE, WS_BASE } from './client';
import type {
  IncidentDossier,
  IncidentListResponse,
  QueueFilters,
  ReviewRequest,
  ReviewResponse,
  TimelineResponse,
} from './v2Types';

const V2_BASE = `${API_BASE}/v2`;
/** v2 stream WS URL — derived from the same resolver as V2_BASE (client.ts)
 *  so HTTP and WS targets always agree in both direct and same-origin modes. */
export const V2_STREAM_URL = `${WS_BASE}/v2/stream`;

export class V2ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown, message: string) {
    super(message);
    this.name = 'V2ApiError';
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(path: string, init?: RequestInit, timeoutMs = 12000): Promise<T> {
  const ctrl = new AbortController();
  const t = window.setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(`${V2_BASE}${path}`, {
      ...init,
      signal: ctrl.signal,
      headers: { 'content-type': 'application/json', ...init?.headers },
    });
    if (!res.ok) {
      const body = (await res.json().catch(() => ({}))) as { detail?: unknown };
      throw new V2ApiError(res.status, body.detail ?? null, `API ${res.status}: ${path}`);
    }
    return (await res.json()) as T;
  } catch (e) {
    if (e instanceof V2ApiError) throw e;
    // Aborted request (timeout) — the outcome is unknown, never auto-retried.
    if (e instanceof DOMException && e.name === 'AbortError') {
      throw new V2ApiError(0, null, `API timeout: ${path}`);
    }
    throw e;
  } finally {
    window.clearTimeout(t);
  }
}

/** Build the queue query string from UI filters (pure — unit-tested). */
export function buildIncidentsQuery(
  filters: QueueFilters,
  cursor?: string | null,
  limit = 50,
): string {
  const qs = new URLSearchParams();
  if (filters.status && filters.status !== 'all') qs.set('status', filters.status);
  if (filters.activity && filters.activity !== 'all') qs.set('activity', filters.activity);
  if (filters.minConfidence !== null && filters.minConfidence > 0) {
    qs.set('min_confidence', String(filters.minConfidence));
  }
  if (filters.timeRangeHours !== null && filters.timeRangeHours > 0) {
    const start = new Date(Date.now() - filters.timeRangeHours * 3_600_000);
    qs.set('start_time', start.toISOString());
  }
  if (cursor) qs.set('cursor', cursor);
  qs.set('limit', String(limit));
  return qs.toString();
}

export const v2Api = {
  listIncidents: (
    filters: QueueFilters,
    cursor?: string | null,
    limit?: number,
  ): Promise<IncidentListResponse> =>
    request(`/incidents?${buildIncidentsQuery(filters, cursor, limit)}`),

  getDossier: (incidentId: string): Promise<IncidentDossier> =>
    request(`/incidents/${incidentId}`),

  getTimeline: (incidentId: string, cursor?: string | null): Promise<TimelineResponse> =>
    request(`/incidents/${incidentId}/timeline${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''}`),

  submitReview: (incidentId: string, body: ReviewRequest): Promise<ReviewResponse> =>
    request(`/incidents/${incidentId}/reviews`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  getReportUrl: (incidentId: string): string =>
    `${V2_BASE}/incidents/${incidentId}/report`,

  healthReady: (): Promise<{ status: string; database?: string }> =>
    fetch(`${API_BASE}/health/ready`, { signal: AbortSignal.timeout(8000) }).then((r) => {
      if (!r.ok) throw new V2ApiError(r.status, null, `health ${r.status}`);
      return r.json() as Promise<{ status: string; database?: string }>;
    }),

  healthLive: (): Promise<{ status: string }> =>
    fetch(`${API_BASE}/health/live`, { signal: AbortSignal.timeout(4000) }).then((r) => {
      if (!r.ok) throw new V2ApiError(r.status, null, `health ${r.status}`);
      return r.json() as Promise<{ status: string }>;
    }),
};
