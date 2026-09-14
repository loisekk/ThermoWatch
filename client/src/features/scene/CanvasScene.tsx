import { useEffect, useMemo, useRef } from 'react';
import { CLASS_META, SUBTYPE_LABEL } from '@/config/constants';
import type { Facility, FireEvent } from '@/types/domain';
import { capByFrp, clusterEllipse, hotspotColor, hotspotRadius, toEnu,
  type Detection } from '@/features/scene/sceneData';
import { enuUnits, ROAD_HALF_W, scatterInPolygon, type OsmBuildingKind, type SceneContext } from '@/features/scene/osmScene';
import { CARTO, LABEL_CAP, hexStr } from '@/features/scene/cartography';

const UNIT = 100; // 1 scene unit = 100 m
const HAZ_HEIGHT: Record<string, number> = { 'G-III': 6, 'G-II': 4, 'G-I': 2.5 };
const TICK_MS = 66; // ~15 fps via setInterval — deliberately NOT requestAnimationFrame

const CANVAS_KIND: Record<OsmBuildingKind, string> = {
  industrial: hexStr(CARTO.building.industrial),
  commercial: hexStr(CARTO.building.commercial),
  residential: hexStr(CARTO.building.residential),
  generic: hexStr(CARTO.building.generic),
};

interface SceneState {
  rings: { hours: number; r: number; i: number }[];
  fx: number;
  fz: number;
  fh: number;
  fac: Facility | null;
}

interface SceneProps {
  ev: FireEvent;
  facilities: Facility[];
  /** Per-detection cloud (capped); null/empty = legacy centroid mode (honest chip). */
  detections?: Detection[] | null;
  /** Live OSM context — simplified parity (footprints, trees, roads, patches). */
  osm?: SceneContext | null;
}

/** Isometric Canvas2D incident scene — renderer-independent (no WebGL, no rAF, no CDN).
 *  Axonometric projection, 1 unit = 100 m; same geometry as the Three.js scene.
 *  Session 23 parity: per-detection hotspot dots + 2σ ellipse (plume/replay off). */
