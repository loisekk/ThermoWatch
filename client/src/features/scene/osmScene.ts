/** Live OSM scene context — real-world surroundings for the incident scene (T8).
 *
 *  Doctrine: "real" = fetched from the world, never invented. OSM data comes from
 *  the server Overpass proxy (/api/v1/scene/context, 6 h cache). Sparse stays
 *  sparse; `source === "unavailable"` renders the legacy SCHEMATIC massing with
 *  an honest label. No filler buildings, ever.
 *
 *  Pure helpers are unit-testable without three.js; builders are dispose-safe
 *  (WebGL context-loss remounts rely on it). 1 scene unit = 100 m.
 */
import * as THREE from 'three';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';
import { mulberry32 } from '@/lib/random/mulberry';
import { CARTO, LABEL_CAP } from './cartography';
import { toEnu } from './sceneData';

export type OsmBuildingKind = 'industrial' | 'commercial' | 'residential' | 'generic';
export type OsmHeightSource = 'tag:height' | 'tag:levels' | 'estimated';

export interface OsmBuilding {
  id: number;
  outline: [number, number][]; // [lat, lon] ring (closed by Overpass)
  height_m: number;
  height_source: OsmHeightSource;
  kind: OsmBuildingKind;
  name?: string | null;
}
export interface OsmTree { lat: number; lon: number; crown_m: number }
export interface OsmRoad { points: [number, number][]; cls: string; name?: string | null }
export interface OsmPoly { outline: [number, number][]; name?: string | null }
export interface OsmLanduse extends OsmPoly { kind: string }

export interface SceneContext {
  source: 'osm-overpass' | 'unavailable';
  snapshot_at: string;
  radius_m: number;
  center: { lat: number; lon: number };
  attribution: string;
  counts: Partial<Record<OsmCountsKey, number>>;
  buildings: OsmBuilding[];
  trees: OsmTree[];
  roads: OsmRoad[];
  wood: OsmPoly[];
  landuse: OsmLanduse[];
  water: OsmPoly[];
}
export type OsmCountsKey = 'buildings' | 'trees' | 'roads' | 'wood' | 'landuse' | 'water';

export const M_TO_U = 1 / 100; // 1 scene unit = 100 m

/** Road ribbon half-widths by OSM class (metres). */
export const ROAD_HALF_W: Record<string, number> = {
  motorway: 7, trunk: 6, primary: 5, secondary: 4,
  tertiary: 3, residential: 2.5, unclassified: 2, service: 1.5,
};

export interface EnuU { x: number; z: number } // three-space scene units (z = -north)

/** Event-origin local ENU in scene units (north maps to -z, matching ThreeScene). */
export function enuUnits(origin: { lat: number; lon: number },
                         lat: number, lon: number): EnuU {
  const enu = toEnu(origin.lat, origin.lon, lat, lon);
  return { x: enu.e * M_TO_U, z: -enu.n * M_TO_U };
}

/** Signed area of a ring (positive = CCW in x/z scene space). */
export function signedArea2(pts: EnuU[]): number {
  let s = 0;
  for (let i = 0; i < pts.length; i++) {
    const a = pts[i];
    const b = pts[(i + 1) % pts.length];
    s += a.x * b.z - b.x * a.z;
  }
  return s / 2;
}

/** Close the ring (first point duplicated at the end) and force CCW — Shape
 *  extrusion needs a well-behaved ring for consistent normals/merging. */
export function closedCCW(pts: EnuU[]): EnuU[] {
  if (pts.length < 3) return pts;
  const ring = pts[0].x === pts[pts.length - 1].x && pts[0].z === pts[pts.length - 1].z
    ? pts.slice(0, -1) : pts.slice();
  if (signedArea2(ring) < 0) ring.reverse();
  return [...ring, ring[0]];
}

/** Quad-strip ribbon for a road polyline (perpendicular offset by halfW units).
 *  Returns 2n vertices (two per input point) — 2*(n-1) triangles. */
