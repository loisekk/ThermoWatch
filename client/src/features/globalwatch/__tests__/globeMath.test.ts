/**
 * Pure globe-math tests (vitest node env — no DOM, no canvas).
 */
import { describe, expect, it } from 'vitest';
import {
  centerRotation,
  isVisible,
  latLonToVec3,
  rotateVec,
  shortestAngle,
  subsolarPoint,
  toScreen,
} from '../globeMath';

const len = (v: { x: number; y: number; z: number }) => Math.hypot(v.x, v.y, v.z);

describe('latLonToVec3', () => {
  it('puts (0,0) at +z, the north pole at +y and (0,90) at +x', () => {
    const origin = latLonToVec3(0, 0);
    expect(origin.z).toBeCloseTo(1, 10);
    expect(origin.x).toBeCloseTo(0, 10);

    const pole = latLonToVec3(90, 0);
    expect(pole.y).toBeCloseTo(1, 10);

    const east = latLonToVec3(0, 90);
    expect(east.x).toBeCloseTo(1, 10);
    expect(east.z).toBeCloseTo(0, 10);
  });
});

describe('rotateVec', () => {
  it('is a rigid rotation — length is preserved', () => {
    const v = latLonToVec3(22.47, 70.07);
    expect(len(rotateVec(v, 0, 0))).toBeCloseTo(1, 10);
    expect(len(rotateVec(v, 1.3, -0.7))).toBeCloseTo(1, 10);
    expect(len(rotateVec(v, -Math.PI / 3, 0.9))).toBeCloseTo(1, 10);
  });

  it('returns the vector unchanged for zero rotation', () => {
    const v = latLonToVec3(-33.9, 18.4);
    const r = rotateVec(v, 0, 0);
    expect(r.x).toBeCloseTo(v.x, 10);
    expect(r.y).toBeCloseTo(v.y, 10);
    expect(r.z).toBeCloseTo(v.z, 10);
  });

  it('is a full turn after 2π', () => {
    const v = latLonToVec3(10, 20);
    const r = rotateVec(v, Math.PI * 2, 0);
    expect(r.x).toBeCloseTo(v.x, 8);
    expect(r.z).toBeCloseTo(v.z, 8);
  });
});

describe('isVisible', () => {
  it('front point is visible, rotated-away point is not', () => {
    const p = latLonToVec3(0, 0);
    expect(isVisible(rotateVec(p, 0, 0))).toBe(true);
    expect(isVisible(rotateVec(p, Math.PI, 0))).toBe(false);
  });

  it('treats the exact limb as a boundary (z ≈ 0 within float noise)', () => {
    const limb = latLonToVec3(0, 90);
    expect(Math.abs(rotateVec(limb, 0, 0).z)).toBeLessThan(1e-12);
  });

  it('hides the far hemisphere', () => {
    for (const lon of [120, 180, -150]) {
      expect(isVisible(rotateVec(latLonToVec3(0, lon), 0, 0))).toBe(false);
    }
  });
});

describe('toScreen', () => {
  it('maps +y up and +x right around the given center', () => {
    expect(toScreen({ x: 0, y: 0, z: 1 }, 100, 100, 50)).toEqual({ x: 100, y: 100 });
    expect(toScreen({ x: 1, y: 1, z: 0 }, 100, 100, 50)).toEqual({ x: 150, y: 50 });
  });
});

describe('centerRotation', () => {
  it('makes the target face the viewer (z ≈ 1, x/y ≈ 0)', () => {
    for (const [lat, lon] of [[22.47, 70.07], [-33.9, 18.4], [51.5, -0.1], [0, 180], [-80, -170]]) {
      const t = centerRotation(lat, lon);
      const v = rotateVec(latLonToVec3(lat, lon), t.lonRot, t.latRot);
      expect(v.z).toBeGreaterThan(0.999);
      expect(Math.abs(v.x)).toBeLessThan(0.001);
      expect(Math.abs(v.y)).toBeLessThan(0.001);
    }
  });
});

describe('shortestAngle', () => {
  it('picks the short way around', () => {
    expect(shortestAngle(0.1, Math.PI * 2 - 0.1)).toBeCloseTo(-0.2, 5);
    expect(shortestAngle(3.0, -3.0)).toBeCloseTo(0.28318, 4);
  });

  it('returns 0 for equal angles and stays within (-π, π]', () => {
    expect(shortestAngle(1.234, 1.234)).toBe(0);
    for (const [from, to] of [[0, Math.PI], [0, -Math.PI], [-9, 9], [100, -100]]) {
      const d = shortestAngle(from, to);
      expect(d).toBeGreaterThan(-Math.PI - 1e-9);
      expect(d).toBeLessThanOrEqual(Math.PI + 1e-9);
    }
  });

  it('never exceeds half a turn in magnitude', () => {
    for (let from = -12; from <= 12; from += 0.7) {
      for (let to = -12; to <= 12; to += 1.1) {
        expect(Math.abs(shortestAngle(from, to))).toBeLessThanOrEqual(Math.PI + 1e-9);
      }
    }
  });
});

describe('subsolarPoint', () => {
  it('stays in physical bounds', () => {
    const s = subsolarPoint(new Date('2026-09-23T12:00:00Z'));
    expect(s.lat).toBeGreaterThanOrEqual(-23.44);
    expect(s.lat).toBeLessThanOrEqual(23.44);
    expect(s.lon).toBeGreaterThanOrEqual(-180);
    expect(s.lon).toBeLessThanOrEqual(180);
  });

  it('reaches the June/December declination extremes', () => {
    expect(subsolarPoint(new Date('2026-06-21T12:00:00Z')).lat).toBeGreaterThan(22);
    expect(subsolarPoint(new Date('2026-12-21T12:00:00Z')).lat).toBeLessThan(-22);
  });

  it('tracks the 15°/hour spin: noon UTC ≈ 0°, midnight UTC ≈ ±180°', () => {
    expect(Math.abs(subsolarPoint(new Date('2026-03-21T12:00:00Z')).lon)).toBeLessThan(0.01);
    expect(Math.abs(Math.abs(subsolarPoint(new Date('2026-03-21T00:00:00Z')).lon) - 180)).toBeLessThan(0.01);
  });
});
