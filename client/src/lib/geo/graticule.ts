import type { FeatureCollection, LineString } from 'geojson';

/** Procedural 15° graticule (equator / prime meridian flagged major). Zero network. */
export function makeGraticule(stepDeg = 15): FeatureCollection<LineString> {
  const features: FeatureCollection<LineString>['features'] = [];
  for (let lon = -180; lon <= 180; lon += stepDeg) {
    const coords: [number, number][] = [];
    for (let lat = -60; lat <= 85; lat += 5) coords.push([lon, lat]);
    features.push({ type: 'Feature', properties: { major: lon === 0 ? 1 : 0 }, geometry: { type: 'LineString', coordinates: coords } });
  }
  for (let lat = -60; lat <= 85; lat += stepDeg) {
    const coords: [number, number][] = [];
    for (let lon = -180; lon <= 180; lon += 5) coords.push([lon, lat]);
    features.push({ type: 'Feature', properties: { major: lat === 0 ? 1 : 0 }, geometry: { type: 'LineString', coordinates: coords } });
  }
  return { type: 'FeatureCollection', features };
}