export function roadRibbon(points: EnuU[], halfW: number): { verts: Float32Array; tris: number } {
  if (points.length < 2) return { verts: new Float32Array(0), tris: 0 };
  const verts = new Float32Array(points.length * 2 * 2);
  for (let i = 0; i < points.length; i++) {
    const p0 = points[Math.max(0, i - 1)];
    const p1 = points[Math.min(points.length - 1, i + 1)];
    const dx = p1.x - p0.x;
    const dz = p1.z - p0.z;
    const len = Math.hypot(dx, dz) || 1;
    const nx = (-dz / len) * halfW;
    const nz = (dx / len) * halfW;
    const p = points[i];
    verts.set([p.x + nx, p.z + nz], i * 4);
    verts.set([p.x - nx, p.z - nz], i * 4 + 2);
  }
  return { verts, tris: (points.length - 1) * 2 };
}

/** Nearest OSM building in scene units from (px, pz): point→segment distance,
 *  returned in metres (units × 100). Pure — used by the three scene, the canvas
 *  parity path and the drawer provenance callout. */
export function nearestBuildingM(px: number, pz: number, origin: { lat: number; lon: number },
                                 buildings: OsmBuilding[]):
  { m: number; id: number; kind: OsmBuildingKind } | null {
  let best: { m: number; id: number; kind: OsmBuildingKind } | null = null;
  for (const b of buildings) {
    const ring = b.outline.map(([la, lo]) => enuUnits(origin, la, lo));
    for (let i = 0; i < ring.length - 1; i++) {
      const a = ring[i];
      const c = ring[i + 1];
      const abx = c.x - a.x;
      const abz = c.z - a.z;
      const t = Math.max(0, Math.min(1, ((px - a.x) * abx + (pz - a.z) * abz)
        / ((abx * abx + abz * abz) || 1)));
      const dU = Math.hypot(px - (a.x + t * abx), pz - (a.z + t * abz));
      if (!best || dU < best.m * M_TO_U) best = { m: dU * 100, id: b.id, kind: b.kind };
    }
  }
  return best;
}

/** T9 hover provenance — pure point-in-polygon (even-odd rule, scene units). */
export function pointInPolygon(px: number, pz: number, ring: EnuU[]): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const xi = ring[i].x, zi = ring[i].z, xj = ring[j].x, zj = ring[j].z;
    if ((zi > pz) !== (zj > pz) && px < ((xj - xi) * (pz - zi)) / (zj - zi) + xi) inside = !inside;
  }
  return inside;
}

/** |area| of a ring in m² (1 scene unit = 100 m → units² × 10⁴). */
export function shoelaceAreaM2(ring: EnuU[]): number {
  let s = 0;
  for (let i = 0; i < ring.length - 1; i++) s += ring[i].x * ring[i + 1].z - ring[i + 1].x * ring[i].z;
  return (Math.abs(s) / 2) * 100 * 100;
}

/** Deterministic rejection sampling inside a polygon (bbox + PIP).
 *  ILLUSTRATIVE density for canopy — disclosed in the legend, never a fuel model. */
export function scatterInPolygon(ring: EnuU[], perKm2: number, seed: number, cap = 300): EnuU[] {
  if (ring.length < 3) return [];
  const xs = ring.map((p) => p.x), zs = ring.map((p) => p.z);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minZ = Math.min(...zs), maxZ = Math.max(...zs);
  const n = Math.min(cap, Math.round((shoelaceAreaM2(ring) / 1e6) * perKm2));
  const rnd = mulberry32(seed);
  const out: EnuU[] = [];
  let guard = n * 20;
  while (out.length < n && guard-- > 0) {
    const p = { x: minX + rnd() * (maxX - minX), z: minZ + rnd() * (maxZ - minZ) };
    if (pointInPolygon(p.x, p.z, ring)) out.push(p);
  }
  return out;
}

