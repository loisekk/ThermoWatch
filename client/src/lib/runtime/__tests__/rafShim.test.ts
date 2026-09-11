import { describe, expect, it } from 'vitest';
import { getRafStatus, installRafShimIfDead, measureRaf } from '../rafShim';

describe('rafShim (node env, no window)', () => {
  it('measureRaf resolves 0 without a DOM', async () => {
    expect(await measureRaf(50)).toBe(0);
  });

  it('install is a safe no-op outside browsers', async () => {
    const st = await installRafShimIfDead();
    expect(st.shimmed).toBe(false);
  });

  it('getRafStatus never throws', () => {
    expect(typeof getRafStatus().fps).toBe('number');
  });
});
