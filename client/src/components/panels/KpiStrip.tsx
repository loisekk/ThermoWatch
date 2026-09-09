import { ArrowDownRight, ArrowUpRight } from 'lucide-react';
import { computeKpis } from '@/selectors/fireSelectors';
import { useFireStore } from '@/store/useFireStore';
import { fmtInt, fmtPct } from '@/lib/utils/format';

export function KpiStrip() {
  const events = useFireStore((s) => s.events);
  const alerts = useFireStore((s) => s.alerts);
  const k = computeKpis(events);
  const openAlerts = alerts.filter((a) => a.status !== 'resolved').length;

  const cells = [
    { label: 'ACTIVE 24H', value: fmtInt(k.active24), delta: k.delta24 },
    { label: 'INDUSTRIAL SHARE', value: fmtPct(k.industrialShare), delta: undefined as number | undefined },
    { label: 'PERSISTENT SRC', value: fmtInt(k.persistentCount), delta: undefined as number | undefined },
    { label: 'OPEN ALERTS', value: fmtInt(openAlerts), delta: undefined as number | undefined },
    { label: 'MEAN CONF', value: fmtPct(k.meanConfidence), delta: undefined as number | undefined },
  ];

  return (
    <div className="grid grid-cols-5 divide-x divide-edge rounded-md border border-edge bg-panel/90">
      {cells.map((c) => (
        <div key={c.label} className="px-2.5 py-2">
          <div className="mono text-[8px] uppercase tracking-widest text-dim">{c.label}</div>
          <div className="mono mt-1 flex items-baseline gap-1 text-lg font-semibold text-ink">
            {c.value}
            {c.delta !== undefined && c.delta !== 0 && (
              <span className={`flex items-center text-[10px] ${c.delta > 0 ? 'text-magma' : 'text-ok'}`}>
                {c.delta > 0 ? <ArrowUpRight className="h-3 w-3" /> : <ArrowDownRight className="h-3 w-3" />}
                {Math.abs(c.delta)}
              </span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