export interface BuildingPick {
  id: OsmBuilding['id'];
  kind: OsmBuildingKind | string;
  height_m: number;
  height_source: string;
  name?: string | null;
  m: number; // 0 = inside the footprint, else outline distance in metres
}

/** Hover pick by pure math (no pick meshes — merged geometry stays cheap):
 *  PIP over footprint rings first, else nearest outline ≤ 25 m. */
export function pickBuilding(px: number, pz: number, origin: { lat: number; lon: number },
                             buildings: OsmBuilding[]): BuildingPick | null {
  for (const b of buildings) {
    const ring = b.outline.map(([la, lo]) => enuUnits(origin, la, lo));
    if (pointInPolygon(px, pz, ring)) {
      return { id: b.id, kind: b.kind, height_m: b.height_m,
               height_source: b.height_source, name: b.name ?? undefined, m: 0 };
    }
  }
  const nb = nearestBuildingM(px, pz, origin, buildings);
  if (nb && nb.m <= 25) {
    const b = buildings.find((x) => x.id === nb.id);
    return { id: nb.id, kind: nb.kind, height_m: b?.height_m ?? 0,
             height_source: b?.height_source ?? '', name: b?.name ?? undefined, m: nb.m };
  }
  return null;
}

/** Lift every vertex of a flat geometry onto plane y (ground patches). */
function flatPoly(geo: THREE.BufferGeometry, y: number): THREE.BufferGeometry {
  const pos = geo.getAttribute('position') as THREE.BufferAttribute;
  for (let i = 0; i < pos.count; i++) pos.setY(i, y);
  return geo;
}

export interface OsmSceneResult {
  group: THREE.Group;
  stats: { buildings: number; trees: number; roads: number; polys: number; meshes: number };
  dispose: () => void;
}

/** Ring (scene units, x/z, north = −z) → THREE.Shape in SHAPE space (x, −z).
 *  Winding is corrected IN SHAPE SPACE — the frame ExtrudeGeometry/ShapeGeometry
 *  actually consume after the rotateX(-π/2) mount (T9.0 hotfix: buildings were
 *  backface-culled invisible in WebGL because winding was corrected in (x,z),
 *  then the (x,−z) sign flip reversed orientation again). Exported for tests. */
export function shapeFromRing(ring: EnuU[]): THREE.Shape {
  const m = ensureCCWShapeSpace(ring);
  const s = new THREE.Shape();
  m.forEach((p, i) => (i ? s.lineTo(p.x, p.y) : s.moveTo(p.x, p.y)));
  s.closePath();
  return s;
}

/** Winding corrected in SHAPE space (x, y = −z). Positive output shoelace
 *  guarantees ExtrudeGeometry top caps face +Y (visible from above, FrontSide). */
export function ensureCCWShapeSpace(pts: EnuU[]): { x: number; y: number }[] {
  const m = pts.map((p) => ({ x: p.x, y: -p.z }));
  let s = 0;
  for (let i = 0; i < m.length - 1; i++) s += m[i].x * m[i + 1].y - m[i + 1].x * m[i].y;
  return s < 0 ? m.reverse() : m;
}

/** REAL OSM footprint rings extruded to true/estimated height, merged per kind.
 *  T9: fill (CARTO palette) + roof caps (top face, albedo ×1.18) + merged
 *  EdgesGeometry outlines — reads as solid massing with crisp tops. */
