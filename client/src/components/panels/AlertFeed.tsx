import { BellRing } from 'lucide-react';
import { Panel } from '@/components/ui/Panel';
import { RISK_META } from '@/config/constants';
import { useFireStore } from '@/store/useFireStore';
import { relTime } from '@/lib/utils/format';
import type { AlertStatus } from '@/types/domain';
import { cn } from '@/lib/utils/cn';

const NEXT: Record<AlertStatus, AlertStatus> = { new: 'acknowledged', acknowledged: 'dispatched', dispatched: 'resolved', resolved: 'resolved' };

export function AlertFeed() {
  const alerts = useFireStore((s) => s.alerts);
  const setAlertStatus = useFireStore((s) => s.setAlertStatus);
  const select = useFireStore((s) => s.select);
  const rows = [...alerts].reverse();

  return (
    <Panel title="Action Queue" icon={<BellRing />} bodyClassName="p-2">
      <ul className="space-y-1.5">
        {rows.map((a) => (
          <li key={a.id} className="rounded-sm border border-edge bg-panel2/60 px-2.5 py-2" style={{ borderLeft: `3px solid ${RISK_META[a.level].color}` }}>
            <div className="flex items-center justify-between gap-2">
              <button onClick={() => select(a.eventId)} className="mono truncate text-left text-[10px] text-ink hover:text-ember">
                {a.eventId} · {a.message}
              </button>
              <span className="mono shrink-0 text-[9px] text-dim">{relTime(a.createdAt)}</span>
            </div>
            <div className="mt-1.5 flex items-center gap-2">
              <span className={cn('mono text-[9px] uppercase tracking-wider', a.status === 'resolved' ? 'text-ok' : a.status === 'new' ? 'text-magma' : 'text-amber')}>
                {a.status}
              </span>
              {a.status !== 'resolved' && (
                <button onClick={() => setAlertStatus(a.id, NEXT[a.status])} className="mono ml-auto rounded border border-edge px-1.5 py-0.5 text-[9px] uppercase tracking-wider text-mute hover:border-ember/50 hover:text-ember">
                  → {NEXT[a.status]}
                </button>
              )}
            </div>
          </li>
        ))}
        {rows.length === 0 && <li className="mono p-3 text-center text-[10px] text-dim">queue clear</li>}
      </ul>
    </Panel>
  );
}
