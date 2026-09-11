import { useState } from 'react';
import { Box as BoxIcon, X } from 'lucide-react';
import { useUIStore } from '@/store/useUIStore';
import { useFireStore } from '@/store/useFireStore';
import { useMapDiagStore } from '@/store/useMapDiagStore';
import { CLASS_META, RISK_META } from '@/config/constants';
import { Badge } from '@/components/ui/Badge';
import { ThreeScene } from '@/features/scene/ThreeScene';
import { CanvasScene } from '@/features/scene/CanvasScene';

/** Incident scene shell: Three.js where WebGL rasterizes, else isometric Canvas2D.
 *  The scene ALWAYS starts now — previously it refused on hosts with a dead GL raster. */
export function Scene3DViewer() {
  const sceneEventId = useUIStore((s) => s.sceneEventId);
  const setSceneEventId = useUIStore((s) => s.setSceneEventId);
  const events = useFireStore((s) => s.events);
  const facilities = useFireStore((s) => s.facilities);
  const capability = useMapDiagStore((s) => s.capability);
  // Session-15: the isometric Canvas2D scene is the default (renders on every host);
  // "try GL" opts into ThreeScene only where rasterization is proven.
  const [sceneRenderer, setSceneRenderer] = useState<'canvas2d' | 'gl'>('canvas2d');
  const ev = events.find((e) => e.id === sceneEventId) ?? null;
  if (!ev) return null;
  const renderer: 'webgl' | 'canvas2d' = sceneRenderer === 'gl' && capability?.rasterizes ? 'webgl' : 'canvas2d';

  return (
    <div role="dialog" aria-label={`3D incident scene ${ev.id}`} className="fixed inset-0 z-50 grid place-items-center bg-void/80 backdrop-blur-sm">
      <div className="flex h-[70vh] w-[min(880px,92vw)] flex-col overflow-hidden rounded-md border border-edge bg-panel">
        <header className="flex items-center gap-2 border-b border-edge px-3 py-2">
          <BoxIcon className="h-4 w-4 text-amber" />
          <span className="mono text-[11px] uppercase tracking-widest text-mute">3D incident scene · {ev.id}</span>
          <Badge color={CLASS_META[ev.classification.primary].color}>{CLASS_META[ev.classification.primary].label}</Badge>
          <Badge color={RISK_META[ev.risk.level].color}>risk {ev.risk.score}</Badge>
          <Badge color="#8ca0b3">renderer: {renderer}</Badge>
          <button
            onClick={() => setSceneRenderer(sceneRenderer === 'gl' ? 'canvas2d' : 'gl')}
            className="mono rounded-sm border border-edge px-1.5 py-0.5 text-[9px] uppercase tracking-wider text-mute hover:text-ink"
          >
            {sceneRenderer === 'gl' ? 'force canvas' : 'try GL'}
          </button>
          <button onClick={() => setSceneEventId(null)} aria-label="Close 3D scene" className="ml-auto rounded p-1 text-mute hover:text-ink">
            <X className="h-4 w-4" />
          </button>
        </header>
        <div className="relative min-h-0 flex-1 bg-abyss">
          {renderer === 'webgl' ? <ThreeScene ev={ev} facilities={facilities} /> : <CanvasScene ev={ev} facilities={facilities} />}
        </div>
        <footer className="mono border-t border-edge px-3 py-1.5 text-[9px] uppercase tracking-widest text-dim">
          1 unit = 100 m · drag orbit · wheel zoom · rings = 6/12/24 h spread forecast (model, not observation)
          {renderer === 'canvas2d' && ' · isometric canvas renderer (webgl rasterization unavailable here)'}
        </footer>
      </div>
    </div>
  );
}
