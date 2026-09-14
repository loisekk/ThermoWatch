import { Component, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Box as BoxIcon, X, RefreshCw } from 'lucide-react';
import { useUIStore } from '@/store/useUIStore';
import { useFireStore } from '@/store/useFireStore';
import { useMapDiagStore } from '@/store/useMapDiagStore';
import { useSceneContextStore } from '@/store/useSceneContextStore';
import { CLASS_META, RISK_META } from '@/config/constants';
import { Badge } from '@/components/ui/Badge';
import { ThreeScene } from '@/features/scene/ThreeScene';
import { CanvasScene } from '@/features/scene/CanvasScene';
import { capByFrp, replayWindow, type Detection } from '@/features/scene/sceneData';
import { enuUnits, nearestBuildingM, type BuildingPick, type SceneContext } from '@/features/scene/osmScene';
import { scaleBarMeters, LEGEND } from '@/features/scene/cartography';
import { resolveSceneRenderer } from '@/features/scene/glSelfCheck';
import { API_BASE } from '@/services/api/client';

const CAMERA_FOV = 45;          // matches ThreeScene's PerspectiveCamera
const CANVAS_FIXED_SCALE_M = 200; // iso canvas: fixed honest scale at default zoom

/** T10 local boundary: a throw inside the GL scene swaps to CanvasScene in the
 *  SAME dialog — the app-wide boundary stays as the last resort only. */
class SceneErrorBoundary
  extends Component<{ onError: () => void; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch() { this.props.onError(); }
  render() { return this.state.failed ? null : this.props.children; }
}

function ageMin(iso: string | null): string {
  if (!iso) return '--';
  const min = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 60_000));
  return min < 1 ? '<1' : `${min} m`;
}

/** Incident scene shell: Three.js where WebGL rasterizes, else isometric Canvas2D.
 *  The scene ALWAYS starts now — previously it refused on hosts with a dead GL raster.
 *  Session 23: per-detection FIRMS hotspot cloud + replay when the live buffer has data. */
