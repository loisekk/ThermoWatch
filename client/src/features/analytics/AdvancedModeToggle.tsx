import { BarChart3 } from 'lucide-react';
import { useAnalyticsStore } from '@/store/useAnalyticsStore';
import { cn } from '@/lib/utils/cn';

export function AdvancedModeToggle() {
  const advancedMode = useAnalyticsStore((s) => s.advancedMode);
  const setAdvancedMode = useAnalyticsStore((s) => s.setAdvancedMode);

  return (
    <button
      onClick={() => setAdvancedMode(!advancedMode)}
      aria-pressed={advancedMode}
      title="Toggle Advanced Analytics Mode (deck.gl layers + DuckDB spatial queries)"
      className={cn(
        'mono flex items-center gap-1.5 rounded border px-2 py-1 text-[10px] uppercase tracking-wider transition-colors',
        advancedMode ? 'border-ember/50 bg-ember/15 text-ember' : 'border-edge text-mute hover:border-ember/30 hover:text-ember',
      )}
    >
      <BarChart3 className="h-3.5 w-3.5" />
      <span>{advancedMode ? 'advanced mode on' : 'advanced mode'}</span>
    </button>
  );
}