function buildingsGroup(origin: { lat: number; lon: number },
                        buildings: OsmBuilding[]): { group: THREE.Group; dispose: () => void } {
  const group = new THREE.Group();
  const byKind: Record<OsmBuildingKind, THREE.BufferGeometry[]> = {
    industrial: [], commercial: [], residential: [], generic: [],
  };
  const roofsByKind: Record<OsmBuildingKind, THREE.BufferGeometry[]> = {
    industrial: [], commercial: [], residential: [], generic: [],
  };
  const edges: THREE.BufferGeometry[] = [];
  for (const b of buildings) {
    const ring = closedCCW(b.outline.map(([la, lo]) => enuUnits(origin, la, lo)));
    if (ring.length < 4) continue;
    const depth = Math.max(0.15, b.height_m * M_TO_U);
    const geo = new THREE.ExtrudeGeometry(shapeFromRing(ring), {
      depth, bevelEnabled: false,
    });
    geo.rotateX(-Math.PI / 2); // extrude +Z -> up +Y; shape (x, y=-z) -> world (x, ·, z)
    byKind[b.kind].push(geo);
    const roof = new THREE.ShapeGeometry(shapeFromRing(ring));
    roof.rotateX(-Math.PI / 2);
    flatPoly(roof, depth);
    roofsByKind[b.kind].push(roof);
    edges.push(new THREE.EdgesGeometry(geo, 40));
  }
  const disposeList: (THREE.Material | THREE.BufferGeometry)[] = [];
  const addMerged = (geos: THREE.BufferGeometry[], mat: THREE.Material, shadows: boolean): void => {
    if (!geos.length) return;
    const merged = mergeGeometries(geos, false);
    geos.forEach((g) => g.dispose());
    if (!merged) return;
    disposeList.push(merged, mat);
    const mesh = new THREE.Mesh(merged, mat);
    mesh.castShadow = shadows;
    mesh.receiveShadow = shadows;
    group.add(mesh);
  };
  for (const kind of Object.keys(byKind) as OsmBuildingKind[]) {
    addMerged(byKind[kind], new THREE.MeshStandardMaterial({
      color: CARTO.building[kind], roughness: 0.78, metalness: 0.12,
    }), true);
    // roof caps: same footprint at y = height, brighter — crisp tops, no floating shells
    addMerged(roofsByKind[kind], new THREE.MeshStandardMaterial({
      color: new THREE.Color(CARTO.building[kind]).multiplyScalar(CARTO.roofBoost),
      roughness: 0.6, metalness: 0.08,
    }), false);
  }
  if (edges.length) {
    const merged = mergeGeometries(edges, false);
    edges.forEach((g) => g.dispose());
    if (merged) {
      const mat = new THREE.LineBasicMaterial({
        color: CARTO.buildingOutline, transparent: true, opacity: 0.55,
      });
      disposeList.push(merged, mat);
      group.add(new THREE.LineSegments(merged, mat));
    }
  }
  return {
    group,
    dispose() {
      disposeList.forEach((d) => d.dispose());
      group.clear();
    },
  };
}

/** Real mapped trees as instanced canopies + trunks (seeded jitter, ±20 %). */
function treesGroup(origin: { lat: number; lon: number },
                    trees: OsmTree[]): { group: THREE.Group; dispose: () => void } {
  const group = new THREE.Group();
  if (!trees.length) return { group, dispose: () => undefined };
  const pick = (i: number) => mulberry32(i)() > 0.5;
  const cones = trees.filter((_, i) => pick(i));
  const blobs = trees.filter((_, i) => !pick(i));
  const make = (list: OsmTree[], geo: THREE.BufferGeometry, mat: THREE.Material): void => {
    if (!list.length) return;
    const im = new THREE.InstancedMesh(geo, mat, list.length);
    const m4 = new THREE.Matrix4();
    list.forEach((t, i) => {
      const r = mulberry32(1000 + i);
      const u = enuUnits(origin, t.lat, t.lon);
      const rU = Math.max(0.015, t.crown_m * M_TO_U) * (0.8 + 0.4 * r());
      const trunkH = rU * 1.5;
      m4.compose(
        new THREE.Vector3(u.x, trunkH + rU * 0.4, u.z),
        new THREE.Quaternion().setFromEuler(new THREE.Euler(0, r() * Math.PI * 2, 0)),
        new THREE.Vector3(rU, rU, rU));
      im.setMatrixAt(i, m4);
    });
    im.instanceMatrix.needsUpdate = true;
    group.add(im);
  };
  const dome = new THREE.ConeGeometry(1, 2.2, 6);
  const blob = new THREE.IcosahedronGeometry(1, 0);
  const trunk = new THREE.CylinderGeometry(0.06, 0.09, 1.6, 5);
  const green = new THREE.MeshStandardMaterial({ color: 0x3a6b35, roughness: 0.85 });
  const dark = new THREE.MeshStandardMaterial({ color: 0x2c5130, roughness: 0.85 });
  const bark = new THREE.MeshStandardMaterial({ color: 0x6b5333, roughness: 1 });
  make(cones, dome, green);
  make(blobs, blob, dark);
  make(trees.map((t) => ({ ...t })), trunk, bark);
  return {
    group,
    dispose() {
      group.children.forEach((c) => {
        const im = c as THREE.InstancedMesh;
        im.geometry.dispose();
        (im.material as THREE.Material).dispose();
      });
      group.clear();
    },
  };
}

