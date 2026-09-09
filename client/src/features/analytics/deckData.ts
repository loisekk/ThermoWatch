/** Pure data-prep for the deck.gl analytics layers (unit-testable, no WebGL). */
import type { Facility, FireEvent } from '@/types/domain';

export const CLASS_COLORS: Record<string, [number, number, number]> = {
  industrial: [255, 107, 53],
  persistent: [255, 184, 0],
  wildfire: [255, 68, 68],
  agricultural: [143, 209, 79],
};

/** Extrusion height (m) by NBC 2016 hazard class. */
export const HAZARD_HEIGHTS: Record<string, number> = {
  'G-III': 2500,
  'G-II': 1500,
  'G-I': 800,
};

export const SUBTYPE_COLORS: Record<string, [number, number, number]> = {
  refinery: [255, 107, 53],
  steel: [125, 141, 161],
  gas_flare: [255, 184, 0],
  cement: [180, 180, 180],
  smelter: [200, 150, 100],
  chemical: [150, 200, 150],
  power_plant: [100, 150, 200],
};

export interface FacilityFootprint {
  id: string;
  hazard: string;
  subtype: string;
  polygon: [number, number][];
}

/** ~400 m square footprint around each facility point (closed ring). */
export function buildFacilityFootprints(facilities: Facility[]): FacilityFootprint[] {
  const delta = 0.0036; // ≈400 m in latitude
  return facilities.map((f) => ({
    id: f.id,
    hazard: f.hazard,
    subtype: f.subtype,
    polygon: [
      [f.lon - delta, f.lat - delta],
      [f.lon + delta, f.lat - delta],
      [f.lon + delta, f.lat + delta],
      [f.lon - delta, f.lat + delta],
      [f.lon - delta, f.lat - delta], // closed
    ],
  }));
}

export interface SpreadRing {
  id: string;
  polygon: [number, number][];
  hours: number;
  risk: string;
}

/** Anisotropy-free preview rings for high/critical-risk events (6/12/24 h). */
export function buildSpreadRings(events: FireEvent[], hours: readonly number[] = [6, 12, 24]): SpreadRing[] {
  const hot = events.filter((e) => e.risk.level === 'high' || e.risk.level === 'critical');
  return hot.flatMap((e) => {
    const baseRadius = 0.5 + e.frp / 200;
    return hours.map((h) => ({
      id: `${e.id}-${h}h`,
      polygon: generateCircle(e.lon, e.lat, baseRadius * h),
      hours: h,
      risk: e.risk.level,
    }));
  });
}

/** Isotropic circle polygon (closed, segments+1 points). */
export function generateCircle(lon: number, lat: number, radiusKm: number, segments = 32): [number, number][] {
  const points: [number, number][] = [];
  for (let i = 0; i <= segments; i++) {
    const angle = (i / segments) * 2 * Math.PI;
    const dlon = (radiusKm * Math.cos(angle)) / (111 * Math.cos((lat * Math.PI) / 180));
    const dlat = (radiusKm * Math.sin(angle)) / 111;
    points.push([lon + dlon, lat + dlat]);
  }
  return points;
}

/** Time-window filter used by every analytics layer. */
export function filterByTimeRange(events: FireEvent[], startMs: number, endMs: number): FireEvent[] {
  return events.filter((e) => e.detectedAt >= startMs && e.detectedAt <= endMs);
}
