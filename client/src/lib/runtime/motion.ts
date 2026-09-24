/**
 * Reduced-motion probe shared by every canvas instrument: CSS cannot stop a
 * setInterval draw loop, so the canvas clock freezes instead (still redraws
 * on resize/data, never animates). Node-safe for vitest.
 */
export function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return false;
  }
  try {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  } catch {
    return false;
  }
}
