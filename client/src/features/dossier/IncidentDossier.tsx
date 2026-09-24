/**
 * Full evidence dossier: header, evidence panels, observation timeline,
 * association rationale, review controls, review history, report export.
 * The primary analyst investigation view.
 */
import { useIncidentDossier } from '@/services/api/useV2Queries';
import { EvidenceSummary } from './EvidenceSummary';
import { ObservationTimeline } from './ObservationTimeline';
import { AssociationRationale } from './AssociationRationale';
import { ReviewControls } from './ReviewControls';
import { ReviewHistory } from './ReviewHistory';
import { ReportExport } from './ReportExport';
import { FRPDeviationStream } from './viz/FRPDeviationStream';
import { SpatialRadar } from './viz/SpatialRadar';
import { isNewZone } from './viz/vizData';

export function IncidentDossier({ incidentId }: { incidentId: string }) {
  const { data: dossier, isLoading, isError, error, refetch } =
    useIncidentDossier(incidentId);

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center text-xs text-dim">
        Loading dossier…
      </div>
    );
  }

  if (isError || !dossier) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 p-4">
        <p className="text-xs text-magma">
          {error instanceof Error ? error.message : 'Failed to load dossier'}
        </p>
        <button
          type="button"
          onClick={() => void refetch()}
          className="mono rounded-sm border border-ember/40 px-3 py-1 text-[10px] uppercase tracking-wider text-ember"
        >
          Retry
        </button>
      </div>
    );
  }

  const latestAssessment = dossier.assessments[0] ?? null;

  return (
    <div className="flex flex-col gap-3 p-3" role="main" aria-label="Incident dossier">
      {/* Header */}
      <header className="rounded-md border border-edge bg-panel/60 p-3">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h3 className="mono text-sm font-semibold text-ink">
              Incident {dossier.id.slice(0, 8)}
            </h3>
            <p className="mono text-[10px] text-dim">
              {dossier.centroid_latitude.toFixed(4)}°N,{' '}
              {Math.abs(dossier.centroid_longitude).toFixed(4)}°
              {dossier.centroid_longitude >= 0 ? 'E' : 'W'} · v{dossier.version}
            </p>
          </div>
          <div className="mono text-right text-[10px] text-dim">
            <div>First: {new Date(dossier.first_seen_at).toLocaleString()}</div>
            <div>Last: {new Date(dossier.last_seen_at).toLocaleString()}</div>
            <div>{dossier.observation_count} observations</div>
          </div>
        </div>
        {/* Uncertainty banner — the abstain path is always surfaced */}
        {latestAssessment?.status === 'insufficient_evidence' && (
          <div className="tw-status-pulse mt-2 rounded-sm border border-amber/40 bg-amber/10 px-2.5 py-1.5 text-[10px] text-amber">
            <strong>Insufficient evidence</strong>
            {latestAssessment.abstain_reason ? ` — ${latestAssessment.abstain_reason}` : ''}
          </div>
        )}
      </header>

      {/* Evidence left (2/3), actions right (1/3) */}
      <div className="grid flex-1 grid-cols-1 gap-3">
        <div className="space-y-3">
          {latestAssessment && (
            <EvidenceSummary assessment={latestAssessment} observations={dossier.observations} />
          )}
          <div className="rounded-md border border-edge bg-panel/60 p-3">
            <h4 className="mono mb-2 text-[10px] font-semibold uppercase tracking-widest text-mute">
              FRP Deviation Stream
            </h4>
            <FRPDeviationStream observations={dossier.observations} />
          </div>
          <ObservationTimeline observations={dossier.observations} />
          <AssociationRationale observations={dossier.observations} />
          <div className="rounded-md border border-edge bg-panel/60 p-3">
            <h4 className="mono mb-2 text-[10px] font-semibold uppercase tracking-widest text-mute">
              Spatial Scope
            </h4>
            <div className="flex justify-center">
              <SpatialRadar
                observations={dossier.observations}
                centroid={{
                  latitude: dossier.centroid_latitude,
                  longitude: dossier.centroid_longitude,
                }}
                newZone={isNewZone(latestAssessment?.residuals ?? null)}
              />
            </div>
          </div>
        </div>

        <div className="space-y-3">
          <ReviewControls
            incidentId={dossier.id}
            currentStatus={dossier.status}
            currentVersion={dossier.version}
          />
          <ReviewHistory reviews={dossier.reviews} />
          <ReportExport incidentId={dossier.id} />
        </div>
      </div>
    </div>
  );
}
