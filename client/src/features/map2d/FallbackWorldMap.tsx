import { useEffect, useMemo, useRef, useState } from 'react';
import type { FeatureCollection, Geometry, Position } from 'geojson';
import world from '@/assets/world-110m.json';
import { BORDER, LAND, OCEAN } from '@/config/worldStyle';
import { COUNTRY_LABELS, countryCounts } from '@/lib/geo/countryIndex';
import { CLASS_META } from '@/config/constants';
import { useFireStore } from '@/store/useFireStore';
import { useAnalyticsStore } from '@/store/useAnalyticsStore';
import { useMapDiagStore } from '@/store/useMapDiagStore';
import { filterEvents } from '@/selectors/fireSelectors';
import { coverScale, clampPan, WORLD_W, WORLD_H } from '@/lib/geo/viewClamp';
import { drawGibs } from '@/lib/geo/tiles';
import type { FireEvent } from '@/types/domain';

const W = 2000;
const H = 1000;
const px = (lon: number) => ((lon + 180) / 360) * W;
const py = (lat: number) => ((90 - lat) / 180) * H;

const PATHS: Path2D[] = ((world as unknown as FeatureCollection<Geometry, Record<string, unknown>>).features).map((f) => {
  const path = new Path2D();
  // GeoJSON traversal: a Position is [number, number]; a Ring is Position[].
  // NOTE: the guard must test node[0][0] (first coordinate of the first position) —
  // testing node[0] alone matches bare Positions and crashes on destructure.
  const walk = (node: unknown): void => {
    if (!Array.isArray(node) || node.length === 0) return;
    const first: unknown = node[0];
    if (typeof first === 'number') return; // bare Position reached directly — nothing to stroke
    if (Array.isArray(first) && typeof (first as unknown[])[0] === 'number') {
      // node is a Ring of Positions
      (node as Position[]).forEach(([lon, lat], i) =>
        i === 0 ? path.moveTo(px(lon), py(lat)) : path.lineTo(px(lon), py(lat)),
      );
      path.closePath();
    } else {
      // node is a Polygon ring-list or MultiPolygon polygon-list — keep descending
      node.forEach(walk);
    }
  };
  walk((f.geometry as unknown as { coordinates: unknown }).coordinates);
  return path;
});

const GRAT = (() => {
  const path = new Path2D();
  for (let lon = -180; lon <= 180; lon += 30) {
    path.moveTo(px(lon), py(-90));
    path.lineTo(px(lon), py(90));
  }
  for (let lat = -90; lat <= 90; lat += 30) {
    path.moveTo(px(-180), py(lat));
    path.lineTo(px(180), py(lat));
  }
  return path;
})();
const TICK_MS = 66; // setInterval-driven redraw: immune to dead rAF

const CLASS_RGB: Record<string, [number, number, number]> = {
  industrial: [255, 107, 53], persistent: [255, 184, 0], wildfire: [255, 68, 68], agricultural: [143, 209, 79],
};

function hexPath(ctx: CanvasRenderingContext2D, x: number, y: number, r: number): void {
  ctx.beginPath();
  for (let i = 0; i < 6; i++) {
    const a = (Math.PI / 3) * i - Math.PI / 6;
    const hx = x + r * Math.cos(a), hy = y + r * Math.sin(a);
    if (i === 0) ctx.moveTo(hx, hy); else ctx.lineTo(hx, hy);
  }
  ctx.closePath();
}


