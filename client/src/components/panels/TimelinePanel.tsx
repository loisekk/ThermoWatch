import { ChartColumn } from 'lucide-react';
import { Panel } from '@/components/ui/Panel';
import { CLASS_META, CLASS_ORDER } from '@/config/constants';
import { computeTimeline } from '@/selectors/fireSelectors';
import { useFireStore } from '@/store/useFireStore';

export function TimelinePanel() {
  const events = useFireStore((s) => s.events);
  const days = computeTimeline(events);
  const max = Math.max(1, ...days.map((d) => d.total));

  return (
    <Panel title="14-Day Detection Timeline" icon={<ChartColumn />} bodyClassName="p-3 pt-2">
      <div className="flex h-28 items-end gap-1">
        {days.map((d) => (
          <div key={d.ts} className="group relative flex h-full flex-1 flex-col justify-end" title={`${d.label} · ${d.total} detections`}>
            <div className="flex flex-col-reverse overflow-hidden rounded-sm" style={{ height: `${(d.total / max) * 100}%` }}>
              {CLASS_ORDER.map((c) =>
                d.counts[c] > 0 ? (
                  <div key={c} style={{ background: CLASS_META[c].color, flexGrow: d.counts[c] }} className="min-h-0.5" />
                ) : null,
              )}
            </div>
          </div>
        ))}
      </div>
      <div className="mono mt-1 flex justify-between text-[8px] text-dim">
        <span>{days[0]?.label}</span><span>{days[days.length - 1]?.label}</span>
      </div>
    </Panel>
  );
}
