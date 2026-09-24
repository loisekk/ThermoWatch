/**
 * Global Watch rail — the left deck: LIVE OVERVIEW, INCIDENT TYPES, RECENT
 * INCIDENTS. Reads the same single query as the globe; selecting a row flies
 * the globe and opens the shared dossier.
 *
 * Every number here is either measured from the feed or labelled as unknown —
 * the rail never invents a status.
 */
import type { IncidentSummary } from '@/services/api/v2Types';
import {
  RISK_META,
  RISK_ORDER,
  countByClass,
  countByRisk,
  deriveRiskLevel,
  incidentCode,
  topClass,
} from './incidentDisplay';
import { GLOBE_PAGE_LIMIT } from './useGlobeIncidents';

const DONUT_COLORS = ['#ff6b35', '#3fb950', '#ffb800', '#ff4444', '#8fd14f', '#7d8da1'];

interface Props {
  incidents: IncidentSummary[];
  totalApprox: number;
  dataUpdatedAt: number;
  /** First load in flight — the empty rail says so instead of claiming "none". */
  loading?: boolean;
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export function GlobalWatchRail({ incidents, totalApprox, dataUpdatedAt, loading = false, selectedId, onSelect }: Props) {
  const counts = countByRisk(incidents);
  const needsReview = incidents.filter((i) => i.status === 'needs_review').length;
  const recent = [...incidents]
    .sort((a, b) => +new Date(b.last_seen_at) - +new Date(a.last_seen_at))
    .slice(0, 6);
  const ageS = dataUpdatedAt ? Math.max(0, Math.round((Date.now() - dataUpdatedAt) / 1000)) : null;
  const fresh = ageS == null ? '—' : ageS < 60 ? `${ageS}s ago` : `${Math.round(ageS / 60)}m ago`;
  const hidden = Math.max(0, totalApprox - incidents.length);

  return (
    <aside
      className="flex w-64 shrink-0 flex-col gap-3 overflow-y-auto border-r border-edge bg-abyss/70 p-3"
      aria-label="Global Watch live overview"
    >
      <section className="rounded-md border border-edge bg-panel/60 p-3">
        <h3 className="mono mb-2 flex items-center gap-2 text-[10px] font-semibold uppercase tracking-widest text-mute">
          <span className="live-dot inline-block h-1.5 w-1.5 rounded-full bg-ok" aria-hidden="true" />
          Live Overview
        </h3>
        <div className="grid grid-cols-2 gap-2">
          <Kpi label="TRACKED" value={incidents.length} />
          <Kpi label="HIGH RISK" value={counts.high} tone={counts.high > 0 ? 'text-magma' : undefined} />
          <Kpi label="NEEDS REVIEW" value={needsReview} tone={needsReview > 0 ? 'text-amber' : undefined} />
          <Kpi label="FEED" value={fresh} tone={ageS != null && ageS < 120 ? 'text-ok' : undefined} />
        </div>
        <div className="mt-3 flex h-1.5 overflow-hidden rounded-full bg-panel2" aria-hidden="true">
          {RISK_ORDER.map((r) =>
            counts[r] > 0 ? (
              <div
                key={r}
                style={{
                  width: `${(counts[r] / Math.max(incidents.length, 1)) * 100}%`,
                  background: RISK_META[r].color,
                }}
              />
            ) : null,
          )}
        </div>
        <p className="mono mt-1.5 text-[9px] leading-relaxed text-dim">
          {RISK_ORDER.filter((r) => counts[r] > 0)
            .map((r) => `${counts[r]} ${RISK_META[r].label}`)
            .join(' · ') || (loading ? 'loading feed…' : 'no active incidents')}
        </p>
        {hidden > 0 && (
          <p className="mono mt-1 text-[9px] text-amber">
            showing newest {incidents.length} of ≈{totalApprox} (page cap {GLOBE_PAGE_LIMIT})
          </p>
        )}
      </section>
      <section className="rounded-md border border-edge bg-panel/60 p-3">
        <h3 className="mono mb-2 text-[10px] font-semibold uppercase tracking-widest text-mute">Incident Types</h3>
        <TypeDonut counts={countByClass(incidents)} total={incidents.length} />
      </section>

      <section className="rounded-md border border-edge bg-panel/60 p-3">
        <h3 className="mono mb-2 text-[10px] font-semibold uppercase tracking-widest text-mute">Recent Incidents</h3>
        <ul className="space-y-1">
          {recent.length === 0 && (
            <li className="mono text-[10px] leading-relaxed text-dim">
              {loading ? 'loading feed…' : 'No active incidents — run demo_scenario to seed.'}
            </li>
          )}
          {recent.map((i) => {
            const meta = RISK_META[deriveRiskLevel(i)];
            return (
              <li key={i.id}>
                <button
                  type="button"
                  onClick={() => onSelect(i.id)}
                  className={`mono flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-[10px] transition-colors hover:bg-panel2 ${
                    selectedId === i.id ? 'bg-ember/10 ring-1 ring-ember/40' : ''
                  }`}
                >
                  <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: meta.color }} aria-hidden="true" />
                  <span className="text-ink">{incidentCode(i.id)}</span>
                  <span className="truncate text-dim">{topClass(i).replace(/_/g, ' ')}</span>
                  <span className="ml-auto text-dim" title={i.last_seen_at}>{timeAgo(i.last_seen_at)}</span>
                </button>
              </li>
            );
          })}
        </ul>
      </section>
    </aside>
  );
}