/** Merged cased roads — Google-Maps cue: dark casing under a lighter fill ribbon.
 *  Casing = full OSM width at y=0.020; fill = ×0.62 at y=0.022, colour by class. */
function roadsGroup(origin: { lat: number; lon: number },
                    roads: OsmRoad[]): { group: THREE.Group; dispose: () => void } {
  const group = new THREE.Group();
  if (!roads.length) return { group, dispose: () => undefined };
  const buildPass = (widthFactor: number, y: number): THREE.BufferGeometry[] => {
    const geos: THREE.BufferGeometry[] = [];
    for (const road of roads) {
      const pts = road.points.map(([la, lo]) => enuUnits(origin, la, lo));
      const halfW = (ROAD_HALF_W[road.cls] ?? 2) * M_TO_U * widthFactor;
      const { verts, tris } = roadRibbon(pts, halfW);
      if (tris === 0) continue;
      const geo = new THREE.BufferGeometry();
      const positions = new Float32Array(verts.length);
      for (let i = 0; i < pts.length; i++) {
        positions[i * 4] = verts[i * 4];           // left x
        positions[i * 4 + 1] = y;                  // left y
        positions[i * 4 + 2] = verts[i * 4 + 1];   // left z
        positions[i * 4 + 3] = verts[i * 4 + 2];   // right x
        positions[i * 4 + 4] = y;                  // right y
        positions[i * 4 + 5] = verts[i * 4 + 3];   // right z
      }
      geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
      const idx: number[] = [];
      for (let i = 0; i < pts.length - 1; i++) {
        const a = i * 2, b = i * 2 + 1;
        idx.push(a, b, a + 2, b, b + 2, a + 2);
      }
      geo.setIndex(idx);
      geo.computeVertexNormals();
      geos.push(geo);
    }
    return geos;
  };
  const disposeList: (THREE.Material | THREE.BufferGeometry)[] = [];
  const addPass = (geos: THREE.BufferGeometry[], color: number, roughness: number): void => {
    if (!geos.length) return; // mergeGeometries([]) reads geometries[0].index -> TypeError
    const merged = mergeGeometries(geos, false);
    geos.forEach((g) => g.dispose());
    if (!merged) return;
    const mat = new THREE.MeshStandardMaterial({ color, roughness, metalness: 0.05 });
    disposeList.push(merged, mat);
    const mesh = new THREE.Mesh(merged, mat);
    mesh.receiveShadow = true;
    group.add(mesh);
  };
  addPass(buildPass(1, 0.02), CARTO.roadCasing, 0.95);                       // casing
  const fillRes = (cls: string): number =>
    cls === 'residential' || cls === 'service' || cls === 'unclassified'
      ? CARTO.roadFillRes : CARTO.roadFill;
  // fill pass split by colour class (two merges, still bounded draw calls)
  const fillMajor: THREE.BufferGeometry[] = [], fillMinor: THREE.BufferGeometry[] = [];
  for (const road of roads) {
    const pts = road.points.map(([la, lo]) => enuUnits(origin, la, lo));
    const halfW = (ROAD_HALF_W[road.cls] ?? 2) * M_TO_U * 0.62;
    const { verts, tris } = roadRibbon(pts, halfW);
    if (tris === 0) continue;
    const geo = new THREE.BufferGeometry();
    const positions = new Float32Array(verts.length);
    for (let i = 0; i < pts.length; i++) {
      positions[i * 4] = verts[i * 4];
      positions[i * 4 + 1] = 0.022;
      positions[i * 4 + 2] = verts[i * 4 + 1];
      positions[i * 4 + 3] = verts[i * 4 + 2];
      positions[i * 4 + 4] = 0.022;
      positions[i * 4 + 5] = verts[i * 4 + 3];
    }
    geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    const idx: number[] = [];
    for (let i = 0; i < pts.length - 1; i++) {
      const a = i * 2, b = i * 2 + 1;
      idx.push(a, b, a + 2, b, b + 2, a + 2);
    }
    geo.setIndex(idx);
    geo.computeVertexNormals();
    (fillRes(road.cls) === CARTO.roadFill ? fillMajor : fillMinor).push(geo);
  }
  addPass(fillMajor, CARTO.roadFill, 0.85);
  addPass(fillMinor, CARTO.roadFillRes, 0.9);
  return {
    group,
    dispose() {
      disposeList.forEach((d) => d.dispose());
      group.clear();
    },
  };
}

