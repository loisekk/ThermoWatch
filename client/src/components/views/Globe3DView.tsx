import { useEffect, useRef, useState } from 'react';
import Globe, { type GlobeMethods } from 'react-globe.gl';
import { MeshPhongMaterial } from 'three';
import { CLASS_META, SUBTYPE_LABEL } from '@/config/constants';
import { filterEvents } from '@/selectors/fireSelectors';
import { useFireStore } from '@/store/useFireStore';
import { useAnalyticsStore } from '@/store/useAnalyticsStore';
import { useMapDiagStore } from '@/store/useMapDiagStore';
import type { Facility, FireEvent } from '@/types/domain';

const pointLabel = (d: object): string => {
  const e = d as FireEvent;
  const m = CLASS_META[e.classification.primary];
  return `<div class="map-pop"><b>${m.label}</b> · ${e.classification.confidence}%<br/>FRP ${e.frp} MW · ${e.persistence.regime}<br/>risk ${e.risk.score}</div>`;
};

const hexColor = (d: object): string => {
  const p = (d as { properties?: { subtype?: string } }).properties;
  const subtype = p?.subtype ?? 'unknown';
  const bySubtype: Record<string, string> = {
    refinery: '#FF6B35',
    steel: '#7D8DA1',
    gas_flare: '#FFB800',
    cement: '#B4B4B4',
    smelter: '#C89664',
    chemical: '#96C896',
    power_plant: '#6496C8',
    waste_incineration: '#8C8C8C',
  };
  return `${bySubtype[subtype] ?? '#8CA0B3'}AA`;
};

const hexAltitude = (d: object): number => {
  const h = (d as { properties?: { hazard?: string } }).properties?.hazard;
  return ({ 'G-III': 0.14, 'G-II': 0.08, 'G-I': 0.04 } as Record<string, number>)[h ?? ''] ?? 0.05;
};

const hexLabel = (d: object): string => {
  const p = (d as { properties?: { name?: string; subtype?: string; hazard?: string } }).properties;
  const subtype = SUBTYPE_LABEL[(p?.subtype ?? '') as keyof typeof SUBTYPE_LABEL] ?? p?.subtype ?? 'Facility';
  return `<div class="map-pop"><b>${p?.name ?? 'Facility'}</b><br/>${subtype} · hazard ${p?.hazard ?? ''}</div>`;
};

/** Facilities -> tiny GeoJSON squares (three-globe hexPolygons needs Polygon geometry). */
const FACILITY_POLY = 0.15; // degrees (~16 km at equator) — enough to bin as a hex column
const facilityGeoJson = (f: Facility): { type: 'Feature'; properties: { id: string; name: string; subtype: string; hazard: string }; geometry: { type: 'Polygon'; coordinates: number[][][] } } => ({
  type: 'Feature',
  properties: { id: f.id, name: f.name, subtype: f.subtype, hazard: f.hazard },
  geometry: {
    type: 'Polygon',
    coordinates: [[
      [f.lon - FACILITY_POLY, f.lat - FACILITY_POLY],
      [f.lon + FACILITY_POLY, f.lat - FACILITY_POLY],
      [f.lon + FACILITY_POLY, f.lat + FACILITY_POLY],
      [f.lon - FACILITY_POLY, f.lat + FACILITY_POLY],
      [f.lon - FACILITY_POLY, f.lat - FACILITY_POLY],
    ]],
  },
});

const hexFeatures = (facilities: Facility[]) => facilities.map(facilityGeoJson);
// react-globe.gl types GeoJsonGeometry as flat { type, coordinates: number[] }, but
// three-globe genuinely accepts full GeoJSON Polygon/MultiPolygon — cast through unknown.
const hexGeom = (d: object) => (d as { geometry: object }).geometry as unknown as { type: string; coordinates: number[] };

/** Texture candidates, probed in order. Local first, CDN fallback. */
const TEXTURE_CANDIDATES = [
  '/textures/earth-night.jpg',
  'https://unpkg.com/three-globe/example/img/earth-night.jpg',
];

async function probeTexture(timeoutMs = 4000): Promise<string | null> {
  for (const url of TEXTURE_CANDIDATES) {
    try {
      const ok = await new Promise<boolean>((resolve) => {
        const img = new Image();
        const timer = window.setTimeout(() => resolve(false), timeoutMs);
        img.onload = () => { window.clearTimeout(timer); resolve(img.naturalWidth > 512); };
        img.onerror = () => { window.clearTimeout(timer); resolve(false); };
        img.src = url;
      });
      if (ok) return url;
    } catch {
      continue;
    }
  }
  return null;
}

