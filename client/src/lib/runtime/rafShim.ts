/** rAF liveness measurement + setTimeout driver for hosts where rAF never fires.
 *  Revives every rAF-driven render engine (MapLibre, three.js, globe.gl, deck.gl)
 *  without touching them: they resolve window.requestAnimationFrame at call time. */

export interface RafStatus {
  fps: number;
  shimmed: boolean;
}

const KEY = '__tw_raf';

export function getRafStatus(): RafStatus {
  if (typeof window === 'undefined') return { fps: 0, shimmed: false };
  return (window as unknown as Record<string, RafStatus | undefined>)[KEY] ?? { fps: -1, shimmed: false };
}

/** Counts rAF frames; resolves early once liveness is proven. Dead rAF -> 0 after `ms`. */
export function measureRaf(ms = 400): Promise<number> {
  return new Promise((resolve) => {
    if (typeof window === 'undefined' || typeof window.requestAnimationFrame !== 'function') return resolve(0);
    let frames = 0;
    let done = false;
    const t0 = performance.now();
    const finish = (elapsed: number) => {
      if (done) return;
      done = true;
      resolve(Math.round((frames / Math.max(elapsed, 1)) * 1000));
    };
    const loop = () => {
      frames++;
      const el = performance.now() - t0;
      if (frames >= 3) return finish(el);
      window.requestAnimationFrame(loop);
    };
    window.requestAnimationFrame(loop);
    window.setTimeout(() => finish(ms), ms + 50);
  });
}

/** Boot-time gate: if rAF is dead, replace it with a 16 ms setTimeout driver. */
export async function installRafShimIfDead(): Promise<RafStatus> {
  if (typeof window === 'undefined') return { fps: 0, shimmed: false };
  const fps = await measureRaf(400);
  if (fps > 0) {
    const st: RafStatus = { fps, shimmed: false };
    (window as unknown as Record<string, RafStatus>)[KEY] = st;
    return st;
  }
  let seq = 0;
  const queue = new Map<number, FrameRequestCallback>();
  const driver = () => {
    if (queue.size === 0) return;
    const batch = [...queue.values()];
    queue.clear();
    const now = performance.now();
    for (const cb of batch) {
      try {
        cb(now);
      } catch (e) {
        console.error('[raf-shim] frame callback failed:', e);
      }
    }
  };
  window.requestAnimationFrame = (cb: FrameRequestCallback) => { const id = ++seq; queue.set(id, cb); return id; };
  window.cancelAnimationFrame = (id: number) => { queue.delete(id); };
  window.setInterval(driver, 16);
  const st: RafStatus = { fps: 0, shimmed: true };
  (window as unknown as Record<string, RafStatus>)[KEY] = st;
  console.warn('[raf-shim] requestAnimationFrame never fired on this host - installed setTimeout(16ms) driver; GL render engines revived');
  return st;
}
