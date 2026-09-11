import { useEffect, useMemo, useRef } from 'react';
import { CLASS_META, SUBTYPE_LABEL } from '@/config/constants';
import type { Facility, FireEvent } from '@/types/domain';

const UNIT = 100; // 1 scene unit = 100 m
const HAZ_HEIGHT: Record<string, number> = { 'G-III': 6, 'G-II': 4, 'G-I': 2.5 };
const TICK_MS = 66; // ~15 fps via setInterval — deliberately NOT requestAnimationFrame

interface SceneState {
  rings: { hours: number; r: number; i: number }[];
  fx: number;
  fz: number;
  fh: number;
  fac: Facility | null;
}

/** Isometric Canvas2D incident scene — renderer-independent (no WebGL, no rAF, no CDN).
 *  Axonometric projection, 1 unit = 100 m; same geometry as the Three.js scene. */
export function CanvasScene({ ev, facilities }: { ev: FireEvent; facilities: Facility[] }) {
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
  }, [scene, ev]);

  return (
    <div ref={wrap} className="absolute inset-0 cursor-grab active:cursor-grabbing">
      <canvas ref={canvasRef} className="absolute inset-0 h-full w-full" aria-label="3D incident scene (canvas renderer)" />
    </div>
  );
}