/**
 * Textured GL orb (the Image-1 look): night-lights texture × blue material tint by default,
 * hex-column facility extrusions by NBC hazard, fire points, persistent pulse rings.
 *
 * Resilience:
 *  - Frame-liveness watchdog: polls three.js renderer.info.render.frame every 1.5 s; two frozen
 *    checks trigger one auto-remount; still frozen -> pinned to the canvas renderer.
 *  - Context-loss listener: preventDefault + auto-remount on webglcontextlost.
 *  - Dev handle: window.__twgl() -> true when the orb context is lost.
 */
export function Globe3DView() {
  const wrap = useRef<HTMLDivElement>(null);
  const globe = useRef<GlobeMethods | undefined>(undefined);
  const [dims, setDims] = useState({ w: 800, h: 600 });
  const [ready, setReady] = useState(false);
  const [textureUrl, setTextureUrl] = useState<string | null>(null);
  const [tint, setTint] = useState<'blue' | 'night'>('blue');
  const [mountKey, setMountKey] = useState(0);
  const [recovery, setRecovery] = useState<'none' | 'remounting' | 'pinned'>('none');
  const remounts = useRef(0);

  const events = useFireStore((s) => s.events);
  const filters = useFireStore((s) => s.filters);
  const facilities = useFireStore((s) => s.facilities);
  const select = useFireStore((s) => s.select);
  const selectFacility = useFireStore((s) => s.selectFacility);
  const timeRange = useAnalyticsStore((s) => s.timeRange);
  const setGlobeOverride = useAnalyticsStore((s) => s.setGlobeOverride);
  const webgl = useMapDiagStore((s) => s.webgl);

  const filtered = filterEvents(events, filters).filter((e) => e.detectedAt >= timeRange.start && e.detectedAt <= timeRange.end);
  const persistent = filtered.filter((e) => e.persistence.regime === 'persistent');
  const hexData = hexFeatures(facilities);

  // Blue-earth / night tint via a controlled Phong material (globeMaterial prop).
  const globeMat = new MeshPhongMaterial({ color: tint === 'blue' ? '#7ea8c8' : '#ffffff' });

  useEffect(() => {
    let on = true;
    probeTexture().then((url) => { if (on) setTextureUrl(url); });
    return () => { on = false; };
  }, []);

  useEffect(() => {
    if (!wrap.current) return;
    const ro = new ResizeObserver(() => {
      const r = wrap.current?.getBoundingClientRect();
      if (r) setDims({ w: r.width, h: r.height });
    });
    ro.observe(wrap.current);
    const r = wrap.current.getBoundingClientRect();
    setDims({ w: r.width, h: r.height });
    return () => ro.disconnect();
  }, []);

  // Frame-liveness watchdog: two frozen render-loop checks -> one remount -> pin to canvas.
  useEffect(() => {
    if (!ready) return;
    const renderer = globe.current?.renderer?.() as { info?: { render?: { frame?: number } }; domElement?: HTMLCanvasElement } | undefined;
    if (!renderer?.info) return;
    let last = renderer.info.render?.frame ?? 0;
    let misses = 0;
    const id = window.setInterval(() => {
      const now = renderer.info?.render?.frame ?? 0;
      if (now === last) {
        misses += 1;
        if (misses >= 2) {
          misses = 0;
          const gl = renderer.domElement?.getContext('webgl2') ?? renderer.domElement?.getContext('webgl');
          const lost = gl ? gl.isContextLost() : false;
          useMapDiagStore.getState().pushError(lost ? 'gl context lost — rebuilding orb' : 'gl render loop stalled — rebuilding orb');
          if (remounts.current < 1) {
            remounts.current += 1;
            setRecovery('remounting');
            setMountKey((k) => k + 1);
            window.setTimeout(() => setRecovery('none'), 800);
          } else {
            setRecovery('pinned');
            setGlobeOverride('canvas');
            useMapDiagStore.getState().pushError('gl unrecoverable here — pinned to canvas renderer');
          }
        }
      } else {
        misses = 0;
      }
      last = now;
    }, 1500);
    return () => window.clearInterval(id);
  }, [ready, mountKey, setGlobeOverride]);

  // Blue-earth default tint is supplied via the globeMaterial prop (MeshPhongMaterial
  // above); on tint change we simply create a fresh material and pass it down.
  useEffect(() => {
    // no-op: globeMat is recreated reactively per tint render
  }, [tint]);

  // Context-loss listener: preventDefault + auto-remount with a fresh context.
  useEffect(() => {
    if (!ready) return;
    const canvas = globe.current?.renderer?.()?.domElement as HTMLCanvasElement | undefined;
    if (!canvas) return;
    const onLost = (e: Event) => {
      e.preventDefault();
      useMapDiagStore.getState().pushError('webgl context lost — recovering orb');
      setRecovery('remounting');
      window.setTimeout(() => {
        setMountKey((k) => k + 1);
        setRecovery('none');
      }, 600);
    };
    canvas.addEventListener('webglcontextlost', onLost);
    return () => canvas.removeEventListener('webglcontextlost', onLost);
  }, [ready, mountKey]);

  // Camera distance clamp: world stays framed (Session 16 screen-lock on the GL orb).
  useEffect(() => {
    if (!ready) return;
    const c = globe.current?.controls?.();
    if (c) {
      c.minDistance = 1.25;
      c.maxDistance = 3.2;
    }
  }, [ready]);

  // Dev handle: window.__twgl() -> true when the orb context is lost.
  useEffect(() => {
    if (import.meta.env.DEV) {
      (window as unknown as { __twgl?: () => boolean }).__twgl = () => {
        const gl = globe.current?.renderer?.()?.domElement?.getContext('webgl2') ?? globe.current?.renderer?.()?.domElement?.getContext('webgl');
        return !!gl?.isContextLost();
      };
    }
    return () => { (window as unknown as { __twgl?: () => boolean }).__twgl = undefined; };
  }, []);

  if (!textureUrl) {
    return (
      <div className="mono absolute inset-0 grid place-items-center bg-abyss text-[11px] uppercase tracking-widest text-dim" aria-label="3D globe (GL renderer">
        loading globe texture…
      </div>
    );
  }

  if (webgl && webgl.context && !webgl.rasterizes) {
    return (
      <div className="mono absolute inset-0 grid place-items-center bg-abyss p-8 text-center text-[11px] leading-relaxed text-mute">
        <div>
          <p className="mb-2 uppercase tracking-widest text-ember">ORB-3D GL requires working WebGL rasterization</p>
          <p>This environment reports a blank rasterizer ({webgl.renderer}).</p>
          <p className="mt-2">Use the canvas orb (Image-2 look) — it renders reliably on this host.</p>
        </div>
      </div>
    );
  }

  return (
<div ref={wrap} className="absolute inset-0" style={{ background: 'radial-gradient(circle at 50% 42%, #0d1420 0%, #07090d 72%)' }} aria-label="3D globe view (GL renderer)">
      <Globe
        key={mountKey}
        ref={globe}
        width={dims.w}
        height={dims.h}
        backgroundColor="rgba(0,0,0,0)"
        globeImageUrl={textureUrl}
        bumpImageUrl={undefined}
        globeMaterial={globeMat}
        atmosphereColor="#ff6b35"
        atmosphereAltitude={0.16}
        pointsData={filtered}
        pointLat={(d: object) => (d as FireEvent).lat}
        pointLng={(d: object) => (d as FireEvent).lon}
        pointColor={(d: object) => CLASS_META[(d as FireEvent).classification.primary].color}
        pointRadius={(d: object) => 0.2 + (Math.min((d as FireEvent).frp, 800) / 800) * 1.0}
        pointAltitude={0.02}
        pointLabel={pointLabel}
        onPointClick={(d: object) => select((d as FireEvent).id)}
        ringsData={persistent}
        ringLat={(d: object) => (d as FireEvent).lat}
        ringLng={(d: object) => (d as FireEvent).lon}
        ringColor={() => (t: number) => `rgba(255,184,0,${(1 - t) * 0.8})`}
        ringMaxRadius={5}
        ringPropagationSpeed={0.7}
        ringRepeatPeriod={1100}
        hexPolygonsData={hexData}
        hexPolygonGeoJsonGeometry={hexGeom}
        hexPolygonResolution={5}
        hexPolygonMargin={0.35}
        hexPolygonAltitude={hexAltitude}
        hexPolygonColor={hexColor}
        hexPolygonLabel={hexLabel}
        onHexPolygonClick={(d: object) => selectFacility((d as { properties: { id: string } }).properties.id)}
        onGlobeReady={() => setReady(true)}
      />

      {recovery === 'remounting' && (
        <div className="mono pointer-events-none absolute inset-x-0 top-1/2 z-10 text-center text-[11px] uppercase tracking-widest text-amber">
          gl stalled — rebuilding orb…
        </div>
      )}

      {recovery === 'pinned' && (
        <div className="mono pointer-events-none absolute inset-x-0 top-1/2 z-10 text-center text-[11px] uppercase tracking-widest text-amber">
          gl unrecoverable — switching to canvas orb
        </div>
      )}

      {/* Earth tint toggle — GL-only (Image-1 look). */}
      <button
        onClick={() => setTint(tint === 'blue' ? 'night' : 'blue')}
        className="mono absolute right-4 top-16 z-10 rounded-sm border border-edge bg-panel/90 px-2 py-1 text-[9px] uppercase tracking-wider text-mute hover:text-ink"
        title="Switch between blue-earth (default) and pure night-lights tint"
      >
        earth: {tint}
      </button>
    </div>
  );
}