export function CanvasScene({ ev, facilities, detections, osm: osmCtx }: SceneProps) {
  const wrap = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const view = useRef({ az: Math.PI / 4, zoom: 1, drag: null as null | { x: number } });

  const fac = useMemo(() => facilities.find((f) => f.id === ev.nearestFacilityId) ?? null, [facilities, ev.nearestFacilityId]);
  const scene = useMemo<SceneState>(() => {
    const rate =
      ({ wildfire: 0.55, agricultural: 0.35, industrial: 0.08, persistent: 0.05 } as Record<string, number>)[ev.classification.primary] *
      (0.7 + Math.min(ev.frp, 800) / 1600);
    const rings = [6, 12, 24].map((h, i) => ({ hours: h, r: Math.max(1.2, (rate * h * 1000) / UNIT), i }));
    let fx = 0, fz = 0, fh = 0;
    if (fac) {
      fx = ((fac.lon - ev.lon) * 111_320 * Math.cos((ev.lat * Math.PI) / 180)) / UNIT;
      fz = ((fac.lat - ev.lat) * 110_540) / UNIT;
      fh = HAZ_HEIGHT[fac.hazard] ?? 3;
    }
    return { rings, fx, fz, fh, fac };
  }, [ev, fac]);

  // Per-detection hotspot cloud in scene coords (east = +x, north = +y units).
  const dets = useMemo(() => {
    if (!detections?.length) return null;
    const capped = capByFrp(detections);
    const enu = capped.map((d) => toEnu(ev.lat, ev.lon, d.lat, d.lon));
    const pts = capped.map((d, i) => ({
      x: enu[i].e / UNIT, y: enu[i].n / UNIT,
      r: hotspotRadius(d.frp_mw), color: hotspotColor(d.brightness_k),
    }));
    const ell = clusterEllipse(enu);
    return { pts, ell };
  }, [detections, ev.lat, ev.lon]);

  // OSM parity shapes (real footprints/trees/roads/patches — T9 carto grade).
  const osmShapes = useMemo(() => {
    if (osmCtx?.source !== 'osm-overpass') return null;
    const O = { lat: ev.lat, lon: ev.lon };
    const xy = (la: number, lo: number) => {
      const u = enuUnits(O, la, lo);
      return { x: u.x, y: -u.z };
    };
    // labels: named water/wood/landuse centroids + road names, priority + cap 12
    const labels: { text: string; x: number; y: number; road: boolean }[] = [];
    const pushLabel = (name: string | null | undefined, ring: [number, number][], road: boolean): void => {
      if (!name) return;
      const pts = ring.map(([la, lo]) => xy(la, lo));
      const c = road ? pts[Math.floor(pts.length / 2)]
        : { x: pts.reduce((a, p) => a + p.x, 0) / pts.length,
            y: pts.reduce((a, p) => a + p.y, 0) / pts.length };
      labels.push({ text: name, x: c.x, y: c.y, road });
    };
    for (const w of osmCtx.water) pushLabel(w.name, w.outline, false);
    for (const w of osmCtx.wood) pushLabel(w.name, w.outline, false);
    for (const w of osmCtx.landuse) pushLabel(w.name, w.outline, false);
    for (const r of osmCtx.roads) pushLabel(r.name, r.points, true);
    labels.sort((a, b) => (a.road === b.road ? a.text.length - b.text.length : a.road ? 1 : -1));
    // canopy: deterministic scatter inside REAL wood polygons (illustrative density)
    const canopy: { x: number; y: number }[] = [];
    for (const w of osmCtx.wood) {
      const ring = w.outline.map(([la, lo]) => {
        const u = enuUnits(O, la, lo);
        return { x: u.x, z: u.z };
      });
      for (const p of scatterInPolygon(ring, 220, 11 + canopy.length)) canopy.push({ x: p.x, y: -p.z });
    }
    return {
      water: osmCtx.water.map((w) => w.outline.map(([la, lo]) => xy(la, lo))),
      wood: osmCtx.wood.map((w) => w.outline.map(([la, lo]) => xy(la, lo))),
      landuse: osmCtx.landuse.map((w) => ({
        pts: w.outline.map(([la, lo]) => xy(la, lo)),
        color: hexStr((CARTO.landuse as Record<string, number>)[w.kind] ?? 0x363b42),
      })),
      roads: osmCtx.roads.map((r) => ({
        pts: r.points.map(([la, lo]) => xy(la, lo)),
        halfW: (ROAD_HALF_W[r.cls] ?? 2) / UNIT,
        res: r.cls === 'residential' || r.cls === 'service' || r.cls === 'unclassified',
      })),
      buildings: osmCtx.buildings.slice(0, 80).map((b) => ({
        pts: b.outline.map(([la, lo]) => xy(la, lo)),
        hU: Math.max(0.15, b.height_m / UNIT),
        color: CANVAS_KIND[b.kind],
      })),
      trees: osmCtx.trees.slice(0, 300).map((t) => xy(t.lat, t.lon)),
      canopy,
      labels: labels.slice(0, LABEL_CAP),
    };
  }, [osmCtx, ev.lat, ev.lon]);

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
      ctx.fillStyle = '#0b0f14';
      ctx.fillRect(0, 0, cw, ch);

      const { az, zoom } = view.current;
      const s = (Math.min(cw, ch) / 60) * zoom;
      const cx = cw / 2, cy = ch * 0.62;
      const ca = Math.cos(az), sa = Math.sin(az);
      const proj = (x: number, y: number, z: number) => ({
        sx: cx + (x * ca - y * sa) * s,
        sy: cy + (x * sa + y * ca) * s * 0.45 - z * s * 0.9,
        depth: x * sa + y * ca,
      });

      // ground grid
      ctx.strokeStyle = 'rgba(42,54,68,0.5)';
      ctx.lineWidth = 0.6;
      for (let g = -24; g <= 24; g += 3) {
        let a = proj(g, -24, 0), b = proj(g, 24, 0);
        ctx.beginPath(); ctx.moveTo(a.sx, a.sy); ctx.lineTo(b.sx, b.sy); ctx.stroke();
        a = proj(-24, g, 0); b = proj(24, g, 0);
        ctx.beginPath(); ctx.moveTo(a.sx, a.sy); ctx.lineTo(b.sx, b.sy); ctx.stroke();
      }

      // OSM surroundings — T9 cartographic parity (cased roads, outlines, canopy, labels)
      if (osmShapes) {
        const fillRing = (pts: { x: number; y: number }[], z: number, color: string, alpha = 1) => {
          if (pts.length < 3) return;
          ctx.beginPath();
          pts.forEach((p, i) => {
            const q = proj(p.x, p.y, z);
            if (i === 0) ctx.moveTo(q.sx, q.sy); else ctx.lineTo(q.sx, q.sy);
          });
          ctx.closePath();
          if (alpha < 1) ctx.globalAlpha = alpha;
          ctx.fillStyle = color; ctx.fill();
          if (alpha < 1) ctx.globalAlpha = 1;
        };
        for (const lu of osmShapes.landuse) fillRing(lu.pts, 0.004, lu.color);
        for (const w of osmShapes.water) {
          fillRing(w, 0.02, hexStr(CARTO.water));
          // shoreline (1 px Google-Maps cue)
          ctx.beginPath();
          w.forEach((p, i) => {
            const q = proj(p.x, p.y, 0.02);
            if (i === 0) ctx.moveTo(q.sx, q.sy); else ctx.lineTo(q.sx, q.sy);
          });
          ctx.closePath();
          ctx.strokeStyle = hexStr(CARTO.waterShore);
          ctx.lineWidth = 1;
          ctx.stroke();
        }
        for (const w of osmShapes.wood) fillRing(w, 0.015, hexStr(CARTO.wood));
        // cased roads: dark casing pass (full width) then lighter fill (×0.62)
        ctx.lineCap = 'round';
        for (const r of osmShapes.roads) {
          ctx.beginPath();
          r.pts.forEach((p, i) => {
            const q = proj(p.x, p.y, 0.01);
            if (i === 0) ctx.moveTo(q.sx, q.sy); else ctx.lineTo(q.sx, q.sy);
          });
          ctx.strokeStyle = hexStr(CARTO.roadCasing);
          ctx.lineWidth = Math.max(1.6, (r.halfW * 2) * s * 0.9);
          ctx.stroke();
        }
        for (const r of osmShapes.roads) {
          ctx.beginPath();
          r.pts.forEach((p, i) => {
            const q = proj(p.x, p.y, 0.012);
            if (i === 0) ctx.moveTo(q.sx, q.sy); else ctx.lineTo(q.sx, q.sy);
          });
          ctx.strokeStyle = r.res ? hexStr(CARTO.roadFillRes) : hexStr(CARTO.roadFill);
          ctx.lineWidth = Math.max(1, (r.halfW * 2 * 0.62) * s * 0.9);
          ctx.stroke();
        }
        for (const bld of osmShapes.buildings) {
          fillRing(bld.pts, 0.005, hexStr(CARTO.ground), 0.85);   // ground footprint shadow
          fillRing(bld.pts, bld.hU, bld.color);                   // roof face
          ctx.beginPath();
          bld.pts.forEach((p, i) => {
            const q = proj(p.x, p.y, bld.hU);
            if (i === 0) ctx.moveTo(q.sx, q.sy); else ctx.lineTo(q.sx, q.sy);
          });
          ctx.closePath();
          ctx.strokeStyle = hexStr(CARTO.buildingOutline);
          ctx.globalAlpha = 0.55; ctx.lineWidth = 0.8; ctx.stroke(); ctx.globalAlpha = 1;
        }
        // canopy inside wood polys — ILLUSTRATIVE density (legend discloses it)
        ctx.fillStyle = hexStr(CARTO.canopy);
        for (const c of osmShapes.canopy) {
          const q = proj(c.x, c.y, 0.03);
          ctx.beginPath(); ctx.arc(q.sx, q.sy, Math.max(1, 0.028 * s), 0, 7); ctx.fill();
        }
        ctx.fillStyle = '#2c5130';
        for (const t of osmShapes.trees) {
          const q = proj(t.x, t.y, 0.03);
          ctx.beginPath(); ctx.arc(q.sx, q.sy, Math.max(1.2, 0.035 * s), 0, 7); ctx.fill();
        }
        // halo labels (dark stroke + light fill), capped
        ctx.font = '10px "IBM Plex Mono", monospace';
        ctx.textAlign = 'center';
        for (const l of osmShapes.labels) {
          const q = proj(l.x, l.y, 0.05);
          ctx.strokeStyle = CARTO.label.halo;
          ctx.lineWidth = 3;
          ctx.strokeText(l.text.slice(0, 24), q.sx, q.sy);
          ctx.fillStyle = l.road ? CARTO.label.road : CARTO.label.fill;
          ctx.fillText(l.text.slice(0, 24), q.sx, q.sy);
        }
        ctx.textAlign = 'left';
      }

      // per-detection hotspots — Session 23 canvas parity (dots + 2σ ellipse)
      if (dets) {
        if (dets.ell) {
          ctx.beginPath();
          for (let i = 0; i <= 48; i++) {
            const t = (i / 48) * Math.PI * 2;
            const ex = (dets.ell.a * Math.cos(t)) / UNIT;
            const ey = (dets.ell.b * Math.sin(t)) / UNIT;
            const rx = ex * Math.cos(dets.ell.rot) - ey * Math.sin(dets.ell.rot);
            const ry = ex * Math.sin(dets.ell.rot) + ey * Math.cos(dets.ell.rot);
            const p = proj(dets.ell.ce / UNIT + rx, dets.ell.cn / UNIT + ry, 0);
            if (i === 0) ctx.moveTo(p.sx, p.sy); else ctx.lineTo(p.sx, p.sy);
          }
          ctx.closePath();
          ctx.strokeStyle = 'rgba(255,107,53,0.8)';
          ctx.lineWidth = 1.2;
          ctx.stroke();
        }
        for (const h of dets.pts) {
          const p = proj(h.x, h.y, 0);
          ctx.fillStyle = h.color;
          ctx.beginPath(); ctx.arc(p.sx, p.sy, Math.max(1.5, h.r * 1.6), 0, 7); ctx.fill();
        }
      }

      // spread rings
      for (const ring of scene.rings) {
        ctx.beginPath();
        for (let i = 0; i <= 48; i++) {
          const t = (i / 48) * Math.PI * 2;
          const p = proj(ring.r * Math.cos(t), ring.r * Math.sin(t), 0);
          if (i === 0) ctx.moveTo(p.sx, p.sy); else ctx.lineTo(p.sx, p.sy);
        }
        ctx.closePath();
        ctx.strokeStyle = ring.i === 2 ? 'rgba(255,68,68,0.75)' : 'rgba(255,107,53,0.65)';
        ctx.lineWidth = 1.4;
        ctx.stroke();
        ctx.fillStyle = ring.i === 2 ? 'rgba(255,68,68,0.05)' : 'rgba(255,107,53,0.04)';
        ctx.fill();
        const lp = proj(ring.r, 0, 0);
        ctx.fillStyle = '#8ca0b3';
        ctx.font = '10px "IBM Plex Mono", monospace';
        ctx.fillText(`${ring.hours}h`, lp.sx + 4, lp.sy - 2);
      }

      // facility massing box (painter's depth order)
      if (scene.fac) {
        const b = scene;
        const w = 1.6;
        const c: [number, number, number][] = [
          [b.fx - w, b.fz - w, 0], [b.fx + w, b.fz - w, 0],
          [b.fx + w, b.fz + w, 0], [b.fx - w, b.fz + w, 0],
        ];
        const bot = c.map(([x, y]) => proj(x, y, 0));
        const top = c.map(([x, y]) => proj(x, y, b.fh));
        const faces = [0, 1, 2, 3].map((i) => {
          const j = (i + 1) % 4;
          return {
            pts: [bot[i], bot[j], top[j], top[i]],
            d: (c[i][0] + c[j][0]) * sa + (c[i][1] + c[j][1]) * ca,
          };
        });
        faces.sort((p, q) => p.d - q.d);
        for (const f of faces.slice(0, 2)) {
          ctx.beginPath();
          f.pts.forEach((p, i) => (i === 0 ? ctx.moveTo(p.sx, p.sy) : ctx.lineTo(p.sx, p.sy)));
          ctx.closePath();
          ctx.fillStyle = '#2a333d'; ctx.fill();
          ctx.strokeStyle = 'rgba(232,238,245,0.35)'; ctx.lineWidth = 0.8; ctx.stroke();
        }
        ctx.beginPath();
        top.forEach((p, i) => (i === 0 ? ctx.moveTo(p.sx, p.sy) : ctx.lineTo(p.sx, p.sy)));
        ctx.closePath();
        ctx.fillStyle = '#7d8da1'; ctx.fill();
        ctx.strokeStyle = 'rgba(232,238,245,0.5)'; ctx.stroke();
        const tp = proj(b.fx, b.fz, b.fh + 1);
        ctx.fillStyle = '#8ca0b3';
        ctx.font = '10px "IBM Plex Mono", monospace';
        ctx.textAlign = 'center';
        ctx.fillText(b.fac!.name.toUpperCase().slice(0, 26), tp.sx, tp.sy);
        ctx.fillStyle = '#5b6b7d';
        ctx.fillText(`${SUBTYPE_LABEL[b.fac!.subtype]} · ${b.fac!.hazard}`, tp.sx, tp.sy + 12);
        ctx.textAlign = 'left';
      }

      // pulsing fire core
      const pulse = 1 + 0.18 * Math.sin(performance.now() / 250);
      const fp = proj(0, 0, 0.8);
      const color = CLASS_META[ev.classification.primary].color;
      const glow = ctx.createRadialGradient(fp.sx, fp.sy, 0, fp.sx, fp.sy, 26 * pulse);
      glow.addColorStop(0, `${color}cc`);
      glow.addColorStop(1, `${color}00`);
      ctx.fillStyle = glow;
      ctx.beginPath(); ctx.arc(fp.sx, fp.sy, 26 * pulse, 0, 7); ctx.fill();
      ctx.fillStyle = color;
      ctx.beginPath(); ctx.arc(fp.sx, fp.sy, 6 * pulse, 0, 7); ctx.fill();
      ctx.strokeStyle = '#e8eef5';
      ctx.lineWidth = 1;
      ctx.beginPath(); ctx.arc(fp.sx, fp.sy, 6 * pulse, 0, 7); ctx.stroke();
    };

    draw();
    const ro = new ResizeObserver(draw);
    ro.observe(wrapEl);
    const timer = window.setInterval(draw, TICK_MS);

    const onDown = (e: PointerEvent) => { view.current.drag = { x: e.clientX }; };
    const onMove = (e: PointerEvent) => {
      if (!view.current.drag) return;
      view.current.az += (e.clientX - view.current.drag.x) * 0.008;
      view.current.drag = { x: e.clientX };
    };
    const onUp = () => { view.current.drag = null; };
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      view.current.zoom = Math.min(4, Math.max(0.5, view.current.zoom * (e.deltaY > 0 ? 0.9 : 1.1)));
    };
    wrapEl.addEventListener('pointerdown', onDown);
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    wrapEl.addEventListener('wheel', onWheel, { passive: false });

    return () => {
      ro.disconnect();
      window.clearInterval(timer);
      wrapEl.removeEventListener('pointerdown', onDown);
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      wrapEl.removeEventListener('wheel', onWheel);
    };
  }, [scene, ev, dets, osmShapes]);

  return (
    <div ref={wrap} className="absolute inset-0 cursor-grab active:cursor-grabbing">
      <canvas ref={canvasRef} className="absolute inset-0 h-full w-full" aria-label="3D incident scene (canvas renderer)" />
    </div>
  );
}
