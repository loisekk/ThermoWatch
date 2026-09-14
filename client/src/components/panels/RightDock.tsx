import { KpiStrip } from './KpiStrip';
import { ClassBreakdown } from './ClassBreakdown';
import { TimelinePanel } from './TimelinePanel';
import { PersistenceBoard } from './PersistenceBoard';
import { AlertFeed } from './AlertFeed';
import { FacilityTable } from './FacilityTable';
import { AgentChatPanel } from '@/features/agent/AgentChatPanel';
import { ManualPredictionPanel } from '@/features/ml/ManualPredictionPanel';
import { ModelCardPanel } from '@/features/model/ModelCardPanel';
import { AnalyticsPanel } from '@/features/analytics/AnalyticsPanel';
import { HistoryPanel } from '@/features/history/HistoryPanel';
import { NewsWirePanel } from '@/features/news/NewsWirePanel';
import { ResizeHandle } from '@/components/ui/ResizeHandle';
import { panelWidth, useUIStore } from '@/store/useUIStore';
import { CLASS_META, CLASS_ORDER } from '@/config/constants';
import { useFireStore } from '@/store/useFireStore';
import { cn } from '@/lib/utils/cn';

export function RightDock() {
  const panel = useUIStore((s) => s.panel);
  const width = useUIStore((s) => panelWidth(s.panelSizes, 'rightDock'));
  const setPanelSize = useUIStore((s) => s.setPanelSize);
  const resetPanelSize = useUIStore((s) => s.resetPanelSize);
  const filters = useFireStore((s) => s.filters);
  const setFilters = useFireStore((s) => s.setFilters);
  const source = useFireStore((s) => s.source);

  return (
    <aside className="relative flex shrink-0 flex-col gap-2 overflow-y-auto border-l border-edge bg-abyss p-2.5"
      style={{ width }}>
      <ResizeHandle edge="left" width={width} min={360} max={640}
        onChange={(w) => setPanelSize('rightDock', w)}
        onReset={() => resetPanelSize('rightDock')}
        label="Resize right dock (drag, arrow keys, double-click to reset)" />
      <div className="mono rounded-md border border-edge bg-panel/90 px-2.5 py-1.5 text-[9px] uppercase tracking-widest text-dim">
        data source: <span className={source === 'server' ? 'text-ok' : 'text-amber'}>{source === 'server' ? 'fastapi live feed' : 'local sim (backend offline)'}</span>
        <span className="mx-1">·</span>near-real-time (FIRMS 3–6h)
      </div>

      <div className="rounded-md border border-edge bg-panel/90 p-2.5">
        <div className="mono mb-2 text-[9px] uppercase tracking-widest text-dim">filters</div>
        <div className="flex flex-wrap gap-1">
          {CLASS_ORDER.map((c) => {
            const on = filters.classes.includes(c);
            return (
              <button key={c} aria-pressed={on}
                onClick={() => setFilters({ classes: on ? filters.classes.filter((x) => x !== c) : [...filters.classes, c] })}
                className={cn('mono rounded-sm border px-1.5 py-0.5 text-[9px] uppercase tracking-wider transition-colors', on ? 'border-transparent text-void' : 'border-edge text-dim')}
                style={on ? { background: CLASS_META[c].color } : undefined}>
                {CLASS_META[c].short}
              </button>
            );
          })}
        </div>
        <label className="mt-2.5 flex items-center gap-2 text-[10px] text-mute">
          <span className="mono w-20 shrink-0 text-[9px] uppercase tracking-wider text-dim">min conf {filters.minConfidence}</span>
          <input type="range" min={0} max={95} step={5} value={filters.minConfidence} onChange={(e) => setFilters({ minConfidence: Number(e.target.value) })} className="w-full accent-[#FF6B35]" />
        </label>
        <label className="mt-1.5 flex items-center gap-2 text-[10px] text-mute">
          <input type="checkbox" checked={filters.persistentOnly} onChange={(e) => setFilters({ persistentOnly: e.target.checked })} className="accent-[#FFB800]" />
          persistent sources only
        </label>
      </div>

      <KpiStrip />
      {panel === 'overview' && (<><ClassBreakdown /><TimelinePanel /><PersistenceBoard /></>)}
      {panel === 'persistence' && (<><PersistenceBoard /><TimelinePanel /></>)}
      {panel === 'alerts' && <AlertFeed />}
      {panel === 'facilities' && <FacilityTable />}
      {panel === 'agent' && <div className="min-h-[420px] flex-1"><AgentChatPanel /></div>}
      {panel === 'predict' && <ManualPredictionPanel />}
      {panel === 'model' && <ModelCardPanel />}
      {panel === 'analytics' && <AnalyticsPanel />}
      {panel === 'history' && <HistoryPanel />}
      {panel === 'news' && <NewsWirePanel />}
    </aside>
  );
}

