import { describe, expect, it } from 'vitest';
import { latLonToUV, orthoInverse } from '../geo/sphereMap';

describe('orthoInverse', () => {
  it('disc center maps to the globe center', () => {
    const h = orthoInverse(0, 0, 78, 22);
    expect(h).not.toBeNull();
    expect(h!.lat).toBeCloseTo(22, 5);
    expect(h!.lon).toBeCloseTo(78, 5);
  });
  it('outside the disc is invisible', () => {
    expect(orthoInverse(1.2, 0.3, 0, 0)).toBeNull();
  });
  it('round-trips a forward-projected point', () => {
    const lon0 = 10, lat0 = 30, lon = 25, lat = 40;
    const r = Math.PI / 180;
    const l = (lon - lon0) * r, p = lat * r, p0 = lat0 * r;
    const dx = Math.cos(p) * Math.sin(l);
    const dyUp = Math.cos(p0) * Math.sin(p) - Math.sin(p0) * Math.cos(p) * Math.cos(l);
    const z = Math.sin(p0) * Math.sin(p) + Math.cos(p0) * Math.cos(p) * Math.cos(l);
    if (z <= 0) return; // back side — skip
    const h = orthoInverse(dx, dyUp, lon0, lat0);
    expect(h).not.toBeNull();
    expect(h!.lat).toBeCloseTo(lat, 3);
    expect(h!.lon).toBeCloseTo(lon, 3);
  });
  it('uv spans [0,1]', () => {
    const { u, v } = latLonToUV(0, 0);
    expect(u).toBeCloseTo(0.5);
    expect(v).toBeCloseTo(0.5);
  });
});