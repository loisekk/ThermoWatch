/**
 * Evidence Fusion Constellation — assessment sources orbiting the fused
 * verdict; dashed edges flow inward as contribution. Sources with zero
 * confidence render OFFLINE (the honest cold-start state until optical /
 * weather evidence is enabled). The center node pulses with the fused score
 * and always prints the number (WCAG — never color/shape alone).
 * Canvas2D on setInterval (no rAF, no WebGL).
 */
import { useEffect, useRef } from 'react';
import { prefersReducedMotion, type FusionSource } from './vizData';
import { INSTR } from './vizPalette';

export function FusionConstellation({
  sources,
  fusedScore,
  size = 160,
}: {
  sources: FusionSource[];
  fusedScore: number;
  size?: number;
}) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const reduce = prefersReducedMotion();
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
      const cx = size / 2;
      const cy = size / 2;
      const orbit = size / 2 - 34;
      const s = Math.max(0, Math.min(1, fusedScore));
      // verdict heat: ok green (0) → magma red (1)
      const heat = `rgb(${Math.round(63 + (255 - 63) * s)},${Math.round(
        185 + (68 - 185) * s,
      )},${Math.round(80 + (68 - 80) * s)})`;

      const nodes = sources.map((src, i) => {
        const a = (i / Math.max(sources.length, 1)) * Math.PI * 2 - Math.PI / 2;
        return { ...src, x: cx + Math.cos(a) * orbit, y: cy + Math.sin(a) * orbit };
      });

      // edges — dashes flow toward the verdict (contribution)
      nodes.forEach((n) => {
        const active = n.confidence > 0;
        ctx.strokeStyle = active
          ? `rgba(255,107,53,${0.2 + n.score * 0.5})`
          : INSTR.edge2;
        ctx.lineWidth = active
          ? 0.5 + Math.min(n.weight * n.confidence * 5, 5)
          : 0.5;
        ctx.setLineDash(active ? [4, 6] : [2, 4]);
        ctx.lineDashOffset = reduce ? 0 : -((now - t0) / 40) % 10;
        ctx.beginPath();
        ctx.moveTo(n.x, n.y);
        ctx.lineTo(cx, cy);
        ctx.stroke();
        ctx.setLineDash([]);
      });

      // source nodes + labels
      ctx.font = '7.5px ui-monospace, monospace';
      ctx.textAlign = 'left';
      nodes.forEach((n) => {
        const active = n.confidence > 0;
        ctx.beginPath();
        ctx.arc(n.x, n.y, active ? 4 + n.score * 4 : 3, 0, Math.PI * 2);
        if (active) {
          ctx.fillStyle = n.score > 0.5 ? INSTR.magma : INSTR.ok;
          ctx.fill();
        } else {
          ctx.strokeStyle = INSTR.dim;
          ctx.stroke();
        }
        ctx.fillStyle = active ? INSTR.mute : INSTR.dim;
        const caption = active ? n.name.toUpperCase().slice(0, 8) : 'OFFLINE';
        ctx.fillText(caption, n.x - 16, n.y + 15);
      });

      // center verdict node — pulses with the fused score
      const pulse = reduce ? 0.5 : 0.5 + 0.5 * Math.sin((now - t0) / 300);
      ctx.shadowColor = heat;
      ctx.shadowBlur = 8 + s * 14 * pulse;
      ctx.fillStyle = heat;
      ctx.beginPath();
      ctx.arc(cx, cy, 9 + s * 9, 0, Math.PI * 2);
      ctx.fill();
      ctx.shadowBlur = 0;
      ctx.textAlign = 'center';
      ctx.font = '10px ui-monospace, monospace';
      ctx.fillStyle = INSTR.ink;
      ctx.fillText(fusedScore.toFixed(2), cx, cy + 26);
      ctx.fillStyle = INSTR.dim;
      ctx.font = '7.5px ui-monospace, monospace';
      ctx.fillText('FUSED', cx, cy - 20);
      ctx.textAlign = 'left';
    }, 40);
    return () => window.clearInterval(id);
  }, [sources, fusedScore, size]);

  return <canvas ref={ref} role="img" aria-label="Evidence fusion constellation" />;
}
