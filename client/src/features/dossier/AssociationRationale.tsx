/**
 * Association rationale — shows the rule version and link decision for the
 * first observation. Evidence is immutable; association can be re-reviewed
 * but never destroys data.
 */
import type { ObservationDetail } from '@/services/api/v2Types';

export function AssociationRationale({ observations }: { observations: ObservationDetail[] }) {
  if (observations.length === 0) return null;
  const first = observations[0];
  const rationale = (first.association_rationale ?? {}) as Record<string, unknown>;
  const ruleVersion = rationale.rule_version as string | undefined;

  return (
    <section
      className="rounded-md border border-edge bg-panel/60 p-3"
      aria-label="Association rationale"
    >
      <h4 className="mono mb-2 text-[10px] font-semibold uppercase tracking-widest text-mute">
        Association Rationale
      </h4>
      <div className="space-y-1 text-[10px] text-mute">
        <div className="flex gap-2">
          <span className="mono shrink-0 text-dim">Rule:</span>
          <code className="mono rounded-sm bg-panel2 px-1.5 py-0.5 text-[10px] text-ember">
            {ruleVersion ?? first.association_method}
          </code>
        </div>
        <div className="flex gap-2">
          <span className="mono shrink-0 text-dim">First link decision:</span>
          <span className="text-mute">{String(rationale.decision ?? 'created_new')}</span>
        </div>
        {rationale.distance_km !== undefined && (
          <div className="flex gap-2">
            <span className="mono shrink-0 text-dim">Distance:</span>
            <span className="mono tabular-nums text-mute">
              {Number(rationale.distance_km).toFixed(2)} km
            </span>
          </div>
        )}
        {rationale.reason !== undefined && (
          <div className="flex gap-2">
            <span className="mono shrink-0 text-dim">Reason:</span>
            <span className="text-mute">{String(rationale.reason)}</span>
          </div>
        )}
      </div>
      <p className="mono mt-2 text-[9px] italic text-dim">
        Original observations are immutable. Association can be re-reviewed but never destroys evidence.
      </p>
    </section>
  );
}
