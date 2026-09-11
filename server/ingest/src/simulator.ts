/** Deterministic fallback feed — identical contract to FIRMS raw rows. */
import type { FirmsRaw } from './firmsClient';

const FAC = [
  [22.47, 70.06], [30.21, 74.94], [22.03, 88.06], [22.8, 86.2], [23.66, 85.96],
  [16.95, 82.25], [20.37, 72.9], [21.72, 72.57], [24.6, 80.83], [20.85, 85.1],
] as const;
const WLD = [[30.1, 79.5], [22.3, 79.8], [25.6, 93.2]] as const;
const j = (s: number) => (Math.random() - 0.5) * 2 * s;

export function simBatch(): FirmsRaw[] {
  const now = Date.now() - 3 * 3_600_000; // honest FIRMS latency in sim too
  const out: FirmsRaw[] = [];
  for (const [la, lo] of FAC) {
    if (Math.random() < 0.5)
      out.push(row(la + j(0.002), lo + j(0.002), 60 + Math.random() * 190, now));
  }
  const n = Math.floor(Math.random() * 4);
  for (let i = 0; i < n; i++) {
    const w = WLD[Math.floor(Math.random() * WLD.length)];
    out.push(row(w[0] + j(1.1), w[1] + j(1.1), 20 + Math.random() * 160, now));
  }
  return out;
}

const row = (latitude: number, longitude: number, frp: number, ts: number): FirmsRaw & { _ts: number } => ({
  latitude, longitude, frp: Math.round(frp), bright_ti4: Math.round(315 + Math.random() * 120),
  confidence: 55 + Math.floor(Math.random() * 45),
  satellite: ['VIIRS-SNPP', 'VIIRS-NOAA20', 'MODIS'][Math.floor(Math.random() * 3)],
  daynight: (Math.random() > 0.5 ? 'D' : 'N') as 'D' | 'N',
  acq_date: '', acq_time: '', _ts: ts,
});
