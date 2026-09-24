/**
 * Analyst workspace: incident queue (left) + evidence dossier (right).
 * The dossier opens in-place — Escape or the close button collapses it.
 */
import { useEffect } from 'react';
import { useQueueStore } from '@/store/useQueueStore';
import { IncidentQueue } from './IncidentQueue';
import { IncidentDossier } from '@/features/dossier/IncidentDossier';

export function QueueWorkspace() {
  const selectedIncidentId = useQueueStore((s) => s.selectedIncidentId);
  const drawerOpen = useQueueStore((s) => s.drawerOpen);
  const selectIncident = useQueueStore((s) => s.selectIncident);

  // Escape closes the dossier (mirrors the global esc shortcut contract).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') selectIncident(null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [selectIncident]);

  return (
    <div className="flex h-full w-full">
      <div className={`flex min-w-0 flex-col transition-all ${drawerOpen && selectedIncidentId ? 'w-1/2' : 'w-full'}`}>
        <IncidentQueue />
      </div>

      {drawerOpen && selectedIncidentId && (
        <div className="flex w-1/2 min-w-0 flex-col border-l border-edge bg-abyss">
          <div className="flex items-center justify-between border-b border-edge px-3 py-1.5">
            <h2 className="mono text-[10px] font-semibold uppercase tracking-widest text-mute">
              Evidence Dossier
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
  );
}
