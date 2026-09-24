/**
 * Incident queue row — disposition badge, location, freshness and the latest
 * assessment summary. Badges pair color with TEXT (never color alone — WCAG).
 */
import type { IncidentSummary } from '@/services/api/v2Types';
import { freshnessLabel } from './queueUtils';
import { ActivityGlyph } from '@/features/dossier/viz/ActivityGlyph';

const STATUS_LABELS: Record<string, string> = {
  needs_review: 'NEEDS REVIEW',
  reviewed: 'REVIEWED',
  escalated: 'ESCALATED',
  dismissed: 'DISMISSED',
};

const STATUS_COLORS: Record<string, string> = {
  needs_review: 'text-amber bg-amber/10 border-amber/40',
  reviewed: 'text-ok bg-ok/10 border-ok/40',
  escalated: 'text-magma bg-magma/10 border-magma/40',
  dismissed: 'text-dim bg-steel/10 border-edge2',
};

const ASSESSMENT_STATUS_COLORS: Record<string, string> = {
  normal: 'text-ok',
  abnormal: 'text-magma',
  insufficient_evidence: 'text-dim',
};

export function IncidentRow({
  incident,
  selected,
  onSelect,
}: {
  incident: IncidentSummary;
  selected: boolean;
  onSelect: () => void;
}) {
  const asm = incident.current_assessment;

  return (
    <button
      type="button"
      role="listitem"
      aria-selected={selected}
      onClick={onSelect}
      className={`flex w-full items-center gap-3 border-b border-edge/50 px-3 py-2.5 text-left transition-colors
        hover:bg-panel2/60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-ember tw-row-${incident.status}
        ${selected ? 'bg-ember/10' : ''}`}
    >
      {/* Disposition badge (text + color, never color alone) */}
      <span
        className={`mono shrink-0 rounded-sm border px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wider ${STATUS_COLORS[incident.status] ?? 'border-edge2 text-dim'}`}
      >
        {STATUS_LABELS[incident.status] ?? incident.status}
      </span>

      {/* Location + timing */}
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span className="text-xs font-medium text-ink">
            {incident.centroid_latitude.toFixed(2)}°, {incident.centroid_longitude.toFixed(2)}°
          </span>
          <span className="mono text-[10px] text-dim">{freshnessLabel(incident.last_seen_at)}</span>
        </div>
        <div className="mono text-[10px] text-dim">
          {incident.observation_count} obs · {incident.days_active}d active · v{incident.version}
        </div>
      </div>

      {/* Latest assessment summary */}
      {asm ? (
        <div className="flex shrink-0 items-center gap-3 text-right">
          <div>
            <div className={`text-[11px] font-medium ${ASSESSMENT_STATUS_COLORS[asm.status] ?? 'text-mute'}`}>
              {asm.status === 'insufficient_evidence' ? 'INSUFFICIENT' : asm.status.toUpperCase()}
            </div>
            <div className="mono text-[10px] text-dim">
              {asm.top_class.replace(/_/g, ' ')}
              {asm.top_confidence !== null && ` (${Math.round(asm.top_confidence * 100)}%)`}
            </div>
          </div>
          <div className="mono text-[10px] text-dim">
            <span className="flex items-center justify-end gap-1">
              <ActivityGlyph state={asm.activity_state} />
              {asm.activity_state.replace(/_/g, ' ')}
            </span>
          </div>
        </div>
      ) : (
        <span className="mono shrink-0 text-[10px] text-dim">no assessment</span>
      )}
    </button>
  );
}
