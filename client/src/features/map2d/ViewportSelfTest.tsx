import { useEffect, useState } from 'react';
import { X } from 'lucide-react';
import { probeWebGL } from '@/features/map2d/WebGLProbe';
import { useUIStore } from '@/store/useUIStore';

interface Result {
  canvas2d: string;
  webgl: string;
  raf: string;
  stage: string;
  dpr: string;
}

export function ViewportSelfTest() {
  const toggleSelfTest = useUIStore((s) => s.toggleSelfTest);
  const [res, setRes] = useState<Result | null>(null);

  useEffect(() => {
    let canvas2d = 'FAIL';
    try {
      const c = document.createElement('canvas');
      c.width = 4;
      c.height = 4;
      const cx = c.getContext('2d');
      if (cx) {
        cx.fillStyle = '#f00';
        cx.fillRect(0, 0, 4, 4);
        const d = cx.getImageData(0, 0, 1, 1).data;
        canvas2d = d[0] > 200 ? 'OK' : 'FAIL(readback)';
      }
    } catch {
      canvas2d = 'EXCEPTION';
    }

    const gl = probeWebGL();
    const webgl = !gl.context
      ? 'NO CONTEXT'
      : gl.rasterizes
        ? `OK (${gl.renderer.slice(0, 28)})`
        : `BROKEN RASTER (${gl.renderer.slice(0, 28)})`;

    let frames = 0;
    let t0 = 0;
    const loop = () => {
      frames++;
      if (performance.now() - t0 < 1000) requestAnimationFrame(loop);
    };
    t0 = performance.now();
    requestAnimationFrame(loop);

    const stage = document.getElementById('viewport-stage');
    const size = stage
      ? `${stage.clientWidth}×${stage.clientHeight}`
      : 'MISSING';

    window.setTimeout(() => {
      setRes({
        canvas2d,
        webgl,
        raf:
          frames > 5 ? `OK (${frames} fps)` : frames > 0 ? `STALLED (${frames}/s)` : 'DEAD (0 frames/s)',
        stage: size,
        dpr: String(window.devicePixelRatio),
      });
    }, 1100);
  }, []);

  return (
    <div className="absolute left-1/2 top-16 z-40 w-72 -translate-x-1/2 rounded-md border border-edge bg-panel/95 p-3 backdrop-blur">
      <div className="mb-2 flex items-center justify-between">
        <span className="mono text-[10px] uppercase tracking-widest text-amber">viewport self-test</span>
        <button
          onClick={toggleSelfTest}
          aria-label="Close self-test"
          className="rounded p-0.5 text-mute hover:text-ink"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
      {!res && <div className="mono text-[10px] text-dim">measuring… (1 s)</div>}
      {res && (
        <ul className="mono space-y-1 text-[10px]">
          <li>
            canvas2d :{' '}
            <span className={res.canvas2d === 'OK' ? 'text-ok' : 'text-magma'}>{res.canvas2d}</span>
          </li>
          <li>
            webgl&nbsp;&nbsp;&nbsp; :{' '}
            <span className={res.webgl.startsWith('OK') ? 'text-ok' : 'text-magma'}>{res.webgl}</span>
          </li>
          <li>
            raf&nbsp;&nbsp;&nbsp;&nbsp; :{' '}
            <span className={res.raf.startsWith('OK') ? 'text-ok' : 'text-magma'}>{res.raf}</span>
          </li>
          <li>
            stage&nbsp;&nbsp; :{' '}
            <span
              className={res.stage === 'MISSING' || res.stage.startsWith('0×') ? 'text-magma' : 'text-ink'}
            >
              {res.stage}
            </span>
          </li>
          <li className="text-ink">dpr&nbsp;&nbsp;&nbsp;&nbsp; : {res.dpr}</li>
        </ul>
      )}
      <div className="mono mt-2 text-[9px] leading-relaxed text-dim">
        webgl=BROKEN or raf=DEAD/STALLED ? the GL engines cannot paint here — the Canvas2D renderers
        (globe + map) are the safe default.
      </div>
    </div>
  );
}