function Kpi({ label, value, tone = 'text-ink' }: { label: string; value: string | number; tone?: string }) {
  return (
    <div className="rounded-sm border border-edge bg-void/60 px-2 py-1.5">
      <div className="mono text-[9px] tracking-wider text-dim">{label}</div>
      <div className={`mono text-sm font-semibold ${tone}`}>{value}</div>
    </div>
  );
}

function timeAgo(iso: string): string {
  const s = Math.max(0, Math.round((Date.now() - +new Date(iso)) / 1000));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.round(s / 60)}m`;
  return `${Math.round(s / 3600)}h`;
}

/** Type donut over real `top_class` counts — inline SVG, no chart dependency. */
function TypeDonut({ counts, total }: { counts: Map<string, number>; total: number }) {
  const entries = [...counts.entries()].slice(0, 6);
  if (entries.length === 0) {
    return <p className="mono text-[10px] leading-relaxed text-dim">no classified incidents yet</p>;
  }
  const sum = entries.reduce((s, [, n]) => s + n, 0) || 1;
  let acc = -Math.PI / 2;
  const arcs = entries.map(([name, n], i) => {
    const a0 = acc;
    const a1 = acc + (n / sum) * Math.PI * 2;
    acc = a1;
    return { name, n, a0, a1, color: DONUT_COLORS[i % DONUT_COLORS.length] };
  });
  const single = arcs.length === 1;
  return (
    <div className="flex items-center gap-3">
      <svg
        width="72"
        height="72"
        viewBox="0 0 72 72"
        role="img"
        aria-label={`incident type distribution across ${total} incidents`}
      >
        {single ? (
          <circle cx="36" cy="36" r="30" fill={arcs[0].color} opacity="0.85" />
        ) : (
          arcs.map((a) => (
            <path
              key={a.name}
              d={`M 36 36 L ${36 + 30 * Math.cos(a.a0)} ${36 + 30 * Math.sin(a.a0)} A 30 30 0 ${
                a.a1 - a.a0 > Math.PI ? 1 : 0
              } 1 ${36 + 30 * Math.cos(a.a1)} ${36 + 30 * Math.sin(a.a1)} Z`}
              fill={a.color}
              opacity="0.85"
            />
          ))
        )}
        <circle cx="36" cy="36" r="16" fill="#07090d" />
        <text x="36" y="39" textAnchor="middle" fill="#8ca0b3" fontSize="11" fontFamily="monospace">
          {total}
        </text>
      </svg>
      <ul className="min-w-0 flex-1 space-y-0.5">
        {arcs.map((a) => (
          <li key={a.name} className="mono flex items-center gap-1.5 text-[9px]">
            <span className="h-1.5 w-1.5 shrink-0 rounded-sm" style={{ background: a.color }} aria-hidden="true" />
            <span className="truncate text-mute">{a.name.replace(/_/g, ' ')}</span>
            <span className="ml-auto text-dim">{a.n}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
