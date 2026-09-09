import { lazy, Suspense, useMemo } from 'react';
import { Home, Minus, Plus } from 'lucide-react';
import { CLASS_META, CLASS_ORDER } from '@/config/constants';
import { useUIStore } from '@/store/useUIStore';
import { useFireStore } from '@/store/useFireStore';
import { useAnalyticsStore } from '@/store/useAnalyticsStore';
import { useMapDiagStore } from '@/store/useMapDiagStore';
import { detectWebGL } from '@/features/map2d/WebGLProbe';
import { AdvancedModeToggle } from '@/features/analytics/AdvancedModeToggle';
import { TimeSlider } from '@/features/analytics/TimeSlider';
import { TimeRangeChips } from './TimeRangeChips';
import { LayerPanel } from '@/components/panels/LayerPanel';

// Lazy viewport engines: three.js (globe) / MapLibre / canvas fallback + the
// bundled world-geo chunk only download when first shown.
const Map2DView = lazy(() => import('./Map2DView').then((m) => ({ default: m.Map2DView })));
const Globe3DView = lazy(() => import('./Globe3DView').then((m) => ({ default: m.Globe3DView })));
const FallbackWorldMap = lazy(() => import('@/features/map2d/FallbackWorldMap').then((m) => ({ default: m.FallbackWorldMap })));

/** IR camera-style FRP scale + legend + viewport badge overlays + Advanced Mode. */
export function ViewStage() {
  const viewMode = useUIStore((s) => s.viewMode);
  const paused = useFireStore((s) => s.paused);
  const events = useFireStore((s) => s.events);
  const advancedMode = useAnalyticsStore((s) => s.advancedMode);
  const layers = useAnalyticsStore((s) => s.layers);
  const mode = useMapDiagStore((s) => s.mode);
  const mapErrors = useMapDiagStore((s) => s.errors);
  const mapApi = useMapDiagStore((s) => s.mapApi);
  const webgl = useMemo(detectWebGL, []);

  return (
    <div className="hud-corners relative min-w-0 flex-1 overflow-hidden bg-abyss">
      <i aria-hidden />
      <Suspense fallback={<div className="mono absolute inset-0 grid place-items-center text-[11px] uppercase tracking-widest text-dim">initialising viewport engine…</div>}>
        {viewMode === '3d' ? <Globe3DView /> : webgl ? <Map2DView /> : <FallbackWorldMap events={events} />}
      </Suspense>

      <div className="mono pointer-events-none absolute left-4 top-4 flex gap-2 text-[10px] uppercase tracking-widest">
        <span className="rounded-sm border border-edge2 bg-panel/80 px-2 py-1 text-mute">
          {viewMode === '2d' ? `ORTHO-2D · ${mode === 'canvas2d-fallback' ? 'CANVAS2D' : 'VECTOR-110M'} (WORLD)` : 'ORB-3D · NIGHT-LIGHTS'}
        </span>
        <span className={`rounded-sm border px-2 py-1 ${paused ? 'border-edge2 text-dim' : 'border-ok/40 text-ok'}`}>{paused ? 'HELD' : 'LIVE'}</span>
      </div>

      {viewMode === '2d' && (
        <>
          <div className="absolute left-4 top-14 flex flex-col gap-2">
            <TimeRangeChips />
            <div className="pointer-events-none flex max-w-[46vw] flex-col gap-1">
              {mapErrors.slice(-2).map((e, i) => (
                <span key={`${i}-${e}`} className="mono rounded-sm border border-magma/40 bg-magma/10 px-2 py-1 text-[9px] text-magma">{e.slice(0, 90)}</span>
              ))}
            </div>
          </div>
          <div className="absolute left-4 top-28 bottom-44 flex flex-col justify-start">
            <LayerPanel />
          </div>
        </>
      )}

      <div className="absolute right-4 top-4 z-10 flex flex-col items-end gap-2">
        {viewMode === '2d' && <AdvancedModeToggle />}
        {viewMode === '2d' && (
          <div className="flex flex-col overflow-hidden rounded-sm border border-edge bg-panel/90">
            <button onClick={() => mapApi?.zoomIn()} aria-label="Zoom in" className="grid h-8 w-8 place-items-center text-mute hover:bg-panel2 hover:text-ink"><Plus className="h-4 w-4" /></button>
            <button onClick={() => mapApi?.zoomOut()} aria-label="Zoom out" className="grid h-8 w-8 place-items-center border-t border-edge text-mute hover:bg-panel2 hover:text-ink"><Minus className="h-4 w-4" /></button>
            <button onClick={() => mapApi?.reset()} aria-label="Reset view" className="grid h-8 w-8 place-items-center border-t border-edge text-mute hover:bg-panel2 hover:text-ink"><Home className="h-4 w-4" /></button>
          </div>
        )}
      </div>

      <div className="pointer-events-none absolute right-4 top-1/2 flex -translate-y-1/2 flex-col items-center gap-1">
        <span className="mono text-[8px] uppercase tracking-widest text-dim">FRP MW</span>
        <div className="h-40 w-2.5 rounded-full" style={{ background: 'linear-gradient(to bottom, #FF4444, #FF6B35, #FFB800, #2A3644)' }} />
        <span className="mono text-[8px] text-dim">800+</span>
        <span className="mono text-[8px] text-dim">100</span>
        <span className="mono text-[8px] text-dim">20</span>
      </div>

      <div className="pointer-events-none absolute bottom-4 right-4 rounded-sm border border-edge bg-panel/85 p-2.5">
        <div className="mono mb-1.5 text-[9px] uppercase tracking-widest text-dim">legend</div>
        <ul className="space-y-1">
          {CLASS_ORDER.map((c) => (
            <li key={c} className="flex items-center gap-2 text-[10px] text-mute">
              <span className="h-2 w-2 rounded-full" style={{ background: CLASS_META[c].color }} />
              {CLASS_META[c].label}
            </li>
          ))}
          <li className="flex items-center gap-2 text-[10px] text-mute">
            <span className="h-2.5 w-2.5 rounded-full border" style={{ borderColor: CLASS_META.persistent.color }} />
            persistent ring (≥5 d)
          </li>
          <li className="flex items-center gap-2 text-[10px] text-mute">
            <span className="h-2 w-2 rounded-full border border-steel bg-panel2" />
            OSM industrial facility
          </li>
        </ul>
        {advancedMode && viewMode === '2d' && (
          <div className="mt-2 border-t border-edge pt-2">
            <div className="mono mb-1 text-[9px] uppercase tracking-widest text-dim">advanced layers</div>
            <ul className="space-y-0.5 text-[9px] text-mute">
              {layers.hexagonDensity && <li>· hex density (1 km cells)</li>}
              {layers.buildingExtrusion && <li>· facility extrusion (3D)</li>}
              {layers.spreadRings && <li>· spread forecast (6/12/24 h)</li>}
            </ul>
          </div>
        )}
      </div>

      {advancedMode && viewMode === '2d' && layers.timeSlider && <TimeSlider />}
    </div>
  );
}
