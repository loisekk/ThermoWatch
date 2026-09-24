/**
 * Normalizes the bundled world asset (`assets/world-110m.json`) into plain
 * lon/lat rings — self-contained (no topojson-client dependency). The shipped
 * asset is a GeoJSON FeatureCollection; the Topology branch keeps the loader
 * working if the asset is ever swapped for TopoJSON.
 */
export interface LandShape {
  rings: [number, number][][];
}

/** Any of: Geometry, Feature, FeatureCollection, Topology, or junk. */
export function normalizeWorld(raw: unknown): LandShape[] {
  if (!raw || typeof raw !== 'object') return [];
  const node = raw as { type?: unknown; objects?: unknown; features?: unknown; geometry?: unknown };
  if (node.type === 'Topology') return fromTopology(node);
  if (node.type === 'FeatureCollection') {
    return asArray(node.features).flatMap((f) => geomToShapes((f as { geometry?: unknown })?.geometry));
  }
  if (node.type === 'Feature') return geomToShapes(node.geometry);
  return geomToShapes(raw);
}

function asArray(v: unknown): unknown[] {
  return Array.isArray(v) ? v : [];
}

function geomToShapes(g: unknown): LandShape[] {
  if (!g || typeof g !== 'object') return [];
  const geom = g as { type?: unknown; coordinates?: unknown; geometries?: unknown };
  if (geom.type === 'Polygon') return [{ rings: (geom.coordinates ?? []) as [number, number][][] }];
  if (geom.type === 'MultiPolygon') {
    return asArray(geom.coordinates).map((poly) => ({ rings: poly as [number, number][][] }));
  }
  if (geom.type === 'GeometryCollection') {
    return asArray(geom.geometries).flatMap(geomToShapes);
  }
  return [];
}

interface TopoTransform {
  scale: [number, number];
  translate: [number, number];
}

function fromTopology(topo: { objects?: unknown }): LandShape[] {
  const raw = topo as {
    transform?: TopoTransform;
    arcs?: number[][][];
    objects?: Record<string, unknown>;
  };
  const tx = raw.transform;
  const arcs: [number, number][][] = (raw.arcs ?? []).map((arc) => {
    let x = 0;
    let y = 0;
    return arc.map((d) => {
      x += d[0];
      y += d[1];
      return (tx
        ? [x * tx.scale[0] + tx.translate[0], y * tx.scale[1] + tx.translate[1]]
        : [x, y]) as [number, number];
    });
  });

  const resolveRing = (idx: number[]): [number, number][] => {
    const pts: [number, number][] = [];
    for (const i of idx) {
      const rev = i < 0;
      let seg = rev ? [...arcs[~i]].reverse() : arcs[i];
      if (!seg) continue;
      if (pts.length > 0) seg = seg.slice(1); // shared seam point
      pts.push(...seg);
    }
    return pts;
  };

  const fromGeom = (g: unknown): LandShape[] => {
    if (!g || typeof g !== 'object') return [];
    const geom = g as { type?: unknown; arcs?: unknown; geometries?: unknown };
    if (geom.type === 'Polygon') {
      return [{ rings: asArray(geom.arcs).map((ring) => resolveRing(ring as number[])) }];
    }
    if (geom.type === 'MultiPolygon') {
      return asArray(geom.arcs).map((poly) => ({
        rings: asArray(poly).map((ring) => resolveRing(ring as number[])),
      }));
    }
    if (geom.type === 'GeometryCollection') {
      return asArray(geom.geometries).flatMap(fromGeom);
    }
    return [];
  };

  return Object.values(raw.objects ?? {}).flatMap(fromGeom);
}
