import { useFireStore } from '@/store/useFireStore';
import { fmtInt, utcStamp } from '@/lib/utils/format';

const KIND_COLOR: Record<string, string> = { ingest: 'text-steel', classify: 'text-amber', alert: 'text-magma', system: 'text-ok' };
/** WS taxonomy tag colors — each live event type is color-coded on the console line. */
const TYPE_COLOR: Record<string, string> = {
  'fire:new': '#FF6B35',
  'fire:classified': '#3FB950',
  'persistence:detected': '#FFB800',
  'alert:triggered': '#FF4444',
  'system:status': '#7D8DA1',
};

export function StatusTicker() {
  const logs = useFireStore((s) => s.logs);
  const events = useFireStore((s) => s.events);
  const last = logs[logs.length - 1];
  return (
    <footer className="flex h-7 items-center gap-3 border-t border-edge bg-abyss px-3">
      <span className="mono text-[10px] uppercase tracking-widest text-dim">console</span>
      {last && (
        <span key={`${last.ts}-${last.text}`} className={`ticker-in mono truncate text-[10px] ${KIND_COLOR[last.kind]}`}>
          {last.tag && (
            <span className="font-semibold" style={{ color: TYPE_COLOR[last.tag] ?? '#8CA0B3' }}>[{last.tag}]</span>
          )}{' '}
          [{utcStamp(last.ts)}] {last.text}
        </span>
      )}
      <span className="mono ml-auto shrink-0 text-[10px] text-dim">
        buffer {fmtInt(events.length)} ev · data: NASA FIRMS · NASA GIBS · © OpenStreetMap contributors (ODbL) · ESA WorldCover · Natural Earth
      </span>
    </footer>
  );
}
