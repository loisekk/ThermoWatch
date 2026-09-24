/**
 * One query feeds the whole Global Watch deck: the map, the rail KPIs, the
 * donut and the recent list all read this single query.
 *
 * Key `['incidents', 'globe']` sits under the same `['incidents']` prefix the
 * queue uses, so the /v2/stream WebSocket invalidates the deck on every
 * incident/assessment event with no extra wiring.
 *
 * `status: 'all'` omits the status param (buildIncidentsQuery) — the server
 * pattern only accepts real dispositions. Dismissed incidents are dropped
 * client-side: they leave the watch floor.
 */
import { useQuery } from '@tanstack/react-query';
import { v2Api } from '@/services/api/v2Client';
import type { IncidentSummary, QueueFilters } from '@/services/api/v2Types';

/** Page size cap on `GET /v2/incidents` (limit ≤ 200) — the deck's honest ceiling. */
export const GLOBE_PAGE_LIMIT = 200;

const GLOBE_FILTERS: QueueFilters = {
  status: 'all',
  activity: 'all',
  minConfidence: null,
  timeRangeHours: null,
};

export interface GlobeFeed {
  /** Active incidents (dismissed excluded), newest activity first. */
  incidents: IncidentSummary[];
  /** Server's approximate total for the unfiltered set — drives the honesty line. */
  totalApprox: number;
}

export function useGlobeIncidents() {
  return useQuery({
    queryKey: ['incidents', 'globe'],
    queryFn: async (): Promise<GlobeFeed> => {
      const page = await v2Api.listIncidents(GLOBE_FILTERS, null, GLOBE_PAGE_LIMIT);
      return {
        incidents: page.incidents.filter((i) => i.status !== 'dismissed'),
        totalApprox: page.total_approx,
      };
    },
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
  });
}
