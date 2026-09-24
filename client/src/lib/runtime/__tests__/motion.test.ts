/**
 * Reduced-motion probe — node-safe guards plus the two live-DOM outcomes.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { prefersReducedMotion } from '../motion';

afterEach(() => vi.unstubAllGlobals());

describe('prefersReducedMotion', () => {
  it('is false in the node test environment (no window, no matchMedia)', () => {
    expect(prefersReducedMotion()).toBe(false);
  });

  it('is false when matchMedia is missing or not a function', () => {
    vi.stubGlobal('window', {});
    expect(prefersReducedMotion()).toBe(false);
    vi.stubGlobal('window', { matchMedia: 'nope' });
    expect(prefersReducedMotion()).toBe(false);
  });

  it('mirrors the media query result', () => {
    vi.stubGlobal('window', { matchMedia: () => ({ matches: true }) });
    expect(prefersReducedMotion()).toBe(true);
    vi.stubGlobal('window', { matchMedia: () => ({ matches: false }) });
    expect(prefersReducedMotion()).toBe(false);
  });

  it('degrades to false when matchMedia throws', () => {
    vi.stubGlobal('window', {
      matchMedia: () => {
        throw new Error('blocked by policy');
      },
    });
    expect(prefersReducedMotion()).toBe(false);
  });
});
