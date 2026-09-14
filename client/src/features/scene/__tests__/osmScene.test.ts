import { expect, it } from 'vitest';
import * as THREE from 'three';
import { buildOsmScene, closedCCW, enuUnits, ensureCCWShapeSpace, nearestBuildingM,
  pickBuilding, pointInPolygon, roadRibbon, scatterInPolygon, shapeFromRing, signedArea2,
  type OsmBuilding, type SceneContext } from '../osmScene';

const O = { lat: 22.8, lon: 86.2 };

/** Shoelace in shape space (x, y). */
function shoelaceXY(pts: { x: number; y: number }[]): number {
  let s = 0;
  for (let i = 0; i < pts.length; i++) {
    const a = pts[i], b = pts[(i + 1) % pts.length];
    s += a.x * b.y - b.x * a.y;
  }
  return s / 2;
}

it('ensureCCWShapeSpace: CW (x,z) square -> positive shoelace in (x,y); mapping is (x, -z)', () => {
  // CW in (x,z) as written (signedArea2 < 0): west->south->east->north
  const cw = [{ x: 0, z: 0 }, { x: 0, z: 2 }, { x: 2, z: 2 }, { x: 2, z: 0 }];
  expect(signedArea2(cw)).toBeLessThan(0);
  const m = ensureCCWShapeSpace(cw);
  expect(shoelaceXY(m)).toBeGreaterThan(0);          // corrected in SHAPE space
  expect(m.every((p, i) => p.x === cw[i].x && p.y === -cw[i].z)).toBe(true); // (x, -z) mapping
  // CCW (x,z) input stays positive after the (x,-z) flip correction
  const ccw = ensureCCWShapeSpace(cw.slice().reverse());
  expect(shoelaceXY(ccw)).toBeGreaterThan(0);
});

it('extruded footprints: top-cap normals point +Y after the rotateX(-PI/2) mount (T9.0 GL fix)', () => {
  const ring = closedCCW([{ x: 0, z: 0 }, { x: 4, z: 0 }, { x: 4, z: -4 }, { x: 0, z: -4 }]);
  const geo = new THREE.ExtrudeGeometry(shapeFromRing(ring), { depth: 1, bevelEnabled: false });
  geo.rotateX(-Math.PI / 2);
  geo.computeVertexNormals();
  const pos = geo.getAttribute('position') as THREE.BufferAttribute;
  const nor = geo.getAttribute('normal') as THREE.BufferAttribute;
  let maxY = -Infinity;
  for (let i = 0; i < pos.count; i++) maxY = Math.max(maxY, pos.getY(i));
  let topTris = 0, upTris = 0;
  for (let t = 0; t < pos.count; t += 3) {
    const ys = [0, 1, 2].map((k) => pos.getY(t + k));
    if (ys.every((y) => Math.abs(y - maxY) < 1e-6)) {
      topTris++;
      const ny = (nor.getY(t) + nor.getY(t + 1) + nor.getY(t + 2)) / 3;
      if (ny > 0.5) upTris++;
    }
  }
  expect(topTris).toBeGreaterThan(0);
  expect(upTris).toBe(topTris); // every roof triangle faces UP -> visible with FrontSide
});

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

it('pointInPolygon: inside / outside / hole-safe even-odd rule', () => {
  const sq = [{ x: 0, z: 0 }, { x: 4, z: 0 }, { x: 4, z: 4 }, { x: 0, z: 4 }];
  expect(pointInPolygon(2, 2, sq)).toBe(true);
  expect(pointInPolygon(5, 5, sq)).toBe(false);
  expect(pointInPolygon(-1, 2, sq)).toBe(false);
});

it('scatterInPolygon: density math, deterministic seed, cap honoured, all points inside', () => {
  const sq = [{ x: 0, z: 0 }, { x: 4, z: 0 }, { x: 4, z: -4 }, { x: 0, z: -4 }]; // 400×400 m
  const a = scatterInPolygon(sq, 220, 7);            // 0.16 km² × 220 ≈ 35
  const b = scatterInPolygon(sq, 220, 7);
  expect(a.length).toBeGreaterThan(20);
  expect(a).toEqual(b);                              // same seed → same points
  expect(a.every((p) => pointInPolygon(p.x, p.z, sq))).toBe(true);
  expect(scatterInPolygon(sq, 1e9, 7).length).toBeLessThanOrEqual(300); // cap
});

it('pickBuilding: PIP hit at centre, ≤25 m nearest-miss, null far away', () => {
  const b = squareBuilding(O); // ±200 m square
  const inside = pickBuilding(0, 0, O, [b])!;
  expect(inside.id).toBe(77);
  expect(inside.m).toBe(0);
  expect(inside.height_m).toBe(8);
  // 0.2 units (20 m) east of the east edge → within the 25 m outline tolerance
  const near = pickBuilding(2.2, 0, O, [b])!;
  expect(near.id).toBe(77);
  expect(near.m).toBeGreaterThan(0);
  expect(near.m).toBeLessThanOrEqual(25);
  expect(pickBuilding(5, 5, O, [b])).toBeNull();
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