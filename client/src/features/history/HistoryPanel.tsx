import { useEffect, useMemo, useState } from 'react';
import { Clock3, Loader } from 'lucide-react';
import { api } from '@/services/api/client';
import { CLASS_META, CLASS_ORDER } from '@/config/constants';
import { useFireStore } from '@/store/useFireStore';

const DAY_MS = 86_400_000;

interface HistoryDay {
  industrial: number;
  persistent: number;
  wildfire: number;
  agricultural: number;
  total: number;
}

interface HistoryData {
  days: number;
  total_events: number;
  daily: Record<string, HistoryDay>;
  leaderboard: { facility_id: string; count: number }[];
  persistent_cells: number;
}

/** Historical analysis workspace: 30-day stacked timeline, persistent-source
 *  leaderboard. Feeds /api/v1/stats/history (server retention window). */
export function HistoryPanel() {
  const [data, setData] = useState<HistoryData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const facilities = useFireStore((s) => s.facilities);

  useEffect(() => {
    let on = true;
    api
      .get<HistoryData>('/api/v1/stats/history?days=180')
      .then((d) => { if (on) setData(d); })
      .catch((e: unknown) => { if (on) setError(e instanceof Error ? e.message : String(e)); });
    return () => { on = false; };
  }, []);

  const rows = useMemo(() => {
    if (!data) return [];
    return Object.entries(data.daily)
      .map(([k, d]) => ({ day: new Date(Number(k) * DAY_MS), d }))
      .sort((a, b) => a.day.getTime() - b.day.getTime())
      .slice(-30);
  }, [data]);

  if (error) {
    return <div className="rounded-md border border-edge bg-panel/90 p-2.5 text-[10px] text-magma">history unavailable — {error}</div>;
  }
  if (!data) {
    return <div className="flex items-center gap-2 rounded-md border border-edge bg-panel/90 p-2.5 text-[10px] text-dim"><Loader className="h-3 w-3 animate-spin" /> loading historical aggregates…</div>;
  }

  const maxTotal = Math.max(...rows.map((r) => r.d.total), 1);
  const pxPerEvent = Math.max(maxTotal / 120, 0.1);
  const facilityName = (id: string) => facilities.find((f) => f.id === id)?.name ?? id;

  return (
    <div className="grid gap-2">
      <div className="rounded-md border border-edge bg-panel/90 p-2.5">
        <div className="mono mb-1.5 flex items-center gap-1.5 text-[9px] uppercase tracking-widest text-dim">
          <Clock3 className="h-3 w-3" /> historical analysis · last {rows.length} d
        </div>
        <div className="flex gap-3 text-[10px] text-mute">
          <span>events <span className="mono text-ink">{data.total_events}</span></span>
          <span>persistent cells <span className="mono text-ink">{data.persistent_cells}</span></span>
          <span>top sources <span className="mono text-ink">{data.leaderboard.length}</span></span>
        </div>
      </div>

      <div className="rounded-md border border-edge bg-panel/90 p-2.5">
        <div className="mono mb-1.5 text-[9px] uppercase tracking-widest text-dim">daily timeline · stacked by class</div>
        <div className="flex h-[120px] items-end gap-px">
          {rows.map(({ day, d }) => (
            <div key={day.getTime()} className="flex min-w-0 flex-1 flex-col-reverse" title={`${day.toISOString().slice(0, 10)} · ${d.total} detections`}>
              {CLASS_ORDER.map((c) => {
                const n = d[c];
                return (
                  <div key={c} className="w-full" style={{ height: n ? `${Math.max(n / pxPerEvent, 1.5)}px` : '0px', background: CLASS_META[c].color, opacity: 0.9 }} />
                );
              })}
            </div>
          ))}
        </div>
        <div className="mt-1 flex gap-px">
          {rows.map(({ day }, i) => (
            <span key={i} className={`mono min-w-0 flex-1 text-center text-[8px] ${i % 5 === 0 ? 'text-dim' : 'text-[transparent]'}`}>
              {day.getUTCMonth() + 1}/{day.getUTCDate()}
            </span>
          ))}
        </div>
        <div className="mt-2 flex flex-wrap gap-2 border-t border-edge pt-1.5">
          {CLASS_ORDER.map((c) => (
            <span key={c} className="flex items-center gap-1 text-[9px] text-mute">
              <span className="h-2 w-2 rounded-full" style={{ background: CLASS_META[c].color }} />
              {CLASS_META[c].label}
            </span>
          ))}
        </div>
      </div>

      <div className="rounded-md border border-edge bg-panel/90 p-2.5">
        <div className="mono mb-1.5 text-[9px] uppercase tracking-widest text-dim">top persistent sources · detections</div>
        {data.leaderboard.length === 0 ? (
          <div className="text-[10px] text-dim">no facility-correlated events in retention window</div>
        ) : (
          <ul className="space-y-1">
            {data.leaderboard.map((f, i) => (
              <li key={f.facility_id} className="flex items-center gap-2">
                <span className="mono w-4 shrink-0 text-[9px] text-dim">{i + 1}.</span>
                <span className="flex-1 truncate text-[10px] text-mute">{facilityName(f.facility_id)}</span>
                <span className="mono shrink-0 text-[9px] text-ink">{f.count}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}