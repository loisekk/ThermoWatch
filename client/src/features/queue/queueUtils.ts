/**
 * Pure queue helpers — node-testable (no React, no fetch).
 */
import type { IncidentListResponse, IncidentSummary, StreamEvent } from '@/services/api/v2Types';

/** Flatten infinite-query pages into a single deduplicated row list. */
export function flattenQueuePages(
  pages: IncidentListResponse[] | undefined,
): IncidentSummary[] {
  if (!pages) return [];
  const seen = new Set<string>();
  const rows: IncidentSummary[] = [];
  for (const page of pages) {
    for (const inc of page.incidents) {
      if (!seen.has(inc.id)) {
        seen.add(inc.id);
        rows.push(inc);
      }
    }
  }
  return rows;
}

/**
 * Map a WS stream event to the query-cache keys it invalidates.
 * Unknown event types are ignored (forward-compatible).
 */
export function routeStreamEvent(
  event: Pick<StreamEvent, 'event_type' | 'entity_type' | 'entity_id'>,
): { queryKey: unknown[] }[] {
  switch (event.event_type) {
    case 'incident.created':
    case 'incident.updated':
    case 'incident.reviewed':
      return event.entity_type === 'incident'
        ? [
            { queryKey: ['incidents'] },
            { queryKey: ['incident', event.entity_id] },
          ]
        : [{ queryKey: ['incidents'] }];
    case 'assessment.created':
      return [
        { queryKey: ['incident', event.entity_id] },
        { queryKey: ['incidents'] },
      ];
    default:
      return [];
  }
}

/**
 * Monotonic sequence gate for the live WS stream: skip replays and
 * out-of-order frames. The baseline resets on reconnect (resync covers gaps).
 */
export function shouldProcessSequence(sequence: number, lastSeen: number): boolean {
  return sequence > lastSeen;
}

/** Human freshness label for a queue row timestamp. */
export function freshnessLabel(iso: string, now = Date.now()): string {
  const hoursAgo = Math.round((now - new Date(iso).getTime()) / 3_600_000);
  if (hoursAgo < 1) return '<1h ago';
  if (hoursAgo < 24) return `${hoursAgo}h ago`;
  return `${Math.round(hoursAgo / 24)}d ago`;
}
