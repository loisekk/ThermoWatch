import { getRafStatus } from '@/lib/runtime/rafShim';

export interface WebGLStatus {
  context: boolean;
  rasterizes: boolean;
  renderer: string;
}

export interface RendererCapability extends WebGLStatus {
  rafFps: number;
  shimmed: boolean;
  ok: boolean;
}

// Context hygiene (Session 17): ONE reused probe context, explicitly released after
// every measurement. Browsers cap live WebGL contexts (~16); a probe that creates a
// fresh context per call and never releases it can force-evict a real engine's
// context — the "renders ~1 s then black" symptom.
let probeCanvas: HTMLCanvasElement | null = null;
let probeGl: (WebGLRenderingContext | WebGL2RenderingContext) | null = null;

/** Context creation != rasterization. Only a readPixels round-trip proves frames paint. */
export function probeWebGL(): WebGLStatus {
  try {
    if (!probeGl || probeGl.isContextLost()) {
      probeCanvas = document.createElement('canvas');
      probeCanvas.width = 4;
      probeCanvas.height = 4;
      probeGl = (probeCanvas.getContext('webgl2') ?? probeCanvas.getContext('webgl')) as (WebGLRenderingContext | WebGL2RenderingContext) | null;
    }
    const gl = probeGl;
    if (!gl) return { context: false, rasterizes: false, renderer: 'none' };
    const dbg = gl.getExtension('WEBGL_debug_renderer_info');
    const renderer = dbg ? String(gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL)) : String(gl.getParameter(gl.RENDERER));
    gl.clearColor(1, 0, 0, 1);
    gl.clear(gl.COLOR_BUFFER_BIT);
    const px = new Uint8Array(4);
    gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px);
    const lost = gl.isContextLost();
    // FREE the slot immediately so a probe can never evict a live engine's context.
    try {
      const lose = gl.getExtension('WEBGL_lose_context');
      if (typeof (lose as { loseContext?: unknown }).loseContext === 'function') {
        (lose as { loseContext: () => void }).loseContext();
      }
    } catch {
      // extension absent (rare) — the context is GC'd with its canvas
    }
    probeGl = null;
    probeCanvas = null;
    return { context: true, rasterizes: !lost && px[0] > 200 && px[3] > 200, renderer };
  } catch {
    probeGl = null;
    probeCanvas = null;
    return { context: false, rasterizes: false, renderer: 'none' };
  }
}

/** Full picture: GL rasterization + rAF liveness (post-shim). ok = GL engines usable. */
export async function probeRenderer(): Promise<RendererCapability> {
  const gl = probeWebGL();
  const raf = getRafStatus();
  const rafFps = raf.fps >= 0 ? raf.fps : 0;
  return { ...gl, rafFps, shimmed: raf.shimmed, ok: gl.context && gl.rasterizes && (rafFps > 0 || raf.shimmed) };
}