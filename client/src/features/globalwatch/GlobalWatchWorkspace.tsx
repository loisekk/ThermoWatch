/**
 * Global Watch workspace — the home deck: live rail (left), full-bleed globe
 * stage (center), and the existing instrument-laden dossier as a slide-over
 * that leaves the globe animating behind it.
 *
 * Selection is the queue's own `selectedIncidentId`, so the globe and the queue
 * are two entry points to one selection model — pick on the globe, review in
 * the dossier, and the queue's Q workspace shows the same incident selected.
 */
import { useEffect } from 'react';
import { useQueueStore } from '@/store/useQueueStore';
import { IncidentDossier } from '@/features/dossier/IncidentDossier';
import { GlobalWatchGlobe } from './GlobalWatchGlobe';
import { GlobalWatchRail } from './GlobalWatchRail';
import { useGlobeIncidents } from './useGlobeIncidents';
import { incidentCode } from './incidentDisplay';

export function GlobalWatchWorkspace() {
  const { data, dataUpdatedAt, isLoading, isError, refetch } = useGlobeIncidents();
  const selectedIncidentId = useQueueStore((s) => s.selectedIncidentId);
  const selectIncident = useQueueStore((s) => s.selectIncident);
  const incidents = data?.incidents ?? [];

  // Escape closes the dossier (mirrors the queue workspace's contract).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') selectIncident(null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [selectIncident]);

  return (
    <div className="relative flex h-full w-full overflow-hidden">
      <GlobalWatchRail
        incidents={incidents}
        totalApprox={data?.totalApprox ?? 0}
        dataUpdatedAt={dataUpdatedAt}
        loading={isLoading}
        selectedId={selectedIncidentId}
        onSelect={selectIncident}
      />

      {/* full-bleed globe stage */}
      <div className="relative min-w-0 flex-1 bg-void">
        {isError ? (
          <div className="flex h-full flex-col items-center justify-center gap-3">
            <p className="text-xs text-magma">Feed unavailable</p>
            <button
              type="button"
              onClick={() => void refetch()}
              className="mono rounded-sm border border-ember/40 bg-ember/10 px-3 py-1.5 text-[10px] uppercase tracking-wider text-ember"
            >
              Retry
            </button>
          </div>
        ) : (
          <GlobalWatchGlobe incidents={incidents} selectedId={selectedIncidentId} onSelect={selectIncident} />
        )}

        {/* dossier slide-over — the globe keeps living behind it */}
        {selectedIncidentId && (
          <div className="drawer-in absolute inset-y-0 right-0 z-10 flex w-[44%] min-w-[420px] flex-col border-l border-edge bg-abyss/95 shadow-2xl">
            <div className="flex items-center justify-between border-b border-edge px-3 py-1.5">
              <h2 className="mono text-[10px] font-semibold uppercase tracking-widest text-mute">
                Incident Dossier <span className="text-ink">{incidentCode(selectedIncidentId)}</span>
              </h2>
              <button
                type="button"
                onClick={() => selectIncident(null)}
                aria-label="Close dossier"
                className="rounded-sm p-1 text-dim hover:bg-panel2 hover:text-ink"
              >
                <svg width="12" height="12" viewBox="0 0 14 14" fill="none" aria-hidden="true">
                  <path d="M1 1L13 13M13 1L1 13" stroke="currentColor" strokeWidth="1.5" />
                </svg>
              </button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto">
              <IncidentDossier incidentId={selectedIncidentId} />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
