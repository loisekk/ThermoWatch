/**
 * Evidence summary — instrument cluster (fingerprint, deviation gauge,
 * diurnal dial, fusion constellation) with the EXISTING numeric readouts
 * kept beneath: every instrument has its number nearby (WCAG — shapes and
 * color never carry the value alone). Source-class estimate and temporal
 * activity stay separate panels with explicit honesty caveats (never
 * conflated).
 */
import type { AssessmentDetail, ObservationDetail } from '@/services/api/v2Types';
import { ThermalFingerprint } from './viz/ThermalFingerprint';
import { ResidualGauge } from './viz/ResidualGauge';
import { TemporalDial } from './viz/TemporalDial';
import { FusionConstellation } from './viz/FusionConstellation';
import { ActivityGlyph } from './viz/ActivityGlyph';
import { fusionFromExplanation, intensityZ } from './viz/vizData';

export function EvidenceSummary({
  assessment,
  observations,
}: {
  assessment: AssessmentDetail;
  observations: ObservationDetail[];
}) {
  const topClasses = Object.entries(assessment.source_class_scores ?? {})
    .sort(([, a], [, b]) => b - a)
    .slice(0, 5);
  const fusion = fusionFromExplanation(assessment.explanation);
  const z = intensityZ(assessment.residuals);
  const hours = observations.map((o) => new Date(o.observed_at).getHours());

  return (
    <section
      className="rounded-md border border-edge bg-panel/60 p-3"
      aria-label="Evidence summary"
    >
      <h4 className="mono mb-2 text-[10px] font-semibold uppercase tracking-widest text-mute">
        Evidence Summary
      </h4>

      {/* Instrument cluster — shape first, every number stays below */}
      <div className="grid grid-cols-2 gap-3 2xl:grid-cols-4">
        <div className="flex flex-col items-center gap-1">
          <span className="mono text-[9px] font-medium uppercase tracking-widest text-dim">
            Thermal Fingerprint
          </span>
          <ThermalFingerprint scores={assessment.source_class_scores} size={160} />
        </div>
        <div className="flex flex-col items-center gap-1">
          <span className="mono text-[9px] font-medium uppercase tracking-widest text-dim">
            Deviation
          </span>
          <ResidualGauge z={z} />
        </div>
        <div className="flex flex-col items-center gap-1">
          <span className="mono text-[9px] font-medium uppercase tracking-widest text-dim">
            Diurnal Pattern
          </span>
          <TemporalDial hours={hours} />
        </div>
        <div className="flex flex-col items-center gap-1">
          <span className="mono text-[9px] font-medium uppercase tracking-widest text-dim">
            Evidence Fusion
          </span>
          <FusionConstellation sources={fusion.sources} fusedScore={fusion.fusedScore} size={160} />
        </div>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-3">
        {/* Source class estimate — compact text parity for the fingerprint */}
        <div>
          <h5 className="mono mb-1.5 text-[9px] font-medium uppercase tracking-widest text-dim">
            Source Class (estimate)
          </h5>
          <div className="space-y-0.5">
            {topClasses.map(([cls, prob]) => (
              <div key={cls} className="flex items-baseline justify-between gap-2">
                <span className="mono truncate text-[10px] text-mute">
                  {cls.replace(/_/g, ' ')}
                </span>
                <span className="mono shrink-0 text-[10px] tabular-nums text-dim">
                  {(prob * 100).toFixed(0)}%
                </span>
              </div>
            ))}
          </div>
          <p className="mono mt-1.5 text-[9px] italic text-dim">
            model estimate — not verified truth
          </p>
        </div>

        {/* Temporal activity — glyph + state + raw residual numbers */}
        <div>
          <h5 className="mono mb-1.5 text-[9px] font-medium uppercase tracking-widest text-dim">
            Temporal Activity
          </h5>
          <div
            className={`flex items-center gap-1.5 text-lg font-bold ${
              assessment.activity_state === 'acute' ? 'text-amber'
              : assessment.activity_state === 'persistent' ? 'text-magma'
              : assessment.activity_state === 'recurring' ? 'text-ember'
              : assessment.activity_state === 'changing' ? 'text-amber'
              : 'text-dim'
            }`}
          >
            <ActivityGlyph state={assessment.activity_state} />
            <span>{assessment.activity_state.replace(/_/g, ' ').toUpperCase()}</span>
          </div>

          {assessment.residuals && (
            <div className="mt-2 space-y-0.5 text-[10px]">
              {Object.entries(assessment.residuals).map(([k, v]) =>
                v !== null && v !== undefined ? (
                  <div key={k} className="flex justify-between">
                    <span className="mono text-dim">{k.replace(/_/g, ' ')}:</span>
                    <span className={`mono tabular-nums ${Math.abs(Number(v)) > 3 ? 'text-magma' : 'text-mute'}`}>
                      {typeof v === 'number' ? v.toFixed(2) : String(v)}
                    </span>
                  </div>
                ) : null,
              )}
            </div>
          )}

          <p className="mono mt-1.5 text-[9px] italic text-dim">
            assessed {assessment.assessment_version.slice(0, 12)}…
          </p>
        </div>
      </div>
    </section>
  );
}
