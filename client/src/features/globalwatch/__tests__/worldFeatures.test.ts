/**
 * World-asset normalizer tests: GeoJSON (the shipped shape) + TopoJSON
 * (delta-decoded, reversed-arc handling) + junk input.
 */
import { describe, expect, it } from 'vitest';
import worldRaw from '@/assets/world-110m.json';
import { normalizeWorld } from '../worldFeatures';

describe('normalizeWorld — GeoJSON (the bundled asset shape)', () => {
  const ring = (lon: number, lat: number) => [[lon, lat], [lon + 1, lat], [lon + 1, lat + 1], [lon, lat]];

  const raw = {
    type: 'FeatureCollection',
    features: [
      { type: 'Feature', geometry: { type: 'Polygon', coordinates: [ring(0, 0)] } },
      { type: 'Feature', geometry: { type: 'MultiPolygon', coordinates: [[ring(2, 2)], [ring(4, 4)]] } },
      {
        type: 'Feature',
        geometry: {
          type: 'GeometryCollection',
          geometries: [{ type: 'Polygon', coordinates: [ring(6, 6)] }],
        },
      },
      { type: 'Feature', geometry: null },
    ],
  };

  it('flattens polygons, multipolygons and geometry collections into rings', () => {
    const shapes = normalizeWorld(raw);
    expect(shapes).toHaveLength(4);
    expect(shapes[0].rings).toHaveLength(1);
    expect(shapes[0].rings[0]).toHaveLength(4);
    // MultiPolygon → one shape per polygon part.
    expect(shapes[1].rings[0][0]).toEqual([2, 2]);
    expect(shapes[2].rings[0][0]).toEqual([4, 4]);
    expect(shapes[3].rings[0][0]).toEqual([6, 6]);
  });

  it('accepts a bare Feature or Geometry as well as a collection', () => {
    expect(normalizeWorld({ type: 'Feature', geometry: { type: 'Polygon', coordinates: [ring(0, 0)] } }))
      .toHaveLength(1);
    expect(normalizeWorld({ type: 'Polygon', coordinates: [ring(0, 0)] })).toHaveLength(1);
  });
});

describe('normalizeWorld — TopoJSON', () => {
  const topo = {
    type: 'Topology',
    transform: { scale: [0.5, 0.5], translate: [10, 20] },
    arcs: [
      [[0, 0], [2, 0], [0, 2], [-2, 0]], // → (10,20) (11,20) (11,21) (10,21)
      [[0, 0], [4, 0]], // → (10,20) (12,20)
    ],
    objects: {
      land: {
        type: 'GeometryCollection',
        geometries: [
          { type: 'Polygon', arcs: [[0]] },
          { type: 'Polygon', arcs: [[~1, 0]] }, // reversed arc 1 stitched to arc 0
        ],
      },
    },
  };

  it('delta-decodes arcs, applies scale/translate and stitches rings', () => {
    const shapes = normalizeWorld(topo);
    expect(shapes).toHaveLength(2);
    expect(shapes[0].rings[0]).toEqual([
      [10, 20], [11, 20], [11, 21], [10, 21],
    ]);
  });

  it('reverses negative arc indices and drops the shared seam point', () => {
    const ring = normalizeWorld(topo)[1].rings[0];
    expect(ring[0]).toEqual([12, 20]); // reversed arc 1, first point
    expect(ring[1]).toEqual([10, 20]); // reversed arc 1, last point
    expect(ring.slice(2)).toEqual([[11, 20], [11, 21], [10, 21]]); // arc 0 without its duplicate seam
  });

  it('passes through untransformed topologies as raw deltas', () => {
    const plain = {
      type: 'Topology',
      arcs: [[[0, 0], [1, 1]]],
      objects: { land: { type: 'Polygon', arcs: [[0]] } },
    };
    expect(normalizeWorld(plain)[0].rings[0]).toEqual([[0, 0], [1, 1]]);
  });
});

describe('normalizeWorld — junk input', () => {
  it('returns [] instead of throwing', () => {
    expect(normalizeWorld(null)).toEqual([]);
    expect(normalizeWorld(undefined)).toEqual([]);
    expect(normalizeWorld(42)).toEqual([]);
    expect(normalizeWorld('land')).toEqual([]);
    expect(normalizeWorld({})).toEqual([]);
    expect(normalizeWorld({ type: 'FeatureCollection', features: 'nope' })).toEqual([]);
  });
});

describe('the bundled world-110m asset', () => {
  it('normalizes into a real landmass (many shapes, thousands of points)', () => {
    const shapes = normalizeWorld(worldRaw);
    expect(shapes.length).toBeGreaterThan(100);
    const points = shapes.reduce((s, shape) => s + shape.rings.reduce((n, r) => n + r.length, 0), 0);
    expect(points).toBeGreaterThan(5_000);
  });

  it('keeps every ring coordinate in [-180, 180] lon / [-90, 90] lat', () => {
    for (const shape of normalizeWorld(worldRaw)) {
      for (const ring of shape.rings) {
        for (const [lon, lat] of ring) {
          expect(Number.isFinite(lon) && Number.isFinite(lat)).toBe(true);
          expect(Math.abs(lon)).toBeLessThanOrEqual(180.001);
          expect(Math.abs(lat)).toBeLessThanOrEqual(90.001);
        }
      }
    }
  });
});
