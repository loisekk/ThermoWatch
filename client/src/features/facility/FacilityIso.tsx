import { useEffect, useRef } from 'react';

const HAZ_H: Record<string, number> = { 'G-III': 6, 'G-II': 4, 'G-I': 2.5 };

/** Tiny isometric massing preview — setInterval-driven (rAF-independent). */
export function FacilityIso({ hazard, subtype }: { hazard: string; subtype: string }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    let az = Math.PI / 4;
    let raf = 0;
    const draw = () => {
      const cw = canvas.clientWidth, ch = 150;
      if (cw === 0) return;
      canvas.width = cw * devicePixelRatio; canvas.height = ch * devicePixelRatio;
      ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
      ctx.fillStyle = '#0b0f14'; ctx.fillRect(0, 0, cw, ch);
      const cx = cw / 2, cy = ch * 0.68, s = 9;
      const ca = Math.cos(az), sa = Math.sin(az);
      const P = (x: number, y: number, z: number): [number, number] => {
        const xr = x * ca - y * sa, yr = x * sa + y * ca;
        return [cx + xr * s, cy + yr * s * 0.45 - z * s * 0.9];
      };
      ctx.strokeStyle = 'rgba(42,54,68,0.6)'; ctx.lineWidth = 0.6;
      for (let g = -6; g <= 6; g += 2) {
        let a = P(g, -6, 0), b = P(g, 6, 0);
        ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke();
        a = P(-6, g, 0); b = P(6, g, 0);
        ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke();
      }
      const h = HAZ_H[hazard] ?? 3, w = 2;
      const base: [number, number][] = [[-w, -w], [w, -w], [w, w], [-w, w]];
      const top = base.map(([x, y]) => P(x, y, h));
      const bot = base.map(([x, y]) => P(x, y, 0));
      for (let i = 0; i < 4; i++) {
        const j = (i + 1) % 4;
        ctx.beginPath(); ctx.moveTo(bot[i][0], bot[i][1]); ctx.lineTo(bot[j][0], bot[j][1]); ctx.lineTo(top[j][0], top[j][1]); ctx.lineTo(top[i][0], top[i][1]); ctx.closePath();
        ctx.fillStyle = i % 2 ? '#2a333d' : '#39424d'; ctx.fill();
        ctx.strokeStyle = 'rgba(232,238,245,0.4)'; ctx.lineWidth = 0.8; ctx.stroke();
      }
      ctx.beginPath(); top.forEach((p, i) => (i === 0 ? ctx.moveTo(p[0], p[1]) : ctx.lineTo(p[0], p[1]))); ctx.closePath();
      ctx.fillStyle = '#7d8da1'; ctx.fill(); ctx.strokeStyle = 'rgba(232,238,245,0.6)'; ctx.stroke();
      ctx.fillStyle = '#8ca0b3'; ctx.font = '9px "IBM Plex Mono", monospace'; ctx.textAlign = 'center';
      ctx.fillText(`${subtype} · ${hazard} · ${Math.round(h * 100)} m`, cx, 14);
    };
    draw();
    const t = window.setInterval(() => { az += 0.01; draw(); }, 66);
    const ro = new ResizeObserver(draw);
    ro.observe(canvas);
    return () => { window.clearInterval(t); ro.disconnect(); cancelAnimationFrame(raf); };
  }, [hazard, subtype]);

  return <canvas ref={ref} className="h-[150px] w-full" aria-label="Facility isometric preview" />;
}