/** Flat ground patches: water / wood / landuse (CARTO palette, real OSM polygons)
 *  + a merged water shore line (Google-Maps shoreline cue). */
function patchesGroup(origin: { lat: number; lon: number }, ctx: SceneContext):
  { group: THREE.Group; dispose: () => void } {
  const group = new THREE.Group();
  const disposeList: (THREE.Material | THREE.BufferGeometry)[] = [];
  const layers: { list: OsmPoly[] | OsmLanduse[]; color: number; y: number; rough: number }[] = [
    { list: ctx.water, color: CARTO.water, y: 0.01, rough: 0.15 },
    { list: ctx.wood, color: CARTO.wood, y: 0.006, rough: 0.9 },
    { list: ctx.landuse, color: 0, y: 0.004, rough: 0.95 },
  ];
  for (const layer of layers) {
    if (!layer.list.length) continue;
    const geos: THREE.BufferGeometry[] = [];
    for (const poly of layer.list) {
      const ring = closedCCW(poly.outline.map(([la, lo]) => enuUnits(origin, la, lo)));
      if (ring.length < 4) continue;
      const g = new THREE.ShapeGeometry(shapeFromRing(ring));
      g.rotateX(-Math.PI / 2);
      geos.push(g);
    }
    if (!geos.length) continue; // every ring degenerate -> empty merge would throw
    const merged = mergeGeometries(geos, false);
    geos.forEach((g) => g.dispose());
    if (!merged) continue;
    flatPoly(merged, layer.y);
    const first = layer.list[0] as OsmLanduse;
    const color = layer.y === 0.004
      ? (CARTO.landuse as Record<string, number>)[first.kind] ?? 0x363b42
      : layer.color;
    const mat = new THREE.MeshStandardMaterial(
      { color, roughness: layer.rough, metalness: layer.y === 0.01 ? 0.8 : 0 });
    disposeList.push(merged, mat);
    const mesh = new THREE.Mesh(merged, mat);
    mesh.receiveShadow = true;
    group.add(mesh);
  }
  // water shore line (merged line segments — one draw call)
  if (ctx.water.length) {
    const shore: THREE.BufferGeometry[] = [];
    for (const w of ctx.water) {
      const ring = w.outline.map(([la, lo]) => enuUnits(origin, la, lo));
      if (ring.length < 3) continue;
      const pos: number[] = [];
      for (let i = 0; i < ring.length - 1; i++) {
        pos.push(ring[i].x, 0.018, ring[i].z, ring[i + 1].x, 0.018, ring[i + 1].z);
      }
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(pos), 3));
      shore.push(g);
    }
    if (shore.length) {
      const merged = mergeGeometries(shore, false);
      shore.forEach((g) => g.dispose());
      if (merged) {
        const mat = new THREE.LineBasicMaterial({
          color: CARTO.waterShore, transparent: true, opacity: 0.8 });
        disposeList.push(merged, mat);
        group.add(new THREE.LineSegments(merged, mat));
      }
    }
  }
  return {
    group,
    dispose() {
      disposeList.forEach((d) => d.dispose());
      group.clear();
    },
  };
}
/** Text sprite for the anti-confusion callout (nearest real OSM building). */
export function buildLabelSprite(text: string, color = '#E8EEF5'):
  { sprite: THREE.Sprite; dispose: () => void } {
  const c = document.createElement('canvas');
  c.width = 512;
  c.height = 128;
  const g = c.getContext('2d')!;
  g.fillStyle = 'rgba(7,9,13,0.78)';
  g.fillRect(0, 0, 512, 128);
  g.strokeStyle = '#FF6B35';
  g.lineWidth = 4;
  g.strokeRect(2, 2, 508, 124);
  g.fillStyle = color;
  g.font = 'bold 40px "IBM Plex Mono", monospace';
  g.textBaseline = 'middle';
  g.textAlign = 'center';
  g.fillText(text.slice(0, 44), 256, 64);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  const mat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false });
  const sprite = new THREE.Sprite(mat);
  sprite.scale.set(12, 3, 1);
  return { sprite, dispose() { tex.dispose(); mat.dispose(); } };
}

