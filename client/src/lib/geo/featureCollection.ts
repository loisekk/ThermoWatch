import type { FeatureCollection, Point } from 'geojson';
import type { Facility, FireEvent } from '@/types/domain';

/** Events → GeoJSON for MapLibre circle layers (primitive props only). */
export function firesToFeatureCollection(events: FireEvent[]): FeatureCollection<Point> {
  return {
    type: 'FeatureCollection',
    features: events.map((e) => ({
      type: 'Feature',
      id: e.id,
      geometry: { type: 'Point', coordinates: [e.lon, e.lat] },
      properties: {
        eid: e.id,
        cls: e.classification.primary,
        frp: e.frp,
        risk: e.risk.score,
        pers: e.persistence.regime === 'persistent' ? 1 : 0,
      },
    })),
  };
}

export function facilitiesToFeatureCollection(facilities: Facility[]): FeatureCollection<Point> {
  return {
    type: 'FeatureCollection',
    features: facilities.map((f) => ({
      type: 'Feature',
      id: f.id,
      geometry: { type: 'Point', coordinates: [f.lon, f.lat] },
      properties: { fid: f.id, name: f.name, subtype: f.subtype, hazard: f.hazard },
    })),
  };
}
