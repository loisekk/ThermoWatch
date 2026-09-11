import { useEffect, useMemo, useRef, useState } from 'react';
import type { FeatureCollection, Geometry, Position } from 'geojson';
import world from '@/assets/world-110m.json';
import { CLASS_META } from '@/config/constants';
import { useFireStore } from '@/store/useFireStore';
import { useUIStore } from '@/store/useUIStore';
import { useAnalyticsStore } from '@/store/useAnalyticsStore';
import { useMapDiagStore } from '@/store/useMapDiagStore';
import { filterEvents } from '@/selectors/fireSelectors';
import { mulberry32 } from '@/lib/random/mulberry';
import type { FireEvent } from '@/types/domain';

const RAD = Math.PI / 180;
const TICK_MS = 66; // setInterval-driven: immune to dead rAF
const LAND = '#1b2127';
const BORDER = '#2a3644';
const OCEAN = '#0d1420';

interface Ring { pts: [number, number][] }
const RINGS: Ring[] = [];
((world as unknown as FeatureCollection<Geometry, Record<string, unknown>>).features).forEach((f) => {
  const g = f.geometry as unknown as { type: string; coordinates: unknown };
  const polys: Position[][][] = g.type === 'Polygon' ? [g.coordinates as Position[][]] : (g.coordinates as Position[][][]);
  polys.forEach((poly) => poly.forEach((ring) => RINGS.push({ pts: ring as [number, number][] })));
});

const STARS = (() => {
  const r = mulberry32(7);
  return Array.from({ length: 260 }, () => ({ x: r(), y: r(), s: 0.4 + r() * 1.1, a: 0.25 + r() * 0.6 }));
})();

interface Projected { x: number; y: number; z: number }
function project(lon: number, lat: number, lon0: number, lat0: number, R: number, cx: number, cy: number): Projected {
  const l = (lon - lon0) * RAD, p = lat * RAD, p0 = lat0 * RAD;
  const z = Math.sin(p0) * Math.sin(p) + Math.cos(p0) * Math.cos(p) * Math.cos(l);
  return {
    x: cx + R * Math.cos(p) * Math.sin(l),
    y: cy - R * (Math.cos(p0) * Math.sin(p) - Math.sin(p0) * Math.cos(p) * Math.cos(l)),
    z,
  };
}

