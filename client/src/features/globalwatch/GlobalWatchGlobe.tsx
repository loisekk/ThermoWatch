/**
 * Global Watch hero — the incident feed as a live orthographic globe.
 *
 * Renderer-resilience doctrine: Canvas2D on setInterval (no rAF, no WebGL), so
 * the deck paints on hosts where GL frames never present. Blips take their
 * color from the derived risk level; high-risk events carry a label chip and
 * pulse rings; drag rotates, click selects, and selecting anywhere (rail or
 * globe) flies the globe to that incident.
 *
 * Honesty: risk colors are theme tokens (magma / amber / ok), so an
 * `insufficient_evidence` incident renders amber — uncertainty is never drawn
 * as safety. Under prefers-reduced-motion the clock freezes: no auto-rotate,
 * no pulses (CSS cannot stop a setInterval loop).
 */
import { useEffect, useRef, useState } from 'react';
import worldRaw from '@/assets/world-110m.json';
import { BORDER, LAND, OCEAN } from '@/config/worldStyle';
import { prefersReducedMotion } from '@/lib/runtime/motion';
import type { IncidentSummary } from '@/services/api/v2Types';
import {
  centerRotation,
  isVisible,
  latLonToVec3,
  rotateVec,
  shortestAngle,
  subsolarPoint,
  toScreen,
  type Vec3,
} from './globeMath';
import { normalizeWorld } from './worldFeatures';
import { RISK_META, deriveRiskLevel, incidentCode, topClass } from './incidentDisplay';

const TICK_MS = 33; // setInterval-driven: immune to a dead rAF
const HIT_RADIUS_SQ = 14 * 14;
const COAST = BORDER;
const GRATICULE = 'rgba(125,141,161,0.10)';
const GLOW = 'rgba(125,141,161,0.14)';
const LIMB = 'rgba(125,141,161,0.40)';
/** Day-side tint is neutral warm white on purpose: amber means "uncertain" here. */
const SUNLIGHT = 'rgba(232,238,245,0.07)';

/** Static geometry → unit vectors ONCE per session, so per-frame work is a
 *  4-multiply rotation plus a scale — no trig in the hot loop. */
type Ring = Vec3[];
const SHAPES: Ring[][] = normalizeWorld(worldRaw).map((shape) =>
  shape.rings.map((ring) => ring.map(([lon, lat]) => latLonToVec3(lat, lon))),
);

function graticuleVectors(): Ring[] {
  const rings: Ring[] = [];
  for (let lon = -180; lon < 180; lon += 30) {
    const ring: Ring = [];
    for (let lat = -90; lat <= 90; lat += 3) ring.push(latLonToVec3(lat, lon));
    rings.push(ring);
  }
  for (let lat = -60; lat <= 60; lat += 30) {
    const ring: Ring = [];
    for (let lon = -180; lon <= 180; lon += 3) ring.push(latLonToVec3(lat, lon));
    rings.push(ring);
  }
  return rings;
}
const GRATICULE_RINGS = graticuleVectors();

export interface GlobeBlip {
  x: number;
  y: number;
  incident: IncidentSummary;
}