export function FallbackWorldMap({ events }: { events: FireEvent[] }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const drawRef = useRef<() => void>(() => {});
  const hoverRef = useRef<FireEvent | null>(null);
  const [hover, setHover] = useState<{ x: number; y: number; ev: FireEvent } | null>(null);
  const view = useRef({ scale: 1, ox: 0, oy: 0, drag: null as null | { x: number; y: number } });
  const filters = useFireStore((s) => s.filters);
  const facilities = useFireStore((s) => s.facilities);
  const select = useFireStore((s) => s.select);
  const layers = useAnalyticsStore((s) => s.layers);
  const timeRange = useAnalyticsStore((s) => s.timeRange);
  const setMapApi = useMapDiagStore((s) => s.setMapApi);

  const filtered = useMemo(
    () => filterEvents(events, filters).filter((e) => e.detectedAt >= timeRange.start && e.detectedAt <= timeRange.end),
    [events, filters, timeRange],
  );
  const counts = useMemo(() => countryCounts(filtered), [filtered]);

  // Advanced-Mode parity on the canvas path: 1.5° bin aggregation
  // (deck.gl HexagonLayer equivalent, renderer-independent).
  const bins = useMemo(() => {
    const map = new Map<string, { x: number; y: number; n: number; frp: number; dom: string }>();
    for (const e of filtered) {
      const key = `${Math.round(e.lon / 1.5)}:${Math.round(e.lat / 1.5)}`;
      const b = map.get(key) ?? { x: 0, y: 0, n: 0, frp: 0, dom: e.classification.primary };
      b.x += e.lon; b.y += e.lat; b.n += 1; b.frp += e.frp;
      map.set(key, b);
    }
    return [...map.values()].filter((b) => b.n >= 3).map((b) => ({ ...b, x: b.x / b.n, y: b.y / b.n }));
  }, [filtered]);

  // Renderer-agnostic control API (same contract as the MapLibre path).
  useEffect(() => {
    setMapApi({
      zoomIn: () => { view.current.scale = Math.min(8, view.current.scale * 1.4); drawRef.current(); },
      zoomOut: () => { view.current.scale = Math.max(1, view.current.scale / 1.4); drawRef.current(); },
      reset: () => { view.current = { ...view.current, scale: 1, ox: 0, oy: 0 }; drawRef.current(); },
    });
    return () => setMapApi(null);
  }, [setMapApi]);
useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const draw = () => {
      const { scale, ox, oy } = view.current;
      const cw = canvas.clientWidth, ch = canvas.clientHeight;
      canvas.width = cw * devicePixelRatio; canvas.height = ch * devicePixelRatio;
      ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
      ctx.fillStyle = OCEAN; ctx.fillRect(0, 0, cw, ch);

      // Session-16 screen-lock: COVER scaling (world always fills the viewport)
      // plus pan clamping (world edges can never enter view).
      const base = coverScale(cw, ch) * scale;
      const cl = clampPan(ox, oy, base, cw, ch);
      const tx = (cw - W * base) / 2 + cl.ox, ty = (ch - H * base) / 2 + cl.oy;
      

      // NASA GIBS imagery — in SCREEN space (pre-world-transform) so Mercator slices
      // land exactly under the vector landmass. drawGibs computes its own screen X/Y.
      if (layers.imagery) {
        drawGibs(
          ctx,
          'truecolor',
          { base, tx, ty, worldW: WORLD_W, worldH: WORLD_H },
          cw, ch, 0.95,
          () => drawRef.current?.(),
        );
      }

      ctx.setTransform(devicePixelRatio * base, 0, 0, devicePixelRatio * base, devicePixelRatio * tx, devicePixelRatio * ty);
      PATHS.forEach((p, i) => {
        const n = counts.get(i) ?? 0;
        const flat = !layers.choropleth ? LAND : n >= 30 ? '#46301f' : n >= 10 ? '#33302a' : n > 0 ? '#232a31' : LAND;
        // Over imagery, countries become a translucent dark tint (not opaque silhouettes).
        ctx.fillStyle = layers.imagery ? 'rgba(13,17,23,0.22)' : flat;
        ctx.fill(p);
        ctx.strokeStyle = layers.imagery ? 'rgba(42,54,68,0.9)' : BORDER; ctx.lineWidth = 0.7 / base; ctx.stroke(p);
      });

      if (layers.graticule) {
        ctx.strokeStyle = '#2A3644'; ctx.lineWidth = 0.5 / base; ctx.globalAlpha = 0.5; ctx.stroke(GRAT); ctx.globalAlpha = 1;
      }

      if (layers.labels) {
        ctx.fillStyle = '#6b7684';
        ctx.font = `${11 / base}px monospace`;
        ctx.textAlign = 'center';
        for (const l of COUNTRY_LABELS) ctx.fillText(l.name.toUpperCase(), px(l.centroid[0]), py(l.centroid[1]));
      }

      // Advanced: hex density bins (canvas parity for deck.gl HexagonLayer)
      if (layers.hexagonDensity) {
        for (const b of bins) {
          const rgb = CLASS_RGB[b.dom] ?? [128, 128, 128];
          ctx.fillStyle = `rgba(${rgb[0]},${rgb[1]},${rgb[2]},0.22)`;
          ctx.strokeStyle = `rgba(${rgb[0]},${rgb[1]},${rgb[2]},0.6)`;
          ctx.lineWidth = 1 / base;
          hexPath(ctx, px(b.x), py(b.y), (6 + Math.min(b.n, 40) * 0.5) / base);
          ctx.fill(); ctx.stroke();
        }
      }

      // Advanced: spread forecast rings (model, not observation)
      if (layers.spreadRings) {
        for (const e of filtered) {
          if (e.risk.score < 55) continue;
          const rate = ({ wildfire: 0.55, agricultural: 0.35, industrial: 0.08, persistent: 0.05 } as Record<string, number>)[e.classification.primary] ?? 0.3;
          [6, 12, 24].forEach((h, i) => {
            const km = rate * h * (0.7 + Math.min(e.frp, 800) / 1600);
            const r = (km / 111) * (W / 360); // km → deg → world px
            ctx.strokeStyle = i === 2 ? 'rgba(255,68,68,0.55)' : 'rgba(255,107,53,0.45)';
            ctx.lineWidth = 1.2 / base;
            ctx.beginPath(); ctx.arc(px(e.lon), py(e.lat), r, 0, 7); ctx.stroke();
          });
        }
      }

      if (layers.facilities) {
        ctx.fillStyle = '#10161d'; ctx.strokeStyle = '#7d8da1'; ctx.lineWidth = 1 / base;
        for (const f of facilities) {
          const s = 3 / base;
          ctx.fillRect(px(f.lon) - s / 2, py(f.lat) - s / 2, s, s);
          ctx.strokeRect(px(f.lon) - s / 2, py(f.lat) - s / 2, s, s);
        }
      }
      if (layers.persistentRings) {
        // phase from performance.now() — animates via the interval loop, rAF-independent
        const phase = (performance.now() % 1600) / 1600;
        ctx.strokeStyle = CLASS_META.persistent.color; ctx.lineWidth = 1.4 / base;
        for (const e of filtered) {
          if (e.persistence.regime !== 'persistent') continue;
          ctx.globalAlpha = 0.7 * (1 - phase);
          ctx.beginPath(); ctx.arc(px(e.lon), py(e.lat), (4 + phase * 12) / base, 0, 7); ctx.stroke();
        }
        ctx.globalAlpha = 1;
      }
      for (const e of filtered) {
        ctx.fillStyle = CLASS_META[e.classification.primary].color;
        ctx.beginPath();
        ctx.arc(px(e.lon), py(e.lat), (3 + Math.min(e.frp, 900) / 160) / base, 0, 7);
        ctx.fill();
      }
      const h = hoverRef.current;
      if (h) {
        ctx.strokeStyle = '#E8EEF5'; ctx.lineWidth = 1.5 / base;
        ctx.beginPath(); ctx.arc(px(h.lon), py(h.lat), 10 / base, 0, 7); ctx.stroke();
      }
    };
    drawRef.current = draw;
    draw();

    const ro = new ResizeObserver(draw);
    ro.observe(canvas);
    const timer = window.setInterval(draw, TICK_MS);

    const onWheel = (ev: WheelEvent) => {
      ev.preventDefault();
      view.current.scale = Math.min(8, Math.max(1, view.current.scale * (ev.deltaY < 0 ? 1.15 : 0.87)));
      draw();
    };
    const onDown = (ev: MouseEvent) => { view.current.drag = { x: ev.clientX, y: ev.clientY }; };

    const toWorld = (cx: number, cy: number) => {
      const rect = canvas.getBoundingClientRect();
      const { scale, ox, oy } = view.current;
      const base = coverScale(rect.width, rect.height) * scale;
      const cl = clampPan(ox, oy, base, rect.width, rect.height);
      const tx = (rect.width - W * base) / 2 + cl.ox, ty = (rect.height - H * base) / 2 + cl.oy;
      return { wx: (cx - rect.left - tx) / base, wy: (cy - rect.top - ty) / base, base };
    };
    const pick = (cx: number, cy: number): FireEvent | null => {
      const { wx, wy, base } = toWorld(cx, cy);
      let best: FireEvent | null = null; let bestD = 12 / base;
      for (const e of filtered) {
        const d = Math.hypot(px(e.lon) - wx, py(e.lat) - wy);
        if (d < bestD) { bestD = d; best = e; }
      }
      return best;
    };

    const onMove = (ev: MouseEvent) => {
      if (view.current.drag) {
        view.current.ox += ev.clientX - view.current.drag.x;
        view.current.oy += ev.clientY - view.current.drag.y;
        view.current.drag = { x: ev.clientX, y: ev.clientY };
        draw();
        return;
      }
      const hit = pick(ev.clientX, ev.clientY);
      hoverRef.current = hit;
      const rect = canvas.getBoundingClientRect();
      setHover(hit ? { x: ev.clientX - rect.left, y: ev.clientY - rect.top, ev: hit } : null);
      canvas.style.cursor = hit ? 'pointer' : '';
      draw();
    };
    const onUp = (ev: MouseEvent) => {
      const wasDrag = view.current.drag && (Math.abs(ev.clientX - view.current.drag.x) > 3 || Math.abs(ev.clientY - view.current.drag.y) > 3);
      view.current.drag = null;
      if (wasDrag) return;
      const hit = pick(ev.clientX, ev.clientY);
      if (hit) select(hit.id);
    };
    canvas.addEventListener('wheel', onWheel, { passive: false });
    canvas.addEventListener('mousedown', onDown);
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => {
      ro.disconnect();
      window.clearInterval(timer);
      canvas.removeEventListener('wheel', onWheel);
      canvas.removeEventListener('mousedown', onDown);
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
  }, [filtered, counts, bins, layers, facilities, select]);

  return (
    <div className="absolute inset-0">
      <canvas ref={canvasRef} className="absolute inset-0 h-full w-full" aria-label="2D world fire map (canvas renderer)" />
      {hover && (
        <div className="map-pop pointer-events-none absolute z-20" style={{ left: hover.x + 12, top: hover.y + 8 }}>
          <b>{CLASS_META[hover.ev.classification.primary].label}</b> · risk {hover.ev.risk.score}
          <br />FRP {hover.ev.frp} MW · {hover.ev.persistence.regime}
        </div>
      )}
    </div>
  );
}
