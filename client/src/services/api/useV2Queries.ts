/**
 * TanStack Query hooks for the v2 API — the single source of server-state
 * truth. Query keys are hierarchical so the WS stream can invalidate
 * surgically (one incident) or broadly (the whole queue).
 */
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';
import { v2Api, V2ApiError } from './v2Client';
import type { QueueFilters, ReviewRequest } from './v2Types';

// --- Query keys (hierarchical for surgical invalidation) ---
export const qk = {
  incidents: (filters: QueueFilters) => ['incidents', filters] as const,
  incident: (id: string) => ['incident', id] as const,
  health: ['health'] as const,
};

// --- Incident queue (infinite scroll with cursor pagination) ---
export function useIncidentQueue(filters: QueueFilters) {
  return useInfiniteQuery({
    queryKey: qk.incidents(filters),
    queryFn: ({ pageParam }) =>
      v2Api.listIncidents({
        status: filters.status,
        activity: filters.activity,
        minConfidence: filters.minConfidence,
        timeRangeHours: filters.timeRangeHours,
      }, pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor,
    // Near-real-time queue: light refetch cadence, paused when hidden.
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
  });
}

// --- Single incident dossier ---
export function useIncidentDossier(incidentId: string | null) {
  return useQuery({
    queryKey: qk.incident(incidentId ?? 'none'),
    queryFn: () => v2Api.getDossier(incidentId as string),
    enabled: !!incidentId,
  });
}

// --- Review mutation with optimistic-concurrency conflict handling ---
export function useSubmitReview(incidentId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ReviewRequest) => v2Api.submitReview(incidentId, body),
    onSuccess: () => {
      // Invalidate the specific incident AND the queue (disposition changed).
      void qc.invalidateQueries({ queryKey: qk.incident(incidentId) });
      void qc.invalidateQueries({ queryKey: ['incidents'] });
    },
    onError: (error: V2ApiError) => {
      if (error.status === 409) {
        // Version conflict: refetch so the UI shows the current state.
        void qc.invalidateQueries({ queryKey: qk.incident(incidentId) });
      }
      // 422 = invalid transition or note policy — surfaced inline, no refetch.
    },
  });
}

// --- Health check (status strip) ---
export function useApiHealth() {
  return useQuery({
    queryKey: qk.health,
    queryFn: () => v2Api.healthReady(),
    refetchInterval: 60_000,
    retry: 1,
  });
}