/** Flat-country orthographic globe (the Image-2 look). Texture-free by design. */
export function CanvasGlobe() {
  const wrap = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const view = useRef({ lon0: 78, lat0: 22, zoom: 1, target: null as null | { lon: number; lat: number }, drag: null as null | { x: number; y: number } });
  const hits = useRef<{ x: number; y: number; ev: FireEvent }[]>([]);
  const facHits = useRef<{ x: number; y: number; id: string }[]>([]);
  const [hover, setHover] = useState<{ x: number; y: number; ev: FireEvent } | null>(null);

  const events = useFireStore((s) => s.events);
  const filters = useFireStore((s) => s.filters);
  const facilities = useFireStore((s) => s.facilities);
  const select = useFireStore((s) => s.select);
  const selectFacility = useFireStore((s) => s.selectFacility);
  const focus = useUIStore((s) => s.focus);
  const autoRotate = useUIStore((s) => s.autoRotate);
  const timeRange = useAnalyticsStore((s) => s.timeRange);
  const layers = useAnalyticsStore((s) => s.layers);
  const setMapApi = useMapDiagStore((s) => s.setMapApi);

  const filtered = useMemo(
    () => filterEvents(events, filters).filter((e) => e.detectedAt >= timeRange.start && e.detectedAt <= timeRange.end),
    [events, filters, timeRange],
  );

  useEffect(() => {
    if (focus) view.current.target = { lon: focus.lon, lat: focus.lat };
  }, [focus]);

  useEffect(() => {
    setMapApi({
      zoomIn: () => { view.current.zoom = Math.min(4, view.current.zoom * 1.3); },
      zoomOut: () => { view.current.zoom = Math.max(0.8, view.current.zoom / 1.3); },
      reset: () => { view.current.lon0 = 78; view.current.lat0 = 22; view.current.zoom = 1; },
    });
    return () => setMapApi(null);
  }, [setMapApi]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const wrapEl = wrap.current;
    if (!canvas || !wrapEl) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const draw = () => {
      const cw = wrapEl.clientWidth, ch = wrapEl.clientHeight;
      if (cw === 0 || ch === 0) return;
      canvas.width = cw * devicePixelRatio;
      canvas.height = ch * devicePixelRatio;
      ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
      ctx.clearRect(0, 0, cw, ch);

      const { lon0, lat0, zoom } = view.current;
      const cx = cw / 2, cy = ch / 2;
      const R = Math.min(cw, ch) * 0.42 * zoom;

      // starfield (screen space)
      if (layers.starfield) {
        ctx.fillStyle = '#e8eef5';
        for (const st of STARS) { ctx.globalAlpha = st.a; ctx.fillRect(st.x * cw, st.y * ch, st.s, st.s); }
        ctx.globalAlpha = 1;
      }

      // atmosphere halo
      const halo = ctx.createRadialGradient(cx, cy, R * 0.92, cx, cy, R * 1.18);
      halo.addColorStop(0, 'rgba(255,107,53,0.16)');
      halo.addColorStop(1, 'rgba(255,107,53,0)');
      ctx.fillStyle = halo;
      ctx.beginPath(); ctx.arc(cx, cy, R * 1.18, 0, 7); ctx.fill();

      // ocean + limb
      ctx.fillStyle = OCEAN;
      ctx.beginPath(); ctx.arc(cx, cy, R, 0, 7); ctx.fill();
      ctx.strokeStyle = '#22303d'; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.arc(cx, cy, R, 0, 7); ctx.stroke();

      ctx.save();
      ctx.beginPath(); ctx.arc(cx, cy, R, 0, 7); ctx.clip();

      // graticule
      if (layers.graticule) {
        ctx.strokeStyle = 'rgba(42,54,68,0.55)';
        ctx.lineWidth = 0.6;
        for (let lon = -180; lon <= 180; lon += 15) {
          ctx.beginPath(); let pen = false;
          for (let lat = -90; lat <= 90; lat += 3) {
            const q = project(lon, lat, lon0, lat0, R, cx, cy);
            if (q.z > 0) { if (!pen) { ctx.moveTo(q.x, q.y); pen = true; } else ctx.lineTo(q.x, q.y); }
            else pen = false;
          }
          ctx.stroke();
        }
        for (let lat = -75; lat <= 75; lat += 15) {
          ctx.beginPath(); let pen = false;
          for (let lon = -180; lon <= 180; lon += 3) {
            const q = project(lon, lat, lon0, lat0, R, cx, cy);
            if (q.z > 0) { if (!pen) { ctx.moveTo(q.x, q.y); pen = true; } else ctx.lineTo(q.x, q.y); }
            else pen = false;
          }
          ctx.stroke();
        }
      }

      // flat landmass (Image-2 look: uniform dark countries + borders)
      for (const ring of RINGS) {
        const proj = ring.pts.map(([lon, lat]) => project(lon, lat, lon0, lat0, R, cx, cy));
        const visible = proj.filter((q) => q.z > 0).length;
        if (visible === proj.length && proj.length > 2) {
          ctx.beginPath();
          proj.forEach((q, i) => (i === 0 ? ctx.moveTo(q.x, q.y) : ctx.lineTo(q.x, q.y)));
          ctx.closePath();
          ctx.fillStyle = LAND; ctx.fill();
          ctx.strokeStyle = BORDER; ctx.lineWidth = 0.7; ctx.stroke();
        } else if (visible > 1) {
          ctx.beginPath(); let pen = false;
          for (const q of proj) {
            if (q.z > 0) { if (!pen) { ctx.moveTo(q.x, q.y); pen = true; } else ctx.lineTo(q.x, q.y); }
            else pen = false;
          }
          ctx.strokeStyle = BORDER; ctx.lineWidth = 0.7; ctx.stroke();
        }
      }

      // facility pins (radial bars by NBC hazard) + base dots
      facHits.current = [];
      if (layers.facilities) {
        const HAZ_PX: Record<string, number> = { 'G-III': 26, 'G-II': 16, 'G-I': 9 };
        for (const f of facilities) {
          const q = project(f.lon, f.lat, lon0, lat0, R, cx, cy);
          if (q.z <= 0) continue;
          const dx = q.x - cx, dy = q.y - cy;
          const len = Math.hypot(dx, dy) || 1;
          const ux = dx / len, uy = dy / len;
          const h = (HAZ_PX[f.hazard] ?? 12) * zoom;
          ctx.strokeStyle = '#e8eef5';
          ctx.lineWidth = 1.4;
          ctx.beginPath(); ctx.moveTo(q.x, q.y); ctx.lineTo(q.x + ux * h, q.y + uy * h); ctx.stroke();
          ctx.fillStyle = '#e8eef5';
          ctx.beginPath(); ctx.arc(q.x + ux * h, q.y + uy * h, 2, 0, 7); ctx.fill();
          ctx.fillStyle = '#10161d'; ctx.strokeStyle = '#7d8da1'; ctx.lineWidth = 1;
          ctx.beginPath(); ctx.arc(q.x, q.y, 2.4, 0, 7); ctx.fill(); ctx.stroke();
          facHits.current.push({ x: q.x, y: q.y, id: f.id });
        }
      }

      // persistent pulse rings
      if (layers.persistentRings) {
        const phase = (performance.now() % 1600) / 1600;
        ctx.strokeStyle = CLASS_META.persistent.color;
        ctx.lineWidth = 1.4;
        for (const e of filtered) {
          if (e.persistence.regime !== 'persistent') continue;
          const q = project(e.lon, e.lat, lon0, lat0, R, cx, cy);
          if (q.z <= 0) continue;
          ctx.globalAlpha = 0.7 * (1 - phase) * Math.min(1, q.z * 3);
          ctx.beginPath(); ctx.arc(q.x, q.y, 4 + phase * 12, 0, 7); ctx.stroke();
        }
        ctx.globalAlpha = 1;
      }

      // fire dots + pick buffer
      hits.current = [];
      for (const e of filtered) {
        const q = project(e.lon, e.lat, lon0, lat0, R, cx, cy);
        if (q.z <= 0) continue;
        const r = 2.5 + Math.min(e.frp, 900) / 160;
        ctx.globalAlpha = 0.45 + 0.55 * Math.min(1, q.z * 2);
        ctx.fillStyle = CLASS_META[e.classification.primary].color;
        ctx.beginPath(); ctx.arc(q.x, q.y, r, 0, 7); ctx.fill();
        ctx.globalAlpha = 1;
        hits.current.push({ x: q.x, y: q.y, ev: e });
      }
      ctx.restore();
    };

    draw();
    const ro = new ResizeObserver(draw);
    ro.observe(wrapEl);
    const timer = window.setInterval(() => {
      const v = view.current;
      if (v.target) {
        v.lon0 += (v.target.lon - v.lon0) * 0.12;
        v.lat0 += (v.target.lat - v.lat0) * 0.12;
        if (Math.abs(v.target.lon - v.lon0) < 0.4 && Math.abs(v.target.lat - v.lat0) < 0.4) v.target = null;
      } else if (autoRotate && !v.drag) {
        v.lon0 = (v.lon0 + 0.12) % 360;
      }
      draw();
    }, TICK_MS);

    const onDown = (e: PointerEvent) => { view.current.drag = { x: e.clientX, y: e.clientY }; view.current.target = null; };
    const onMove = (e: PointerEvent) => {
      if (!view.current.drag) return;
      view.current.lon0 -= (e.clientX - view.current.drag.x) * 0.25;
      view.current.lat0 = Math.max(-80, Math.min(80, view.current.lat0 + (e.clientY - view.current.drag.y) * 0.25));
      view.current.drag = { x: e.clientX, y: e.clientY };
    };
    const onUp = (e: PointerEvent) => {
      const wasDrag = view.current.drag && (Math.abs(e.clientX - view.current.drag.x) > 3 || Math.abs(e.clientY - view.current.drag.y) > 3);
      view.current.drag = null;
      if (wasDrag) return;
      const rect = canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left, my = e.clientY - rect.top;
      const fire = hits.current.find((h) => Math.hypot(h.x - mx, h.y - my) < 9);
      if (fire) { select(fire.ev.id); return; }
      const fac = facHits.current.find((h) => Math.hypot(h.x - mx, h.y - my) < 9);
      if (fac) selectFacility(fac.id);
    };
    const onHover = (e: MouseEvent) => {
      if (view.current.drag) return;
      const rect = canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left, my = e.clientY - rect.top;
      const hit = hits.current.find((h) => Math.hypot(h.x - mx, h.y - my) < 9);
      setHover(hit ? { x: mx, y: my, ev: hit.ev } : null);
      canvas.style.cursor = hit ? 'pointer' : 'grab';
    };
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      view.current.zoom = Math.min(4, Math.max(0.8, view.current.zoom * (e.deltaY > 0 ? 0.9 : 1.1)));
    };
    wrapEl.addEventListener('pointerdown', onDown);
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    canvas.addEventListener('mousemove', onHover);
    canvas.addEventListener('wheel', onWheel, { passive: false });
    return () => {
      ro.disconnect();
      window.clearInterval(timer);
      wrapEl.removeEventListener('pointerdown', onDown);
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      canvas.removeEventListener('mousemove', onHover);
      canvas.removeEventListener('wheel', onWheel);
    };
  }, [filtered, facilities, layers, autoRotate, select, selectFacility]);

  return (
    <div ref={wrap} className="absolute inset-0 cursor-grab active:cursor-grabbing" style={{ background: 'radial-gradient(circle at 50% 42%, #0d1420 0%, #07090d 72%)' }} aria-label="3D globe view (canvas renderer)">
      <canvas ref={canvasRef} className="absolute inset-0 h-full w-full" />
      {hover && (
        <div className="map-pop pointer-events-none absolute z-20" style={{ left: hover.x + 12, top: hover.y + 8 }}>
          <b>{CLASS_META[hover.ev.classification.primary].label}</b> · {hover.ev.classification.confidence}%
          <br />FRP {hover.ev.frp} MW · {hover.ev.persistence.regime}
          <br />risk {hover.ev.risk.score}
        </div>
      )}
    </div>
  );
}