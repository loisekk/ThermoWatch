import { expect, it } from 'vitest';
import { capByFrp, clusterEllipse, hotspotColor, hotspotRadius, replayWindow,
  toEnu, type Detection, type Enu } from '../sceneData';

const O = { lat: 22.8, lon: 86.2 };

it('ENU: 0.01 deg north ~= 1113 m, east scaled by mid-latitude cosine', () => {
  const p = toEnu(O.lat, O.lon, O.lat + 0.01, O.lon);
  expect(p.n).toBeCloseTo(1113.2, 0);
  expect(p.e).toBeCloseTo(0, 3);
  const e = toEnu(O.lat, O.lon, O.lat, O.lon + 0.01);
  expect(e.e).toBeGreaterThan(1000);
  expect(e.n).toBeCloseTo(0, 3);
});

it('ellipse recovers axis-aligned spread (2 sigma)', () => {
  const pts: Enu[] = Array.from({ length: 40 }, (_, i) => ({
    e: (i % 2 ? 1 : -1) * 100, n: (i % 4 < 2 ? 1 : -1) * 20,
  }));
  const el = clusterEllipse(pts)!;
  expect(el.a).toBeGreaterThan(el.b);
  expect(Math.abs(el.rot)).toBeLessThan(0.01);
  // ±100 m east spread → 2σ ≈ 200 m (fixture pattern gives ~202.5)
  expect(el.a).toBeGreaterThan(190);
  expect(el.a).toBeLessThan(210);
});

it('ellipse is null below 3 points', () => {
  expect(clusterEllipse([{ e: 0, n: 0 }, { e: 1, n: 1 }])).toBeNull();
});

it('radius monotonic + clamped; color thresholds', () => {
  expect(hotspotRadius(0)).toBe(0.6);
  expect(hotspotRadius(10000)).toBe(4);
  expect(hotspotRadius(90)).toBeGreaterThan(hotspotRadius(10));
  expect(hotspotColor(320)).toBe('#FFB800');
  expect(hotspotColor(400)).toBe('#FF6B35');
  expect(hotspotColor(520)).toBe('#FF4444');
});

it('cap by FRP keeps the strongest 200', () => {
  const d = (i: number): Detection => ({
    lat: 0, lon: 0, frp_mw: i, brightness_k: 300,
    acq_at: new Date(Date.UTC(2026, 8, 1 + (i % 28))).toISOString(),
  });
  const many = Array.from({ length: 250 }, (_, i) => d(i));
  const capped = capByFrp(many);
  expect(capped).toHaveLength(200);
  expect(Math.min(...capped.map((x) => x.frp_mw))).toBe(50); // 250-200 lowest dropped
});

it('replay window spans acquisition times', () => {
  const many = Array.from({ length: 40 }, (_, i) => ({
    lat: 0, lon: 0, frp_mw: 1, brightness_k: 300,
    acq_at: new Date(Date.UTC(2026, 8, 1 + i)).toISOString(),
  }));
  const w = replayWindow(many);
  expect(w.toMs).toBeGreaterThan(w.fromMs);
  expect(w.toMs - w.fromMs).toBeCloseTo(39 * 86_400_000, 0);
});
