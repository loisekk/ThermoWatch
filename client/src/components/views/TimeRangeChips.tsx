import { useAnalyticsStore } from '@/store/useAnalyticsStore';
import { cn } from '@/lib/utils/cn';

const PRESETS: { key: string; label: string; hours: number | null }[] = [
  { key: '24h', label: '24h', hours: 24 },
  { key: '48h', label: '48h', hours: 48 },
  { key: '7d', label: '7d', hours: 168 },
  { key: '14d', label: '14d', hours: 336 },
  { key: '30d', label: '30d', hours: 720 },
  { key: 'all', label: 'All', hours: null },
];

export function TimeRangeChips() {
  const windowKey = useAnalyticsStore((s) => s.windowKey);
  const setWindow = useAnalyticsStore((s) => s.setWindow);
  return (
    <div className="pointer-events-auto flex rounded-sm border border-edge bg-panel/90 p-0.5">
      {PRESETS.map((p) => (
        <button
          key={p.key}
          onClick={() => setWindow(p.key, p.hours)}
          aria-pressed={windowKey === p.key}
          className={cn('mono px-2.5 py-1 text-[10px] uppercase tracking-wider transition-colors',
            windowKey === p.key ? 'bg-ok/20 text-ok' : 'text-mute hover:text-ink')}
        >
          {p.label}
        </button>
      ))}
    </div>
  );
}
