import { expect, it } from 'vitest';
import { buildOsmScene, closedCCW, enuUnits, nearestBuildingM, roadRibbon,
  signedArea2, type OsmBuilding, type SceneContext } from '../osmScene';

const O = { lat: 22.8, lon: 86.2 };

it('enuUnits: north maps to negative z, east to +x (~11.13 units / 0.01 deg)', () => {
  const n = enuUnits(O, O.lat + 0.01, O.lon);
  expect(n.x).toBeCloseTo(0, 3);
  expect(n.z).toBeCloseTo(-11.132, 0);
  const e = enuUnits(O, O.lat, O.lon + 0.01);
  expect(e.x).toBeGreaterThan(10);
  expect(e.z).toBeCloseTo(0, 3);
});

it('closedCCW closes open rings and forces CCW orientation', () => {
  const open = [{ x: 0, z: 0 }, { x: 1, z: 0 }, { x: 1, z: 1 }];
  const c = closedCCW(open);
  expect(c[0].x).toBe(c[c.length - 1].x);
  expect(c[0].z).toBe(c[c.length - 1].z);
  expect(signedArea2(c)).toBeGreaterThan(0); // CCW
  const rev = closedCCW(c.slice().reverse().slice(0, -1));
  expect(signedArea2(rev)).toBeGreaterThan(0);
  // already-closed ring stays closed (no duplicate-first-point duplication)
  expect(closedCCW(c)).toHaveLength(c.length);
});

it('roadRibbon: 2n verts, 2(n-1) tris, perpendicular offset', () => {
  const pts = [{ x: 0, z: 0 }, { x: 1, z: 0 }, { x: 2, z: 0 }];
  const { verts, tris } = roadRibbon(pts, 0.5);
  expect(tris).toBe(4);
  expect(verts.length / 2).toBe(6); // 2n = 6 vertices
  // first point: offsets (+0, +0.5) and (+0, -0.5)
  expect(verts[0]).toBe(0); expect(verts[1]).toBeCloseTo(0.5);
  expect(verts[2]).toBe(0); expect(verts[3]).toBeCloseTo(-0.5);
});

function squareBuilding(origin: { lat: number; lon: number }): OsmBuilding {
  // 4x4-unit square centred on the origin: corners at ±200 m east/north.
  // East degrees are scaled by the mid-latitude cosine (ENU equirectangular).
  const dLat = 200 / 111_320;
  const dLon = 200 / (111_320 * Math.cos((origin.lat * Math.PI) / 180));
  const corners: [number, number][] = [
    [origin.lat - dLat, origin.lon - dLon], [origin.lat - dLat, origin.lon + dLon],
    [origin.lat + dLat, origin.lon + dLon], [origin.lat + dLat, origin.lon - dLon],
  ];
  return { id: 77, outline: corners, height_m: 8, height_source: 'tag:height', kind: 'industrial' };
}

it('nearestBuildingM: centre-to-edge of a 4-unit square = half side = 200 m', () => {
  const b = squareBuilding(O);
  const hit = nearestBuildingM(0, 0, O, [b])!;
  expect(hit.id).toBe(77);
  expect(hit.m).toBeGreaterThan(190);
  expect(hit.m).toBeLessThan(210);
  // outside a corner: distance > half side
  const far = nearestBuildingM(5, 5, O, [b])!;
  expect(far.m).toBeGreaterThan(200);
});

it('nearestBuildingM returns null for empty lists', () => {
  expect(nearestBuildingM(0, 0, O, [])).toBeNull();
});

it('buildOsmScene: stats + dispose empties the group', () => {
  const ctx: SceneContext = {
    source: 'osm-overpass', snapshot_at: 'x', radius_m: 1200,
    center: { lat: O.lat, lon: O.lon }, attribution: 'c',
    counts: { buildings: 1, trees: 2, roads: 1, wood: 0, landuse: 0, water: 1 },
    buildings: [squareBuilding(O)],
    trees: [{ lat: O.lat + 0.0004, lon: O.lon + 0.0004, crown_m: 4 },
            { lat: O.lat - 0.0004, lon: O.lon - 0.0004, crown_m: 6 }],
    roads: [{ points: [[O.lat, O.lon - 0.01], [O.lat, O.lon + 0.01]], cls: 'secondary' }],
    wood: [], landuse: [],
    water: [{ outline: [[O.lat - 0.002, O.lon - 0.002], [O.lat - 0.002, O.lon + 0.002],
                        [O.lat + 0.002, O.lon + 0.002], [O.lat + 0.002, O.lon - 0.002]] }],
  };
  const { group, stats, dispose } = buildOsmScene(O, ctx);
  expect(stats.buildings).toBe(1);
  expect(stats.trees).toBe(2);
  expect(group.children.length).toBeGreaterThan(0);
  dispose();
  expect(group.children.length).toBe(0);
});