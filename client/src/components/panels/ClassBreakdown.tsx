import { PieChart } from 'lucide-react';
import { Panel } from '@/components/ui/Panel';
import { Donut } from '@/components/ui/charts/Donut';
import { CLASS_META, CLASS_ORDER } from '@/config/constants';
import { computeBreakdown } from '@/selectors/fireSelectors';
import { useFireStore } from '@/store/useFireStore';
import { fmtInt } from '@/lib/utils/format';

export function ClassBreakdown() {
  const events = useFireStore((s) => s.events);
  const filters = useFireStore((s) => s.filters);
  const filtered = events.filter((e) => filters.classes.includes(e.classification.primary));
  const bd = computeBreakdown(filtered);
  const total = CLASS_ORDER.reduce((a, c) => a + bd[c], 0);

  return (
    <Panel title="Classification Mix" icon={<PieChart />}>
      <div className="flex items-center gap-4">
        <Donut
          segments={CLASS_ORDER.map((c) => ({ value: bd[c], color: CLASS_META[c].color, label: CLASS_META[c].label }))}
          centerLabel={fmtInt(total)}
          centerSub="EVENTS"
        />
        <ul className="flex-1 space-y-2">
          {CLASS_ORDER.map((c) => {
            const share = total ? (bd[c] / total) * 100 : 0;
            return (
              <li key={c}>
                <div className="flex items-center justify-between text-[10px]">
                  <span className="flex items-center gap-1.5 text-mute">
                    <span className="h-1.5 w-1.5 rounded-full" style={{ background: CLASS_META[c].color }} />
                    {CLASS_META[c].short}
                  </span>
                  <span className="mono text-ink">{fmtInt(bd[c])} · {Math.round(share)}%</span>
                </div>
                <div className="mt-1 h-1 rounded-full bg-edge">
                  <div className="h-1 rounded-full" style={{ width: `${share}%`, background: CLASS_META[c].color }} />
                </div>
              </li>
            );
          })}
        </ul>
      </div>
    </Panel>
  );
}
