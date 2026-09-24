/**
 * Analyst incident queue — triage rows with cursor-paginated infinite scroll,
 * filter bar, live status strip and J/K keyboard navigation.
 */
import { useCallback, useEffect, useMemo, useRef } from 'react';
import { useIncidentQueue } from '@/services/api/useV2Queries';
import { useQueueStore } from '@/store/useQueueStore';
import { flattenQueuePages } from './queueUtils';
import { QueueFilters } from './QueueFilters';
import { IncidentRow } from './IncidentRow';
import { QueueEmptyState } from './QueueEmptyState';

export function IncidentQueue() {
  const filters = useQueueStore((s) => s.filters);
  const selectedIncidentId = useQueueStore((s) => s.selectedIncidentId);
  const selectIncident = useQueueStore((s) => s.selectIncident);
  const resetFilters = useQueueStore((s) => s.resetFilters);
  const {
    data, isLoading, isError, error,
    fetchNextPage, hasNextPage, isFetchingNextPage,
    refetch, isRefetching,
  } = useIncidentQueue(filters);

  const allIncidents = useMemo(
    () => flattenQueuePages(data?.pages),
    [data],
  );

  // Infinite scroll sentinel.
  const sentinelRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && hasNextPage && !isFetchingNextPage) {
          void fetchNextPage();
        }
      },
      { rootMargin: '200px' },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [fetchNextPage, hasNextPage, isFetchingNextPage]);

  // J/K row navigation (silent while typing).
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT'
        || t.isContentEditable)) return;
      if (allIncidents.length === 0) return;
      const idx = allIncidents.findIndex((i) => i.id === selectedIncidentId);
      if (e.key === 'j' || e.key === 'J' || e.key === 'ArrowDown') {
        e.preventDefault();
        selectIncident(allIncidents[Math.min(idx + 1, allIncidents.length - 1)]?.id ?? null);
      } else if (e.key === 'k' || e.key === 'K' || e.key === 'ArrowUp') {
        e.preventDefault();
        selectIncident(allIncidents[Math.max(idx - 1, 0)]?.id ?? null);
      }
    },
    [allIncidents, selectedIncidentId, selectIncident],
  );
  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleKeyDown]);

  return (
    <div className="flex h-full flex-col gap-2.5 p-3" role="main" aria-label="Incident Queue">
      {/* Status strip — live/simulated mode is always explicit */}
      <div className="mono flex items-center justify-between text-[9px] uppercase tracking-widest text-dim">
        <div className="flex items-center gap-2">
          <span className={`inline-block h-2 w-2 rounded-full ${isError ? 'bg-magma live-dot' : isRefetching ? 'bg-amber' : 'bg-ok'}`} aria-hidden="true" />
          <span aria-live="polite">
            {isError ? 'queue feed error — retrying'
              : isRefetching ? 'updating…'
              : `${allIncidents.length} incidents loaded`}
          </span>
        </div>
        <span>sorted by most recent</span>
      </div>

      <QueueFilters />

      {isLoading ? (
        <div className="flex-1 space-y-2" aria-label="Loading incidents">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-14 animate-pulse rounded-md border border-edge bg-panel/60" />
          ))}
        </div>
      ) : isError ? (
        <QueueEmptyState
          title="Feed unavailable"
          message={error instanceof Error ? error.message : 'Cannot reach the API'}
          actionLabel="Retry"
          onAction={() => void refetch()}
        />
      ) : allIncidents.length === 0 ? (
        <QueueEmptyState
          title={filters.status !== 'all'
            ? `No ${filters.status.replace(/_/g, ' ')} incidents`
            : 'No incidents match filters'}
          message="Try widening the filter or check if the feed is active."
          actionLabel="Reset filters"
          onAction={resetFilters}
        />
      ) : (
        <div
          className="flex-1 overflow-y-auto rounded-md border border-edge bg-panel/50"
          role="list" aria-label="Incident list"
        >
          {allIncidents.map((incident) => (
            <IncidentRow
              key={incident.id}
              incident={incident}
              selected={incident.id === selectedIncidentId}
              onSelect={() => selectIncident(incident.id)}
            />
          ))}
          <div ref={sentinelRef} className="h-8" aria-hidden="true">
            {isFetchingNextPage && (
              <div className="mono flex h-8 items-center justify-center text-[9px] uppercase tracking-widest text-dim">
                loading more…
              </div>
            )}
          </div>
        </div>
      )}

      <div className="mono flex justify-end gap-3 text-[9px] text-dim">
        <span><kbd className="rounded border border-edge2 px-1">J</kbd>/<kbd className="rounded border border-edge2 px-1">K</kbd> navigate</span>
        <span><kbd className="rounded border border-edge2 px-1">Esc</kbd> close dossier</span>
      </div>
    </div>
  );
}