export function Scene3DViewer() {
  const sceneEventId = useUIStore((s) => s.sceneEventId);
  const setSceneEventId = useUIStore((s) => s.setSceneEventId);
  const events = useFireStore((s) => s.events);
  const facilities = useFireStore((s) => s.facilities);
  const capability = useMapDiagStore((s) => s.capability);
  const [sceneRenderer, setSceneRenderer] = useState<'canvas2d' | 'gl'>('canvas2d');
  // T10 GL pin ladder: first GL death = one silent remount; second = permanent
  // honest pin (chip says why). sceneError = the local boundary caught a throw.
  const [glAttempts, setGlAttempts] = useState(0);
  const [pin, setPin] = useState<string | null>(null);
  const [sceneError, setSceneError] = useState(false);
  // Per-detection buffer for the selected event (null = fetch failed/unavailable
  // → honest centroid-mode fallback, never a black scene).
  const [dets, setDets] = useState<Detection[] | null>(null);
  // null = latest; epoch ms = replay scrub position (Three only; canvas parity skips replay).
  const [replayT, setReplayT] = useState<number | null>(null);
  const ev = events.find((e) => e.id === sceneEventId) ?? null;

  // T10 pin ladder: first GL death gets ONE remount attempt (fresh context),
  // the second death pins the dialog to Canvas2D with the reason on the chip.
  const onGlDead = (reason: string) => {
    if (glAttempts < 1) setGlAttempts((a) => a + 1);
    else setPin(reason);
  };
  useEffect(() => { setSceneError(false); }, [sceneEventId, glAttempts]);

  useEffect(() => {
    let on = true;
    setDets(null);
    setReplayT(null);
    if (!sceneEventId) return;
    fetch(`${API_BASE}/api/v1/events/${sceneEventId}/detections?days=30`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((j) => { if (on) setDets((j.detections ?? []) as Detection[]); })
      .catch(() => { if (on) setDets(null); });
    return () => { on = false; };
  }, [sceneEventId]);

  // Live OSM surroundings (real footprints/trees/roads/water) — server-cached;
  // fetch is abortable, debounced per event, and re-runs on REFRESH (rate-guarded).
  const setCtx = useSceneContextStore((s) => s.setCtx);
  const refreshKey = useSceneContextStore((s) => s.refreshKey);
  const sharedCtx = useSceneContextStore((s) => s.eventId === sceneEventId ? s.context : null);
  const ctxLoading = useSceneContextStore((s) => s.eventId === sceneEventId && s.loading);
  useEffect(() => {
    let on = true;
    const ctrl = new AbortController();
    if (!sceneEventId) return;
    setCtx({ eventId: sceneEventId, loading: true });
    const url = `${API_BASE}/api/v1/scene/context?lat=${ev?.lat ?? 0}&lon=${ev?.lon ?? 0}&radius_m=1200`;
    fetch(url, { signal: ctrl.signal })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((j) => { if (on) setCtx({ context: j as SceneContext, loading: false }); })
      .catch(() => { if (on) setCtx({ context: null, loading: false }); });
    return () => { on = false; ctrl.abort(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sceneEventId, refreshKey]);

  // Spot checks below must ALL run as hooks every render, so the early return
  // for a missing event sits AFTER them (null-safe when ev is undefined).
  // T10 doctrine restore: canvas-first. GL only when the user forced it AND the
  // probe proves rasterization AND the pin ladder has not retired GL here.
  const renderer: 'webgl' | 'canvas2d' =
    !sceneError && resolveSceneRenderer({
      forced: sceneRenderer === 'gl',
      rasterizes: capability?.rasterizes,
      pinned: pin !== null,
    }) === 'webgl' ? 'webgl' : 'canvas2d';
  const shown = dets ? capByFrp(dets) : null;
  const win = shown && shown.length ? replayWindow(shown) : null;
  const detCount = shown?.length ?? 0;

  const hasOsm = sharedCtx?.source === 'osm-overpass';
  const bld = sharedCtx?.buildings.length ?? 0;
  const treeCount = sharedCtx?.trees.length ?? 0;

  // T9: hover provenance, OSM mesh-count truth chip, scale bar + north arrow.
  const [hover, setHover] = useState<BuildingPick | null>(null);
  const [hoverPos, setHoverPos] = useState({ x: 0, y: 0 });
  const [cam, setCam] = useState({ dist: 26, yaw: 45 });
  const [osmMeshes, setOsmMeshes] = useState(0);
  const bodyRef = useRef<HTMLDivElement>(null);
  const [bodyH, setBodyH] = useState(400);
  useEffect(() => {
    const el = bodyRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setBodyH(el.clientHeight || 400));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const mPerPx = (2 * cam.dist * Math.tan((CAMERA_FOV * Math.PI) / 360) * 100) / Math.max(1, bodyH);
  const scaleM = renderer === 'webgl'
    ? scaleBarMeters(cam.dist, CAMERA_FOV, Math.max(1, bodyH))
    : CANVAS_FIXED_SCALE_M;
  const scalePx = renderer === 'webgl' ? scaleM / mPerPx : 120;
  const ctxChip = ctxLoading
    ? { text: 'CONTEXT: OSM loading…', color: '#8CA0B3' }
    : !hasOsm
      ? { text: 'CONTEXT: SCHEMATIC (OSM unreachable)', color: '#FF6B35' }
      : bld < 3
        ? { text: `CONTEXT: OSM SPARSE · ${bld} bld — rendering what exists`, color: '#FFB800' }
        : { text: `CONTEXT: OSM LIVE · ${bld} bld / ${treeCount} trees · snapshot ${ageMin(sharedCtx!.snapshot_at)} ago`, color: '#3FB950' };

  // Anti-confusion callout: top-FRP hotspot vs the nearest REAL OSM building.
  const callout = useMemo(() => {
    if (!ev || !hasOsm || !sharedCtx || !shown?.length) return null;
    const top = shown[0];
    const origin = { lat: ev.lat, lon: ev.lon };
    const u = enuUnits(origin, top.lat, top.lon);
    const nb = nearestBuildingM(u.x, u.z, origin, sharedCtx.buildings);
    if (!nb) return null;
    return { text: `≈${Math.round(nb.m)} m from OSM way ${nb.id}… (${nb.kind})`,
             x: u.x, z: u.z, id: nb.id, kind: nb.kind, m: nb.m };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sharedCtx, shown, ev]);
  useEffect(() => {
    setCtx({ nearest: callout ? { m: callout.m, id: callout.id, kind: callout.kind } : null });
  }, [callout, setCtx]);

  if (!ev) return null;

  return (
    <div role="dialog" aria-label={`3D incident scene ${ev.id}`} className="fixed inset-0 z-50 grid place-items-center bg-void/80 backdrop-blur-sm">
      <div className="flex h-[70vh] w-[min(880px,92vw)] flex-col overflow-hidden rounded-md border border-edge bg-panel">
        <header className="flex items-center gap-2 border-b border-edge px-3 py-2">
          <BoxIcon className="h-4 w-4 text-amber" />
          <span className="mono text-[11px] uppercase tracking-widest text-mute">3D incident scene · {ev.id}</span>
          <Badge color={CLASS_META[ev.classification.primary].color}>{CLASS_META[ev.classification.primary].label}</Badge>
          <Badge color={RISK_META[ev.risk.level].color}>risk {ev.risk.score}</Badge>
          <Badge color="#8ca0b3">renderer: {renderer}</Badge>
          {pin && (
            <Badge color="#FFB800">
              GL RASTER UNRELIABLE HERE ({pin}) — PINNED TO CANVAS2D · force to retry
            </Badge>
          )}
          {sceneError && (
            <Badge color="#FFB800">SCENE ERROR — CANVAS FALLBACK</Badge>
          )}
          <Badge color={detCount ? '#FF6B35' : '#FFB800'}>
            {detCount ? `hotspots: ${detCount} (viirs 375 m)` : 'per-detection unavailable — centroid mode'}
          </Badge>
          <Badge color={ctxChip.color}>{ctxChip.text}</Badge>
          {hasOsm && (
            <Badge color="#6b7480">
              OSM MESHES: {osmMeshes}
            </Badge>
          )}
          <button
            onClick={() => useSceneContextStore.getState().bumpRefresh()}
            title="Force re-fetch OSM context (server rate-guards: min 60 s/cell)"
            className="mono flex items-center gap-1 rounded-sm border border-edge px-1.5 py-0.5 text-[9px] uppercase tracking-wider text-mute hover:text-ember"
          >
            <RefreshCw className="h-3 w-3" /> refresh context
          </button>
          <button
            onClick={() => {
              setPin(null); setGlAttempts(0); setSceneError(false);
              setSceneRenderer(sceneRenderer === 'gl' ? 'canvas2d' : 'gl');
            }}
            className="mono rounded-sm border border-edge px-1.5 py-0.5 text-[9px] uppercase tracking-wider text-mute hover:text-ink"
          >
            {sceneRenderer === 'gl' ? 'force canvas' : 'try GL'}
          </button>
          <button onClick={() => setSceneEventId(null)} aria-label="Close 3D scene" className="ml-auto rounded p-1 text-mute hover:text-ink">
            <X className="h-4 w-4" />
          </button>
        </header>
        <div ref={bodyRef} className="relative min-h-0 flex-1 bg-abyss">
          {renderer === 'webgl' ? (
            <SceneErrorBoundary key={glAttempts} onError={() => setSceneError(true)}>
              <ThreeScene ev={ev} facilities={facilities} detections={shown} replayT={replayT}
                osm={hasOsm ? sharedCtx : null} callout={callout}
                onHover={(pick, cx, cy) => { setHover(pick); setHoverPos({ x: cx, y: cy }); }}
                onOsmStats={(s) => setOsmMeshes(s.meshes)}
                onCamera={(dist, yaw) => setCam({ dist, yaw })}
                onGlDead={onGlDead} />
            </SceneErrorBoundary>
          ) : (
            <CanvasScene ev={ev} facilities={facilities} detections={shown} osm={hasOsm ? sharedCtx : null} />
          )}
          {renderer === 'webgl' && win && (
            <div className="absolute bottom-2 left-1/2 z-10 flex w-[min(520px,88%)] -translate-x-1/2 items-center gap-2 rounded-sm border border-edge bg-panel/90 px-2 py-1">
              <span className="mono text-[9px] uppercase tracking-widest text-dim">replay</span>
              <input
                type="range"
                aria-label="Replay detection acquisitions"
                min={win.fromMs}
                max={win.toMs}
                step={Math.max(1, Math.floor((win.toMs - win.fromMs) / 400))}
                value={replayT ?? win.toMs}
                onChange={(e) => setReplayT(Number(e.target.value))}
                className="w-full accent-[#FF6B35]"
              />
              <button
                onClick={() => setReplayT(null)}
                className="mono rounded-sm border border-edge px-1.5 py-0.5 text-[9px] uppercase tracking-wider text-mute hover:text-ember"
              >
                latest
              </button>
            </div>
          )}
          {/* T9 overlays — legend (bottom-left), scale bar + north arrow (bottom-right) */}
          <div className="pointer-events-none absolute bottom-3 left-3 z-10 flex flex-col gap-1 rounded-sm border border-edge bg-panel/90 px-2 py-1.5">
            {LEGEND.map((l) => (
              <span key={l.text} className="mono flex items-center gap-1.5 text-[9px] text-mute">
                <i className="inline-block h-2 w-2" style={{ background: l.color }} />{l.text}
              </span>
            ))}
          </div>
          <div className="pointer-events-none absolute bottom-3 right-3 z-10 flex items-end gap-2 rounded-sm border border-edge bg-panel/90 px-2 py-1.5">
            <div className="flex flex-col items-center">
              <div className="relative border-b border-ink" style={{ width: `${Math.round(scalePx)}px`, height: '4px' }}>
                <span className="absolute -bottom-0.5 left-0 h-2 w-px bg-ink" />
                <span className="absolute -bottom-0.5 right-0 h-2 w-px bg-ink" />
              </div>
              <span className="mono mt-0.5 text-[9px] text-mute">{scaleM} m</span>
            </div>
            <span className="mono flex items-end gap-1 text-[9px] leading-none text-mute">
              {/* T10: inline SVG only — no <img> assets inside the scene dialog */}
              <svg width="10" height="8" viewBox="0 0 10 8" aria-hidden="true" style={{
                transform: renderer === 'webgl' ? `rotate(${cam.yaw}deg)` : undefined,
              }}>
                <path d="M5 0 L9 8 L5 6 L1 8 Z" fill="currentColor" />
              </svg>
              <span>N</span>
            </span>
          </div>
          {/* hover provenance tooltip (page-coords from the WebGL pointer event) */}
          {hover && renderer === 'webgl' && (
            <div className="mono pointer-events-none fixed z-[60] rounded-sm border border-edge bg-panel px-2 py-1 text-[10px] text-ink"
              style={{ left: hoverPos.x + 12, top: hoverPos.y + 12 }}>
              OSM way {hover.id} · {hover.kind}{hover.name ? ` · ${hover.name}` : ''}
              {hover.height_m ? ` · ${hover.height_m} m (${hover.height_source})` : ''}
              {hover.m ? ` · ≈${Math.round(hover.m)} m` : ''}
            </div>
          )}
        </div>
        <footer className="mono border-t border-edge px-3 py-1.5 text-[9px] uppercase tracking-widest text-dim">
          1 unit = 100 m · hotspots = firms viirs 375 m detections (near-real-time 3–6 h) · {hasOsm ? 'context = osm buildings/vegetation/roads (live snapshot · © osm odbl)' : 'context = schematic (osm unreachable)'} · drag orbit · wheel zoom · rings = 6/12/24 h spread forecast (model, not observation) · plume illustrative
          {renderer === 'canvas2d' && ` · ${pin
            ? `gl pinned on this host (${pin})`
            : sceneError
              ? 'scene error — canvas fallback'
              : 'isometric canvas renderer (webgl rasterization unavailable here)'} · plume/replay off · osm carto`}
        </footer>
      </div>
    </div>
  );
}