/** Scattered canopy over wood polygons (ILLUSTRATIVE — density disclosed in the
 *  legend, never a fuel model). Deterministic rejection sampling inside the REAL
 *  OSM polygon (scatterInPolygon), broadleaf blobs, cap 300/poly. */
function woodScatter(origin: { lat: number; lon: number }, ctx: SceneContext):
  THREE.InstancedMesh | null {
  if (!ctx.wood.length) return null;
  const pts: (EnuU & { s: number })[] = [];
  ctx.wood.forEach((w, i) => {
    const ring = w.outline.map(([la, lo]) => enuUnits(origin, la, lo));
    for (const p of scatterInPolygon(ring, 220, 11 + i)) {
      const r = mulberry32(5000 + pts.length);
      pts.push({ ...p, s: 0.25 + r() * 0.25 });
    }
  });
  if (!pts.length) return null;
  const geo = new THREE.IcosahedronGeometry(1, 0);
  const mat = new THREE.MeshStandardMaterial({ color: CARTO.canopy, roughness: 0.95 });
  const im = new THREE.InstancedMesh(geo, mat, pts.length);
  pts.forEach((p, k) => {
    const m4 = new THREE.Matrix4().compose(
      new THREE.Vector3(p.x, 0.03 + p.s * 0.5, p.z),
      new THREE.Quaternion(),
      new THREE.Vector3(p.s, p.s, p.s));
    im.setMatrixAt(k, m4);
  });
  im.instanceMatrix.needsUpdate = true;
  return im;
}

/** Halo text sprite (dark stroke + light fill — readable on any backdrop). */
export function buildHaloLabel(text: string, opts: { fill?: string; scale?: number } = {}):
  { sprite: THREE.Sprite; dispose: () => void } {
  const c = document.createElement('canvas');
  c.width = 512;
  c.height = 96;
  const g = c.getContext('2d')!;
  g.font = 'bold 44px "IBM Plex Mono", monospace';
  g.textAlign = 'center';
  g.textBaseline = 'middle';
  g.strokeStyle = CARTO.label.halo;
  g.lineWidth = 8;
  g.strokeText(text.slice(0, 28), 256, 48);
  g.fillStyle = opts.fill ?? CARTO.label.fill;
  g.fillText(text.slice(0, 28), 256, 48);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  const mat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false });
  const sprite = new THREE.Sprite(mat);
  const w = opts.scale ?? 6;
  sprite.scale.set(w, w * 0.1875, 1);
  return { sprite, dispose() { tex.dispose(); mat.dispose(); } };
}

