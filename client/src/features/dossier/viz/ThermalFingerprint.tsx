/**
 * Thermal Fingerprint — 10-axis radar of source-class probabilities that
 * morphs (lerp) when a new assessment version arrives: the polygon shape IS
 * the facility's class signature, with a dashed uniform decagon showing what
 * "no information" looks like. Canvas2D on setInterval (no rAF, no WebGL).
 */
import { useEffect, useRef } from 'react';
import { prefersReducedMotion } from './vizData';
import { INSTR } from './vizPalette';

/** [server class key, 3-letter axis code] — mirrors SOURCE_CLASSES order. */
const CLASSES: [string, string][] = [
  ['refinery', 'REF'],
  ['steel', 'STL'],
  ['gas_flare', 'GAS'],
  ['cement', 'CEM'],
  ['smelter', 'SML'],
  ['waste_incineration', 'WST'],
  ['power_plant', 'PWR'],
  ['chemical', 'CHM'],
  ['unknown_industrial', 'UNK'],
  ['natural_fire', 'NAT'],
];

export function ThermalFingerprint({
  scores,
  size = 160,
}: {
  scores: Record<string, number>;
  size?: number;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  const shown = useRef<number[]>(CLASSES.map(() => 0));

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const reduce = prefersReducedMotion();
    const targets = CLASSES.map(([key]) => scores[key] ?? 0);
    const cx = size / 2;
    const cy = size / 2 + 6;
    const R = size / 2 - 26;
    const angle = (i: number): number =>
      (i / CLASSES.length) * Math.PI * 2 - Math.PI / 2;
    const radius = (v: number, maxV: number): number => R * (v / maxV) * 0.95;

    const id = window.setInterval(() => {
      const dpr = window.devicePixelRatio || 1;
      canvas.width = Math.max(1, Math.round(size * dpr));
      canvas.height = Math.max(1, Math.round(size * dpr));
      canvas.style.width = `${size}px`;
      canvas.style.height = `${size}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, size, size);

      // morph toward the latest scores (snap under reduced motion)
      shown.current = reduce
        ? targets.slice()
        : shown.current.map((v, i) => v + (targets[i] - v) * 0.12);

      // rings
      ctx.font = '8px ui-monospace, monospace';
      ctx.lineWidth = 1;
      for (const r of [0.33, 0.66, 1]) {
        ctx.strokeStyle = INSTR.edge;
        ctx.beginPath();
        for (let i = 0; i <= CLASSES.length; i++) {
          const a = angle(i % CLASSES.length);
          const x = cx + Math.cos(a) * R * r;
          const y = cy + Math.sin(a) * R * r;
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
        ctx.stroke();
      }

      // axes + codes (active codes in brand ember)
      CLASSES.forEach(([, code], i) => {
        const a = angle(i);
        ctx.strokeStyle = INSTR.edge2;
        ctx.beginPath();
        ctx.moveTo(cx, cy);
        ctx.lineTo(cx + Math.cos(a) * R, cy + Math.sin(a) * R);
        ctx.stroke();
        ctx.fillStyle = (scores[CLASSES[i][0]] ?? 0) > 0.15 ? INSTR.ember : INSTR.dim;
        ctx.fillText(code, cx + Math.cos(a) * (R + 12) - 8, cy + Math.sin(a) * (R + 12) + 3);
      });

      // uniform baseline (dashed) — what "no information" looks like
      ctx.strokeStyle = INSTR.steel;
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      CLASSES.forEach((_, i) => {
        const a = angle(i);
        const x = cx + Math.cos(a) * R * 0.1;
        const y = cy + Math.sin(a) * R * 0.1;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.closePath();
      ctx.stroke();
      ctx.setLineDash([]);

      // the fingerprint polygon
      const maxV = Math.max(0.15, ...shown.current);
      ctx.beginPath();
      shown.current.forEach((v, i) => {
        const a = angle(i);
        const x = cx + Math.cos(a) * radius(v, maxV);
        const y = cy + Math.sin(a) * radius(v, maxV);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.closePath();
      ctx.fillStyle = 'rgba(255,107,53,0.16)';
      ctx.fill();
      ctx.strokeStyle = INSTR.ember;
      ctx.lineWidth = 1.5;
      ctx.stroke();
      ctx.fillStyle = INSTR.ember;
      shown.current.forEach((v, i) => {
        const a = angle(i);
        ctx.beginPath();
        ctx.arc(
          cx + Math.cos(a) * radius(v, maxV),
          cy + Math.sin(a) * radius(v, maxV),
          2,
          0,
          Math.PI * 2,
        );
        ctx.fill();
      });
    }, 40);
    return () => window.clearInterval(id);
  }, [scores, size]);

  return <canvas ref={ref} role="img" aria-label="Source class probability radar" />;
}
