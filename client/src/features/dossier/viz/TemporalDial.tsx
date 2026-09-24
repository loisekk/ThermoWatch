/**
 * Temporal Dial — 24h clock of detection hours: radial activity bars inside
 * a night-shaded wedge (18:00–06:00), so diurnal patterns become geometry.
 * Numbers stay on the dial: hour labels + center observation count.
 * Canvas2D on setInterval (no rAF, no WebGL).
 */
import { useEffect, useRef } from 'react';
import { hourHistogram, isNightHour } from './vizData';
import { INSTR } from './vizPalette';

export function TemporalDial({ hours, size = 150 }: { hours: number[]; size?: number }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const counts = hourHistogram(hours);
    const maxC = Math.max(1, ...counts);

    const id = window.setInterval(() => {
      const dpr = window.devicePixelRatio || 1;
      canvas.width = Math.max(1, Math.round(size * dpr));
      canvas.height = Math.max(1, Math.round(size * dpr));
      canvas.style.width = `${size}px`;
      canvas.style.height = `${size}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, size, size);
      const cx = size / 2;
      const cy = size / 2;
      const R = size / 2 - 16;
      ctx.textAlign = 'left';
      ctx.font = '8px ui-monospace, monospace';

      // night wedge 18:00 → 06:00 (arc π → 2π passes midnight at the top)
      ctx.fillStyle = 'rgba(140,160,179,0.07)';
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.arc(cx, cy, R, Math.PI, Math.PI * 2);
      ctx.closePath();
      ctx.fill();

      // inner ring
      ctx.strokeStyle = INSTR.edge2;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.arc(cx, cy, R * 0.45, 0, Math.PI * 2);
      ctx.stroke();

      // radial hourly bars — ember at night, green by day
      counts.forEach((c, h) => {
        const a = (h / 24) * Math.PI * 2 - Math.PI / 2;
        const len = c > 0 ? (c / maxC) * (R - R * 0.45) : 2;
        ctx.strokeStyle = c > 0 ? (isNightHour(h) ? INSTR.ember : INSTR.ok) : INSTR.edge2;
        ctx.lineWidth = 3;
        ctx.beginPath();
        ctx.moveTo(cx + Math.cos(a) * R * 0.48, cy + Math.sin(a) * R * 0.48);
        ctx.lineTo(
          cx + Math.cos(a) * (R * 0.48 + len),
          cy + Math.sin(a) * (R * 0.48 + len),
        );
        ctx.stroke();
      });

      // quadrant labels
      ctx.lineWidth = 1;
      ctx.fillStyle = INSTR.dim;
      for (const h of [0, 6, 12, 18]) {
        const a = (h / 24) * Math.PI * 2 - Math.PI / 2;
        ctx.fillText(
          `${h}`.padStart(2, '0'),
          cx + Math.cos(a) * (R + 7) - 6,
          cy + Math.sin(a) * (R + 7) + 3,
        );
      }

      // center count — the number the bars summarize
      ctx.textAlign = 'center';
      ctx.fillStyle = INSTR.mute;
      ctx.fillText(`${hours.length} obs`, cx, cy + 3);
      ctx.textAlign = 'left';
    }, 100);
    return () => window.clearInterval(id);
  }, [hours, size]);

  return <canvas ref={ref} role="img" aria-label="24-hour detection distribution" />;
}
