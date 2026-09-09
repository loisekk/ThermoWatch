import { useEffect, useState } from 'react';
import { BellRing, Map, Orbit, Pause, Play, Satellite } from 'lucide-react';
import { Segmented } from '@/components/ui/Segmented';
import { countdownHMS, utcStamp } from '@/lib/utils/format';
import { useFireStore } from '@/store/useFireStore';
import { useUIStore, type ViewMode } from '@/store/useUIStore';
import { cn } from '@/lib/utils/cn';

const PASS_CYCLE_MS = 3 * 3_600_000; // VIIRS revisit cadence

export function TopBar() {
  const { viewMode, setViewMode, autoRotate, toggleAutoRotate } = useUIStore();
  const { paused, togglePause, alerts } = useFireStore();
  const openAlerts = alerts.filter((a) => a.status === 'new').length;
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);

  return (
    <header className="flex h-12 items-center gap-4 border-b border-edge bg-abyss px-4">
      <div className="flex items-center gap-2.5">
        <span className="grid h-7 w-7 place-items-center rounded-sm border border-ember/40 bg-ember/10 text-ember">
          <Satellite className="h-4 w-4" />
        </span>
        <div className="leading-none">
          <div className="text-sm font-bold tracking-[0.22em]">THERMOWATCH</div>
          <div className="mono mt-0.5 text-[9px] uppercase tracking-widest text-dim">NTRO · SIH26162 · v0.1</div>
        </div>
      </div>

      <div className="mx-auto flex items-center gap-3">
        <Segmented<ViewMode>
          ariaLabel="Viewport mode"
          value={viewMode}
          onChange={setViewMode}
          options={[
            { value: '2d', label: 'Ortho 2D', icon: <Map className="h-3.5 w-3.5" /> },
            { value: '3d', label: 'Orb 3D', icon: <Orbit className="h-3.5 w-3.5" /> },
          ]}
        />
        {viewMode === '3d' && (
          <button
            onClick={toggleAutoRotate}
            aria-pressed={autoRotate}
            className={cn('mono rounded border px-2 py-1 text-[10px] uppercase tracking-wider', autoRotate ? 'border-ember/50 text-ember' : 'border-edge text-mute')}
          >
            auto-rotate {autoRotate ? 'on' : 'off'}
          </button>
        )}
        <button
          onClick={togglePause}
          aria-pressed={!paused}
          title="Pause / resume simulated NRT feed (space)"
          className={cn('flex items-center gap-1.5 rounded border px-2 py-1 text-[10px] uppercase tracking-wider', paused ? 'border-edge text-mute' : 'border-ok/50 text-ok')}
        >
          {paused ? <Play className="h-3 w-3" /> : <Pause className="h-3 w-3" />}
          <span className={cn('h-1.5 w-1.5 rounded-full', paused ? 'bg-dim' : 'live-dot bg-ok')} />
          {paused ? 'feed held' : 'feed live'}
        </button>
      </div>

      <div className="flex items-center gap-4">
        <div className="mono hidden text-[10px] uppercase tracking-wider text-mute md:block">
          next VIIRS pass <span className="text-amber">T-{countdownHMS(PASS_CYCLE_MS - (now % PASS_CYCLE_MS))}</span>
        </div>
        <div className="relative text-mute" title={`${openAlerts} unacknowledged alerts`}>
          <BellRing className="h-4 w-4" />
          {openAlerts > 0 && (
            <span className="mono absolute -right-2 -top-2 grid h-4 min-w-4 place-items-center rounded-full bg-magma px-1 text-[9px] font-bold text-void">{openAlerts}</span>
          )}
        </div>
        <div className="mono text-[11px] text-ink">{utcStamp(now)}</div>
      </div>
    </header>
  );
}
