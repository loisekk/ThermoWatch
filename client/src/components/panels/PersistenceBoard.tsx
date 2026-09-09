import { History } from 'lucide-react';
import { Panel } from '@/components/ui/Panel';
import { Badge } from '@/components/ui/Badge';
import { CLASS_META, SUBTYPE_LABEL } from '@/config/constants';
import { topPersistent } from '@/selectors/fireSelectors';
import { useFireStore } from '@/store/useFireStore';
import { useUIStore } from '@/store/useUIStore';

export function PersistenceBoard() {
  const events = useFireStore((s) => s.events);
  const facilities = useFireStore((s) => s.facilities);
  const select = useFireStore((s) => s.select);
  const requestFocus = useUIStore((s) => s.requestFocus);
  const rows = topPersistent(events);

  return (
    <Panel title="Chronic Thermal Sources" icon={<History />} bodyClassName="p-2">
      <ul className="space-y-1.5">
        {rows.map((e) => {
          const f = facilities.find((x) => x.id === e.nearestFacilityId);
          return (
            <li key={e.id}>
              <button
                onClick={() => { select(e.id); requestFocus(e.lat, e.lon); }}
                className="w-full rounded-sm border border-edge bg-panel2/60 px-2.5 py-2 text-left transition-colors hover:border-edge2"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-[11px] font-medium text-ink">{f ? f.name : `${e.lat.toFixed(2)}, ${e.lon.toFixed(2)}`}</span>
                  <Badge color={CLASS_META[e.classification.primary].color}>{e.persistence.consecutiveDays}d</Badge>
                </div>
                <div className="mono mt-1 flex items-center justify-between text-[9px] text-dim">
                  <span>{f ? SUBTYPE_LABEL[f.subtype] : 'unmapped source'} · {e.persistence.detections30d} det/30d</span>
                  <span>risk {e.risk.score}</span>
                </div>
                <div className="mt-1.5 h-1 rounded-full bg-edge">
                  <div className="h-1 rounded-full bg-amber" style={{ width: `${Math.min(100, (e.persistence.consecutiveDays / 45) * 100)}%` }} />
                </div>
              </button>
            </li>
          );
        })}
        {rows.length === 0 && <li className="mono p-3 text-center text-[10px] text-dim">no persistent sources in window</li>}
      </ul>
    </Panel>
  );
}
