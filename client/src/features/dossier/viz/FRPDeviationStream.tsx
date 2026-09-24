/**
 * FRP Deviation Stream — the dossier's hero waveform: log1p(FRP) over time
 * against the facility's normal envelope, so "is this normal?" reads as a
 * shape (dots inside vs escaping the band) instead of a subtraction.
 * Canvas2D on setInterval (renderer-resilience doctrine): no rAF, no WebGL.
 * Numeric parity: MW axis ticks + a caption spell out green/red (WCAG).
 */
import { useEffect, useRef } from 'react';
import type { ObservationDetail } from '@/services/api/v2Types';
import { frpEnvelope, prefersReducedMotion } from './vizData';
import { INSTR } from './vizPalette';

export function FRPDeviationStream({
  observations,
  expectedP10,
  expectedP90,
  height = 140,
}: {
  observations: ObservationDetail[];
  /** Facility normal band in raw FRP (MW) — p10/p90 once a normal state is exposed. */
  expectedP10?: number | null;
  expectedP90?: number | null;
  height?: number;
}) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas || observations.length === 0) return;
    const ctx = canvas.getContext('2d');
    const parent = canvas.parentElement;
    if (!ctx || !parent) return;

    const reduce = prefersReducedMotion();
    const logs = observations.map((o) => Math.log1p(Math.max(o.frp ?? 0, 0)));
    const times = observations.map((o) => new Date(o.observed_at).getTime());
    const tMin = Math.min(...times);
    const tMax = Math.max(...times);
    const { lo, hi, baselineKnown } = frpEnvelope(logs, expectedP10, expectedP90);
    const yMin = Math.min(lo, ...logs) - 0.3;
    const ySpan = Math.max(Math.max(hi, ...logs) + 0.3 - yMin, 1e-6);
    const span = Math.max(tMax - tMin, 1);
    const newest = Math.max(...times);
    let W = 0;
    let H = 0;
    let t0 = 0;

    const draw = () => {
      const now = reduce ? 0 : performance.now();
      if (t0 === 0) t0 = now;
      const dpr = window.devicePixelRatio || 1;
      const w = parent.clientWidth;
      if (w === 0) return;
      const h = height;
      if (w !== W || h !== H) {
        W = w;
        H = h;
        canvas.width = Math.max(1, Math.round(w * dpr));
        canvas.height = Math.max(1, Math.round(h * dpr));
        canvas.style.width = `${w}px`;
        canvas.style.height = `${h}px`;
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      const px = (t: number): number => 34 + ((t - tMin) / span) * (w - 46);
      const py = (v: number): number => h - 18 - ((v - yMin) / ySpan) * (h - 30);

      // grid + FRP (MW) ticks — log1p inverted with expm1
      ctx.lineWidth = 1;
      ctx.font = '9px ui-monospace, monospace';
      ctx.textAlign = 'left';
      for (let i = 0; i <= 3; i++) {
        const v = yMin + (ySpan * i) / 3;
        ctx.strokeStyle = INSTR.edge2;
        ctx.beginPath();
        ctx.moveTo(34, py(v));
        ctx.lineTo(w - 12, py(v));
        ctx.stroke();
        ctx.fillStyle = INSTR.mute;
        ctx.fillText(`${Math.expm1(v).toFixed(0)}`, 4, py(v) + 3);
      }

      // normal envelope — THE signal
      const bandTop = Math.max(py(hi), 12);
      ctx.fillStyle = 'rgba(63,185,80,0.10)';
      ctx.strokeStyle = 'rgba(63,185,80,0.35)';
      ctx.setLineDash([4, 3]);
      ctx.beginPath();
      ctx.rect(34, bandTop, w - 46, Math.max(py(lo) - bandTop, 1));
      ctx.fill();
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = 'rgba(63,185,80,0.85)';
      ctx.fillText(
        baselineKnown ? 'FACILITY NORMAL BAND' : 'DATA IQR (no baseline)',
        38,
        bandTop - 4,
      );

      // observations — red drop-line + ring when outside the band
      times.forEach((t, i) => {
        const x = px(t);
        const y = py(logs[i]);
        const outside = logs[i] < lo || logs[i] > hi;
        if (outside) {
          ctx.strokeStyle = INSTR.magma;
          ctx.globalAlpha = 0.4;
          ctx.beginPath();
          ctx.moveTo(x, h - 18);
          ctx.lineTo(x, y);
          ctx.stroke();
          ctx.globalAlpha = 1;
        }
        ctx.fillStyle = outside ? INSTR.magma : INSTR.ok;
        ctx.beginPath();
        ctx.arc(x, y, outside ? 3.5 : 2.5, 0, Math.PI * 2);
        ctx.fill();
        if (t === newest) {
          const pulse = ((now - t0) % 1600) / 1600;
          ctx.strokeStyle = outside ? INSTR.magma : INSTR.ok;
          ctx.globalAlpha = 1 - pulse;
          ctx.beginPath();
          ctx.arc(x, y, 3 + pulse * 10, 0, Math.PI * 2);
          ctx.stroke();
          ctx.globalAlpha = 1;
        }
      });
    };

    draw();
    const id = window.setInterval(draw, 50);
    return () => window.clearInterval(id);
  }, [observations, expectedP10, expectedP90, height]);

  if (observations.length === 0) {
    return <p className="mono text-[10px] text-dim">No observations to plot.</p>;
  }

  return (
    <div className="w-full">
      <canvas
        ref={ref}
        role="img"
        aria-label="FRP over time against the facility normal band"
      />
      <p className="mono mt-1 text-[9px] text-dim">
        Green = within expected band · Red = deviation · log1p FRP axis (MW)
      </p>
    </div>
  );
}