export interface LabelCandidate { prio: number; text: string; x: number; z: number; road?: boolean }

/** Named-feature labels: priority facility → water → wood → landuse → primary
 *  roads → other roads, capped at LABEL_CAP. Positions = centroid / midpoint. */
export function buildOsmLabels(origin: { lat: number; lon: number },
                               ctx: SceneContext): { sprites: THREE.Sprite[]; dispose: () => void } {
  const cands: LabelCandidate[] = [];
  const centroid = (ring: EnuU[]): EnuU => ({
    x: ring.reduce((a, p) => a + p.x, 0) / ring.length,
    z: ring.reduce((a, p) => a + p.z, 0) / ring.length,
  });
  for (const w of ctx.water) if (w.name) {
    const c = centroid(w.outline.map(([la, lo]) => enuUnits(origin, la, lo)));
    cands.push({ prio: 1, text: w.name, x: c.x, z: c.z });
  }
  for (const w of ctx.wood) if (w.name) {
    const c = centroid(w.outline.map(([la, lo]) => enuUnits(origin, la, lo)));
    cands.push({ prio: 2, text: w.name, x: c.x, z: c.z });
  }
  for (const w of ctx.landuse) if (w.name) {
    const c = centroid(w.outline.map(([la, lo]) => enuUnits(origin, la, lo)));
    cands.push({ prio: 3, text: w.name, x: c.x, z: c.z });
  }
  for (const r of ctx.roads) if (r.name) {
    const pts = r.points.map(([la, lo]) => enuUnits(origin, la, lo));
    const mid = pts[Math.floor(pts.length / 2)];
    cands.push({ prio: 4, text: r.name, x: mid.x, z: mid.z, road: true });
  }
  cands.sort((a, b) => a.prio - b.prio || a.text.length - b.text.length);
  const picked = cands.slice(0, LABEL_CAP);
  const sprites: THREE.Sprite[] = [];
  const disposables: { dispose: () => void }[] = [];
  for (const c of picked) {
    const l = buildHaloLabel(c.text, { fill: c.road ? CARTO.label.road : CARTO.label.fill,
      scale: c.road ? 5 : 7 });
    l.sprite.position.set(c.x, 0.09, c.z);
    sprites.push(l.sprite);
    disposables.push(l);
  }
  return {
    sprites,
    dispose: () => disposables.forEach((d) => d.dispose()),
  };
}

/** Full OSM context group. Draw calls stay bounded: merged buildings/roofs/
 *  outlines/roads/patches + instanced trees + canopy + halo labels.
 *  Dispose frees every geometry/material/texture. */
export function buildOsmScene(origin: { lat: number; lon: number }, ctx: SceneContext): OsmSceneResult {
  const group = new THREE.Group();
  const parts: { dispose: () => void }[] = [];
  const b = buildingsGroup(origin, ctx.buildings);
  const t = treesGroup(origin, ctx.trees);
  const r = roadsGroup(origin, ctx.roads);
  const p = patchesGroup(origin, ctx);
  parts.push(b, t, r, p);
  group.add(b.group, t.group, r.group, p.group);
  const scatter = woodScatter(origin, ctx);
  if (scatter) {
    group.add(scatter);
    parts.push({
      dispose() {
        scatter.geometry.dispose();
        (scatter.material as THREE.Material).dispose();
      },
    });
  }
  const labels = buildOsmLabels(origin, ctx);
  for (const s of labels.sprites) group.add(s);
  parts.push(labels);
  return {
    group,
    stats: { buildings: ctx.buildings.length, trees: ctx.trees.length,
             roads: ctx.roads.length, polys: ctx.water.length + ctx.wood.length,
             meshes: group.children.length },
    dispose() {
      parts.forEach((x) => x.dispose());
      group.clear();
    },
  };
}