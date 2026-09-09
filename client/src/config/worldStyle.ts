import type { StyleSpecification } from 'maplibre-gl';
import { countriesWithIds } from '@/lib/geo/countryIndex';
import { makeGraticule } from '@/lib/geo/graticule';

export const OCEAN = '#0d1117';
export const LAND = '#1b2127';
export const BORDER = '#2a3644';

/** Choropleth ramp driven by feature-state 'count' (fire density per country). */
export const HEAT_RAMP = [
  'interpolate', ['linear'], ['coalesce', ['feature-state', 'count'], 0],
  0, LAND, 1, '#232a31', 10, '#33302a', 30, '#46301f', 80, '#5a3418',
] as const;

/** Fully synchronous, fully bundled vector world style. Zero external resources. */
export function makeWorldVectorStyle(): StyleSpecification {
  return {
    version: 8,
    sources: {
      countries: { type: 'geojson', data: countriesWithIds() as never },
      graticule: { type: 'geojson', data: makeGraticule() as never },
    },
    layers: [
      { id: 'ocean', type: 'background', paint: { 'background-color': OCEAN } },
      { id: 'countries-fill', type: 'fill', source: 'countries', paint: { 'fill-color': LAND } },
      { id: 'countries-line', type: 'line', source: 'countries', paint: { 'line-color': BORDER, 'line-width': 0.7 } },
      {
        id: 'graticule', type: 'line', source: 'graticule',
        paint: {
          'line-color': '#2A3644',
          'line-width': ['match', ['get', 'major'], 1, 1.1, 0.5],
          'line-opacity': ['match', ['get', 'major'], 1, 0.5, 0.25],
        },
      },
    ],
  };
}