interface Props {
  incidents: IncidentSummary[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export function GlobalWatchGlobe({ incidents, selectedId, onSelect }: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [hovered, setHovered] = useState<IncidentSummary | null>(null);

  const view = useRef({
    lon: -1.2,
    lat: 0.35,
    targetLon: null as number | null,
    targetLat: null as number | null,
  });
  const drag = useRef({ on: false, x: 0, y: 0, moved: false });
  const blips = useRef<GlobeBlip[]>([]);
  // Mirrors for the long-lived draw loop (one interval for the component's life).
  const feed = useRef<{
    incidents: IncidentSummary[];
    selectedId: string | null;
    hovered: IncidentSummary | null;
  }>({ incidents, selectedId, hovered });

  useEffect(() => {
    feed.current = { incidents, selectedId, hovered };
  }, [incidents, selectedId, hovered]);

  // --- fly-to: selecting an incident rotates the globe until it faces us ---
  useEffect(() => {
    if (!selectedId) {
      view.current.targetLon = null;
      view.current.targetLat = null;
      return;
    }
    const inc = incidents.find((i) => i.id === selectedId);
    if (!inc) return;
    const t = centerRotation(inc.centroid_latitude, inc.centroid_longitude);
    view.current.targetLon = t.lonRot;
    view.current.targetLat = t.latRot;
  }, [selectedId, incidents]);

  // --- pointer input: drag to rotate, click a blip to open its dossier ---
  useEffect(() => {
    const el = canvasRef.current;
    if (!el) return;

    const pick = (mx: number, my: number): GlobeBlip | null => {
      let best: GlobeBlip | null = null;
      let bd = HIT_RADIUS_SQ;
      for (const b of blips.current) {
        const d = (b.x - mx) ** 2 + (b.y - my) ** 2;
        if (d < bd) {
          bd = d;
          best = b;
        }
      }
      return best;
    };
    const local = (e: PointerEvent) => {
      const rect = el.getBoundingClientRect();
      return { mx: e.clientX - rect.left, my: e.clientY - rect.top };
    };

    const onMove = (e: PointerEvent) => {
      if (drag.current.on) return;
      const { mx, my } = local(e);
      const hit = pick(mx, my);
      setHovered(hit?.incident ?? null);
      el.style.cursor = hit ? 'pointer' : 'grab';
    };
    const onDown = (e: PointerEvent) => {
      drag.current = { on: true, x: e.clientX, y: e.clientY, moved: false };
      el.style.cursor = 'grabbing';
    };
    const onDrag = (e: PointerEvent) => {
      if (!drag.current.on) return;
      const dx = e.clientX - drag.current.x;
      const dy = e.clientY - drag.current.y;
      if (Math.abs(dx) + Math.abs(dy) > 3) drag.current.moved = true;
      view.current.lon += dx * 0.005;
      view.current.lat = Math.max(-1.1, Math.min(1.1, view.current.lat + dy * 0.004));
      view.current.targetLon = null; // manual override beats fly-to
      view.current.targetLat = null;
      drag.current.x = e.clientX;
      drag.current.y = e.clientY;
    };
    const onUp = (e: PointerEvent) => {
      const wasDrag = drag.current.moved;
      drag.current.on = false;
      el.style.cursor = 'grab';
      if (wasDrag) return;
      const { mx, my } = local(e);
      const hit = pick(mx, my);
      if (hit) onSelect(hit.incident.id);
    };
    const onLeave = () => setHovered(null);

    el.addEventListener('pointermove', onMove);
    el.addEventListener('pointerdown', onDown);
    el.addEventListener('pointerleave', onLeave);
    window.addEventListener('pointermove', onDrag);
    window.addEventListener('pointerup', onUp);
    return () => {
      el.removeEventListener('pointermove', onMove);
      el.removeEventListener('pointerdown', onDown);
      el.removeEventListener('pointerleave', onLeave);
      window.removeEventListener('pointermove', onDrag);
      window.removeEventListener('pointerup', onUp);
    };
  }, [onSelect]);

  // --- the draw loop: one interval for the component's life ---
  useEffect(() => {
    const canvas = canvasRef.current;
    const wrap = wrapRef.current;
    if (!canvas || !wrap) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const reduce = prefersReducedMotion();
    let t0 = performance.now();

    const chipPath = (x: number, y: number, w: number, h: number, r: number) => {
      ctx.beginPath();
      if (typeof ctx.roundRect === 'function') ctx.roundRect(x, y, w, h, r);
      else ctx.rect(x, y, w, h);
    };

    /** Project a ring, stroke the visible stretch; fill only when it faces us. */
    const drawRing = (ring: Ring, lonRot: number, latRot: number, cx: number, cy: number, R: number) => {
      const rotated: Vec3[] = [];
      let visible = 0;
      for (const p of ring) {
        const r = rotateVec(p, lonRot, latRot);
        rotated.push(r);
        if (isVisible(r)) visible += 1;
      }
      const ratio = visible / Math.max(ring.length, 1);
      if (ratio < 0.15) return;
      ctx.beginPath();
      let started = false;
      for (const r of rotated) {
        if (!isVisible(r)) {
          started = false;
          continue;
        }
        const s = toScreen(r, cx, cy, R);
        if (!started) {
          ctx.moveTo(s.x, s.y);
          started = true;
        } else {
          ctx.lineTo(s.x, s.y);
        }
      }
      if (ratio > 0.85) {
        ctx.fillStyle = LAND;
        ctx.fill();
      }
      ctx.strokeStyle = COAST;
      ctx.lineWidth = 0.7;
      ctx.stroke();
    };

    const paint = (now: number) => {
      const dt = Math.min(now - t0, 100);
      t0 = now;
      const dpr = window.devicePixelRatio || 1;
      const w = wrap.clientWidth;
      const h = wrap.clientHeight;
      if (w === 0 || h === 0) return;
      if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
        canvas.width = Math.round(w * dpr);
        canvas.height = Math.round(h * dpr);
        canvas.style.width = `${w}px`;
        canvas.style.height = `${h}px`;
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);

      const cx = w / 2;
      const cy = h / 2;
      const R = Math.min(w, h) * 0.4;
      const v = view.current;
      const { incidents: live, selectedId: sel, hovered: hov } = feed.current;

      // rotation: fly-to easing, else a slow idle drift (frozen under reduced motion)
      if (v.targetLon != null && v.targetLat != null) {
        v.lon += shortestAngle(v.lon, v.targetLon) * 0.06;
        v.lat += (v.targetLat - v.lat) * 0.06;
        if (Math.abs(shortestAngle(v.lon, v.targetLon)) < 0.002 && Math.abs(v.targetLat - v.lat) < 0.002) {
          v.targetLon = null;
          v.targetLat = null;
        }
      } else if (!reduce && !drag.current.on && !hov && !sel) {
        // Idle drift ≈ one full turn per 3.5 min (the CanvasGlobe cadence), and
        // only when nothing is selected — a selected incident stays centered
        // while its dossier is open.
        v.lon += 0.00003 * dt;
      }

      // atmosphere + ocean disc
      const glow = ctx.createRadialGradient(cx, cy, R * 0.9, cx, cy, R * 1.18);
      glow.addColorStop(0, GLOW);
      glow.addColorStop(1, 'rgba(125,141,161,0)');
      ctx.fillStyle = glow;
      ctx.beginPath();
      ctx.arc(cx, cy, R * 1.18, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = OCEAN;
      ctx.beginPath();
      ctx.arc(cx, cy, R, 0, Math.PI * 2);
      ctx.fill();

      // sphere surface: landmass, graticule, day-side tint
      ctx.save();
      ctx.beginPath();
      ctx.arc(cx, cy, R, 0, Math.PI * 2);
      ctx.clip();
      for (const shape of SHAPES) for (const ring of shape) drawRing(ring, v.lon, v.lat, cx, cy, R);
      ctx.strokeStyle = GRATICULE;
      ctx.lineWidth = 0.5;
      for (const ring of GRATICULE_RINGS) {
        ctx.beginPath();
        let started = false;
        for (const p of ring) {
          const r = rotateVec(p, v.lon, v.lat);
          if (!isVisible(r)) {
            started = false;
            continue;
          }
          const s = toScreen(r, cx, cy, R);
          if (!started) {
            ctx.moveTo(s.x, s.y);
            started = true;
          } else {
            ctx.lineTo(s.x, s.y);
          }
        }
        ctx.stroke();
      }
      const sun = subsolarPoint(new Date());
      const sv = rotateVec(latLonToVec3(sun.lat, sun.lon), v.lon, v.lat);
      const ss = toScreen(sv, cx, cy, R);
      const sunGrad = ctx.createRadialGradient(ss.x, ss.y, 0, ss.x, ss.y, R * 1.3);
      sunGrad.addColorStop(0, SUNLIGHT);
      sunGrad.addColorStop(1, 'rgba(232,238,245,0)');
      ctx.fillStyle = sunGrad;
      ctx.beginPath();
      ctx.arc(cx, cy, R, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();

      // limb ring
      ctx.strokeStyle = LIMB;
      ctx.lineWidth = 1.2;
      ctx.beginPath();
      ctx.arc(cx, cy, R, 0, Math.PI * 2);
      ctx.stroke();

      // incident blips — every active incident on the visible hemisphere
      blips.current = [];
      const chipRects: { x: number; y: number; w: number; h: number }[] = [];
      ctx.font = '9px ui-monospace, "IBM Plex Mono", monospace';
      live.forEach((inc, idx) => {
        const p = rotateVec(latLonToVec3(inc.centroid_latitude, inc.centroid_longitude), v.lon, v.lat);
        if (!isVisible(p)) return;
        const s = toScreen(p, cx, cy, R);
        blips.current.push({ x: s.x, y: s.y, incident: inc });

        const risk = deriveRiskLevel(inc);
        const meta = RISK_META[risk];
        const isSel = inc.id === sel;
        const isHov = hov?.id === inc.id;
        const size = isSel ? 5 : isHov ? 4.5 : 3;

        // static halo + pulse rings for high risk / selection
        ctx.strokeStyle = meta.ring;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.arc(s.x, s.y, size + 3, 0, Math.PI * 2);
        ctx.stroke();
        if (!reduce && (risk === 'high' || isSel)) {
          const phase = ((now / 1000 + idx * 0.4) % 1.8) / 1.8;
          ctx.strokeStyle = meta.color;
          ctx.globalAlpha = (1 - phase) * 0.7;
          ctx.beginPath();
          ctx.arc(s.x, s.y, size + phase * 16, 0, Math.PI * 2);
          ctx.stroke();
          ctx.globalAlpha = 1;
        }

        ctx.shadowColor = meta.color;
        ctx.shadowBlur = isSel || isHov ? 12 : 6;
        ctx.fillStyle = meta.color;
        ctx.beginPath();
        ctx.arc(s.x, s.y, size, 0, Math.PI * 2);
        ctx.fill();
        ctx.shadowBlur = 0;
        if (isSel) {
          ctx.strokeStyle = '#e8eef5'; // --color-ink
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.arc(s.x, s.y, size + 5, 0, Math.PI * 2);
          ctx.stroke();
        }

        // label chips: HIGH always (decluttered), others on hover/selection
        const forced = isHov || isSel;
        if (risk !== 'high' && !forced) return;
        const label = `${topClass(inc).replace(/_/g, ' ').toUpperCase()} · ${meta.label}`;
        const tw = ctx.measureText(label).width;
        const lx = s.x + 10;
        const ly = s.y - 16;
        const box = { x: lx, y: ly, w: tw + 12, h: 16 };
        const collides = chipRects.some(
          (r) => box.x < r.x + r.w && box.x + box.w > r.x && box.y < r.y + r.h && box.y + box.h > r.y,
        );
        if (collides && !forced) return; // keep the deck readable — no stacked chips
        chipRects.push(box);

        ctx.strokeStyle = 'rgba(125,141,161,0.4)';
        ctx.lineWidth = 0.6;
        ctx.beginPath();
        ctx.moveTo(s.x + 3, s.y - 3);
        ctx.lineTo(lx - 2, ly + 8);
        ctx.stroke();
        chipPath(lx, ly, box.w, box.h, 3);
        ctx.fillStyle = 'rgba(7,9,13,0.85)'; // --color-void
        ctx.fill();
        ctx.strokeStyle = meta.color;
        ctx.lineWidth = 0.8;
        ctx.stroke();
        ctx.fillStyle = meta.color;
        ctx.fillText(label, lx + 6, ly + 11);
      });
    };

    paint(performance.now());
    const id = window.setInterval(() => paint(performance.now()), reduce ? 500 : TICK_MS);
    return () => window.clearInterval(id);
  }, []);

  const hoverMeta = hovered ? RISK_META[deriveRiskLevel(hovered)] : null;

  return (
    <div ref={wrapRef} className="relative h-full w-full overflow-hidden">
      <canvas
        ref={canvasRef}
        className="absolute inset-0 cursor-grab"
        role="img"
        aria-label={`Global incident globe — ${incidents.length} tracked incidents colored by derived risk: red high, amber medium (includes insufficient evidence), green low`}
      />
      <div className="mono pointer-events-none absolute left-3 top-3 text-[10px] uppercase tracking-widest text-dim">
        Global Watch · {incidents.length} tracked
      </div>
      <div className="mono pointer-events-none absolute bottom-3 right-3 text-[10px] text-dim">
        drag to rotate · click a blip to open dossier
      </div>
      {hovered && hoverMeta && (
        <div className="mono pointer-events-none absolute bottom-3 left-3 rounded-sm border border-edge2 bg-panel2 px-2 py-1 text-[10px] text-ink">
          {incidentCode(hovered.id)} · {topClass(hovered).replace(/_/g, ' ')} · {hoverMeta.label}
        </div>
      )}
    </div>
  );
}
