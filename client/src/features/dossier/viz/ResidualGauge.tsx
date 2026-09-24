/**
 * Residual Gauge — intensity z-score as a needle instrument with
 * green/amber/red zones (|z| < 2 / < threshold / beyond). The digital
 * readout stays visible beside the needle (WCAG — never color alone), and
 * z = null honestly reads NO BASELINE instead of pointing at zero.
 * Canvas2D on setInterval (no rAF, no WebGL).
 */
import { useEffect, useRef } from 'react';
import { prefersReducedMotion } from './vizData';
import { INSTR } from './vizPalette';

export function ResidualGauge({
  z,
  threshold = 3.5,
  label = 'INTENSITY',
  size = 130,
}: {
  z: number | null;
  threshold?: number;
  label?: string;
  size?: number;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  const needle = useRef(0);
  const h = Math.round(size * 0.86); // room for the readout + caption below the arc

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const reduce = prefersReducedMotion();
    const cx = size / 2;
    const cy = size / 2 + 14;
    const R = size / 2 - 12;
    const clamp = (v: number): number => Math.max(-5, Math.min(5, v));
    const target = z == null ? 0 : clamp(z);
    const ang = (v: number): number => Math.PI + ((v + 5) / 10) * Math.PI; // -5..5 → π..2π

    const id = window.setInterval(() => {
      const dpr = window.devicePixelRatio || 1;
      canvas.width = Math.max(1, Math.round(size * dpr));
      canvas.height = Math.max(1, Math.round(h * dpr));
      canvas.style.width = `${size}px`;
      canvas.style.height = `${h}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, size, h);
      ctx.textAlign = 'left';

      // zones: green |z|<2, amber 2..threshold, red beyond
      const zone = (from: number, to: number, color: string): void => {
        ctx.strokeStyle = color;
        ctx.lineWidth = 7;
        ctx.beginPath();
        ctx.arc(cx, cy, R, ang(from), ang(to));
        ctx.stroke();
      };
      zone(-2, 2, INSTR.ok);
      zone(2, threshold, INSTR.amber);
      zone(-threshold, -2, INSTR.amber);
      zone(threshold, 5, INSTR.magma);
      zone(-5, -threshold, INSTR.magma);

      // ticks + numerals
      ctx.font = '8px ui-monospace, monospace';
      ctx.lineWidth = 1;
      for (const v of [-5, -2, 0, 2, 5]) {
        const a = ang(v);
        ctx.strokeStyle = INSTR.mute;
        ctx.beginPath();
        ctx.moveTo(cx + Math.cos(a) * (R - 8), cy + Math.sin(a) * (R - 8));
        ctx.lineTo(cx + Math.cos(a) * (R - 2), cy + Math.sin(a) * (R - 2));
        ctx.stroke();
        ctx.fillStyle = INSTR.dim;
        ctx.fillText(`${v}`, cx + Math.cos(a) * (R - 20) - 3, cy + Math.sin(a) * (R - 20) + 3);
      }

      // needle (snaps under reduced motion) or the NO-BASELINE state
      needle.current = reduce ? target : needle.current + (target - needle.current) * 0.15;
      const a = ang(needle.current);
      ctx.textAlign = 'center';
      if (z == null) {
        ctx.fillStyle = INSTR.dim;
        ctx.font = '10px ui-monospace, monospace';
        ctx.fillText('NO BASELINE', cx, cy - 4);
      } else {
        const color =
          Math.abs(z) > threshold ? INSTR.magma : Math.abs(z) > 2 ? INSTR.amber : INSTR.ok;
        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        ctx.shadowColor = color;
        ctx.shadowBlur = 6;
        ctx.beginPath();
        ctx.moveTo(cx, cy);
        ctx.lineTo(cx + Math.cos(a) * (R - 12), cy + Math.sin(a) * (R - 12));
        ctx.stroke();
        ctx.shadowBlur = 0;
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(cx, cy, 3, 0, Math.PI * 2);
        ctx.fill();
      }

      // digital readout + caption (the number never hides behind the needle)
      ctx.textAlign = 'center';
      ctx.font = '11px ui-monospace, monospace';
      ctx.fillStyle = z == null ? INSTR.dim : Math.abs(z) > threshold ? INSTR.magma : INSTR.ink;
      ctx.fillText(
        z == null ? 'z = --' : `z = ${z >= 0 ? '+' : ''}${z.toFixed(2)}`,
        cx,
        cy + 14,
      );
      ctx.fillStyle = INSTR.dim;
      ctx.font = '8px ui-monospace, monospace';
      ctx.fillText(label, cx, cy + 26);
    }, 40);
    return () => window.clearInterval(id);
  }, [z, threshold, label, size, h]);

  return <canvas ref={ref} role="img" aria-label={`${label} residual gauge`} />;
}
