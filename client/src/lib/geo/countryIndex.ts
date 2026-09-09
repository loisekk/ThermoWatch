import type { FeatureCollection, Geometry, Position } from 'geojson';
import world from '@/assets/world-110m.json';
import type { FireEvent } from '@/types/domain';

export interface CountryBox {
  id: number;
  name: string;
  minLon: number; minLat: number; maxLon: number; maxLat: number;
  area: number;
  centroid: [number, number];
}

const fc = world as unknown as FeatureCollection<Geometry, Record<string, unknown>>;

function* coordinatesOf(node: unknown): Generator<Position> {
  if (Array.isArray(node)) {
    if (typeof node[0] === 'number') yield node as Position;
    else for (const child of node) yield* coordinatesOf(child);
  }
}

export const COUNTRY_BOXES: CountryBox[] = fc.features.map((f, i) => {
  const box: [number, number, number, number] = [180, 90, -180, -90];
  for (const c of coordinatesOf((f.geometry as unknown as { coordinates: Position[] }).coordinates)) {
    if (c[0] < box[0]) box[0] = c[0];
    if (c[1] < box[1]) box[1] = c[1];
    if (c[0] > box[2]) box[2] = c[0];
    if (c[1] > box[3]) box[3] = c[1];
  }
  const [minLon, minLat, maxLon, maxLat] = box;
  return {
    id: i,
    name: String(f.properties?.NAME ?? f.properties?.ADMIN ?? `region-${i}`),
    minLon, minLat, maxLon, maxLat,
    area: (maxLon - minLon) * (maxLat - minLat),
    centroid: [(minLon + maxLon) / 2, (minLat + maxLat) / 2],
  };
});

/** Approximate per-country density via bbox join (documented approximation). */
export function countryCounts(events: FireEvent[]): Map<number, number> {
  const out = new Map<number, number>();
  for (const e of events) {
    for (const b of COUNTRY_BOXES) {
      if (e.lon >= b.minLon && e.lon <= b.maxLon && e.lat >= b.minLat && e.lat <= b.maxLat) {
        out.set(b.id, (out.get(b.id) ?? 0) + 1);
        break;
      }
    }
  }
  return out;
}

export const COUNTRY_LABELS = COUNTRY_BOXES
  .filter((b) => b.area > 60 && b.name !== 'Antarctica')
  .sort((a, b) => b.area - a.area)
  .slice(0, 26);

/** Same geometry as the style source, with stable numeric ids for feature-state. */
export function countriesWithIds(): FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: fc.features.map((f, i) => ({ ...f, id: i })),
  } as FeatureCollection;
}
