/**
 * Spatial Scope — detections as blips on a range-ring radar around the
 * incident centroid, with a rotating sweep and a reticle on the newest
 * detection that blinks red when the assessment flags a NEW ZONE. Older
 * blips dim (the API returns observations oldest-first). Range labels keep
 * the numbers on the glass (WCAG). Canvas2D on setInterval.
 */
import { useEffect, useRef } from 'react';
import { prefersReducedMotion } from './vizData';
import { INSTR } from './vizPalette';

export function SpatialRadar({
  observations,
  centroid,
  newZone = false,
  size = 190,
}: {
  observations: { latitude: number; longitude: number }[];
  centroid: { latitude: number; longitude: number };
  newZone?: boolean;
  size?: number;
}) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const reduce = prefersReducedMotion();
    const cx = size / 2;
    const cy = size / 2;
    const R = size / 2 - 22;

    // project to km east/north of the centroid
    const pts = observations.map((o) => ({
      x:
        (o.longitude - centroid.longitude) *
        111.32 *
        Math.cos((centroid.latitude * Math.PI) / 180),
      y: (o.latitude - centroid.latitude) * 111.32,
    }));
    const maxR = Math.max(2, ...pts.map((p) => Math.hypot(p.x, p.y))) * 1.2;
    const scale = R / maxR;
    let t0 = 0;

    const id = window.setInterval(() => {
      const now = reduce ? 0 : performance.now();
      if (t0 === 0) t0 = now;
      const dpr = window.devicePixelRatio || 1;
      canvas.width = Math.max(1, Math.round(size * dpr));
      canvas.height = Math.max(1, Math.round(size * dpr));
      canvas.style.width = `${size}px`;
      canvas.style.height = `${size}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, size, size);
      ctx.textAlign = 'left';
      ctx.font = '8px ui-monospace, monospace';
      ctx.lineWidth = 1;

      // range rings + km labels
      ctx.fillStyle = INSTR.mute;
      for (const f of [1 / 3, 2 / 3, 1]) {
        ctx.strokeStyle = INSTR.edge;
        ctx.beginPath();
        ctx.arc(cx, cy, R * f, 0, Math.PI * 2);
        ctx.stroke();
        ctx.fillText(`${(maxR * f).toFixed(1)}km`, cx + R * f * 0.7 + 3, cy - R * f * 0.7 - 3);
      }

      // crosshairs + N
      ctx.strokeStyle = INSTR.edge;
      ctx.beginPath();
      ctx.moveTo(cx - R, cy);
      ctx.lineTo(cx + R, cy);
      ctx.moveTo(cx, cy - R);
      ctx.lineTo(cx, cy + R);
      ctx.stroke();
      ctx.fillStyle = INSTR.dim;
      ctx.fillText('N', cx - 2, cy - R - 6);

      // rotating sweep (conic trail where the browser supports it)
      const sweep = reduce ? -Math.PI / 2 : ((now - t0) / 3600) % (Math.PI * 2);
      if (typeof ctx.createConicGradient === 'function') {
        const grad = ctx.createConicGradient(sweep, cx, cy);
        grad.addColorStop(0, 'rgba(255,107,53,0.32)');
        grad.addColorStop(0.12, 'rgba(255,107,53,0)');
        grad.addColorStop(1, 'rgba(255,107,53,0)');
        ctx.fillStyle = grad;
        ctx.beginPath();
        ctx.arc(cx, cy, R, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.strokeStyle = 'rgba(255,107,53,0.75)';
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.lineTo(cx + Math.cos(sweep) * R, cy + Math.sin(sweep) * R);
      ctx.stroke();

      // blips — newest brightest (API returns ascending observed_at)
      pts.forEach((p, i) => {
        const recency = pts.length > 1 ? i / (pts.length - 1) : 1;
        const x = cx + p.x * scale;
        const y = cy - p.y * scale;
        ctx.fillStyle = INSTR.ok;
        ctx.globalAlpha = 0.25 + recency * 0.75;
        ctx.beginPath();
        ctx.arc(x, y, 2.2, 0, Math.PI * 2);
        ctx.fill();
        ctx.globalAlpha = 1;
      });

      // newest detection reticle — blinks red on a new-zone flag
      if (pts.length > 0) {
        const last = pts[pts.length - 1];
        const x = cx + last.x * scale;
        const y = cy - last.y * scale;
        const on = reduce ? true : (now - t0) % 900 < 500;
        ctx.strokeStyle = newZone && on ? INSTR.magma : 'rgba(232,238,245,0.8)';
        const marks: [number, number, number, number][] = [
          [x - 7, y, x - 4, y],
          [x + 7, y, x + 4, y],
          [x, y - 7, x, y - 4],
          [x, y + 7, x, y + 4],
        ];
        for (const [x1, y1, x2, y2] of marks) {
          ctx.beginPath();
          ctx.moveTo(x1, y1);
          ctx.lineTo(x2, y2);
          ctx.stroke();
        }
        if (newZone && on) {
          ctx.fillStyle = INSTR.magma;
          ctx.fillText('NEW ZONE', x + 10, y + 3);
        }
      }
    }, 33);
    return () => window.clearInterval(id);
  }, [observations, centroid, newZone, size]);

  return (
    <canvas
      ref={ref}
      role="img"
      aria-label="Spatial radar of detections around the incident centroid"
    />
  );
}
