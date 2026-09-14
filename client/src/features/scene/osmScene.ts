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
import { toEnu } from './sceneData';

export type OsmBuildingKind = 'industrial' | 'commercial' | 'residential' | 'generic';
export type OsmHeightSource = 'tag:height' | 'tag:levels' | 'estimated';

export interface OsmBuilding {
  id: number;
  outline: [number, number][]; // [lat, lon] ring (closed by Overpass)
  height_m: number;
  height_source: OsmHeightSource;
  kind: OsmBuildingKind;
}
export interface OsmTree { lat: number; lon: number; crown_m: number }
export interface OsmRoad { points: [number, number][]; cls: string }
export interface OsmPoly { outline: [number, number][] }
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

/** Lift every vertex of a flat geometry onto plane y (ground patches). */
function flatPoly(geo: THREE.BufferGeometry, y: number): THREE.BufferGeometry {
  const pos = geo.getAttribute('position') as THREE.BufferAttribute;
  for (let i = 0; i < pos.count; i++) pos.setY(i, y);
  return geo;
}

export interface OsmSceneResult {
  group: THREE.Group;
  stats: { buildings: number; trees: number; roads: number; polys: number };
  dispose: () => void;
}

const KIND_MATERIALS: Record<OsmBuildingKind,
  { color: number; roughness: number; metalness: number }> = {
  industrial: { color: 0x8a9199, roughness: 0.6, metalness: 0.35 },
  commercial: { color: 0xa9b2bd, roughness: 0.7, metalness: 0.15 },
  residential: { color: 0xcbb28a, roughness: 0.9, metalness: 0.05 },
  generic: { color: 0x9d9aa0, roughness: 0.8, metalness: 0.1 },
};

const LANDUSE_TINT: Record<string, number> = {
  farmland: 0x6b7d4f, industrial: 0x55606b, commercial: 0x5a6472,
  residential: 0x6d6456, orchard: 0x5f7d4a,
};

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

/** REAL OSM footprint rings extruded to true/estimated height, merged per kind. */
function buildingsGroup(origin: { lat: number; lon: number },
                        buildings: OsmBuilding[]): { group: THREE.Group; dispose: () => void } {
  const group = new THREE.Group();
  const byKind: Record<OsmBuildingKind, THREE.BufferGeometry[]> = {
    industrial: [], commercial: [], residential: [], generic: [],
  };
  for (const b of buildings) {
    const ring = closedCCW(b.outline.map(([la, lo]) => enuUnits(origin, la, lo)));
    if (ring.length < 4) continue;
    const geo = new THREE.ExtrudeGeometry(shapeFromRing(ring), {
      depth: Math.max(0.15, b.height_m * M_TO_U), bevelEnabled: false,
    });
    geo.rotateX(-Math.PI / 2); // extrude +Z -> up +Y; shape (x,-north) -> (x, north)
    byKind[b.kind].push(geo);
  }
  const matCache = new Map<OsmBuildingKind, THREE.MeshStandardMaterial>();
  for (const kind of Object.keys(byKind) as OsmBuildingKind[]) {
    const geos = byKind[kind];
    if (!geos.length) continue;
    const merged = mergeGeometries(geos, false);
    geos.forEach((g) => g.dispose());
    if (!merged) continue;
    const mat = new THREE.MeshStandardMaterial(KIND_MATERIALS[kind]);
    matCache.set(kind, mat);
    const mesh = new THREE.Mesh(merged, mat);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    group.add(mesh);
  }
  return {
    group,
    dispose() {
      group.children.forEach((c) => (c as THREE.Mesh).geometry.dispose());
      matCache.forEach((m) => m.dispose());
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

/** Merged asphalt ribbons — road geometry from real OSM highway polylines. */
function roadsGroup(origin: { lat: number; lon: number },
                    roads: OsmRoad[]): { group: THREE.Group; dispose: () => void } {
  const group = new THREE.Group();
  if (!roads.length) return { group, dispose: () => undefined };
  const geos: THREE.BufferGeometry[] = [];
  for (const road of roads) {
    const pts = road.points.map(([la, lo]) => enuUnits(origin, la, lo));
    const halfW = (ROAD_HALF_W[road.cls] ?? 2) * M_TO_U;
    const { verts, tris } = roadRibbon(pts, halfW);
    if (tris === 0) continue;
    const geo = new THREE.BufferGeometry();
    const positions = new Float32Array(verts.length);
    for (let i = 0; i < pts.length; i++) {
      positions[i * 4] = verts[i * 4];           // left x
      positions[i * 4 + 1] = 0.02;               // left y
      positions[i * 4 + 2] = verts[i * 4 + 1];   // left z
      positions[i * 4 + 3] = verts[i * 4 + 2];   // right x
      positions[i * 4 + 4] = 0.02;               // right y
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
  const merged = mergeGeometries(geos, false);
  geos.forEach((g) => g.dispose());
  if (merged) {
    const mesh = new THREE.Mesh(merged, new THREE.MeshStandardMaterial(
      { color: 0x414b57, roughness: 0.9, metalness: 0.1 }));
    mesh.receiveShadow = true;
    group.add(mesh);
  }
  return {
    group,
    dispose() {
      group.children.forEach((c) => (c as THREE.Mesh).geometry.dispose());
      group.children.forEach((c) => {
        (c as THREE.Mesh).material && ((c as THREE.Mesh).material as THREE.Material).dispose();
      });
      group.clear();
    },
  };
}

/** Flat ground patches: water / wood / landuse tints (real OSM polygons). */
function patchesGroup(origin: { lat: number; lon: number }, ctx: SceneContext):
  { group: THREE.Group; dispose: () => void } {
  const group = new THREE.Group();
  const layers: { list: OsmPoly[] | OsmLanduse[]; color: number; y: number }[] = [
    { list: ctx.water, color: 0x2e5f7a, y: 0.01 },
    { list: ctx.wood, color: 0x2d4a2e, y: 0.006 },
    { list: ctx.landuse, color: 0, y: 0.004 },
  ];
  const matCache: THREE.MeshStandardMaterial[] = [];
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
    const merged = mergeGeometries(geos, false);
    geos.forEach((g) => g.dispose());
    if (!merged) continue;
    flatPoly(merged, layer.y);
    const color = layer.y === 0.004
      ? LANDUSE_TINT[(layer.list[0] as OsmLanduse).kind] ?? 0x5f6b5a
      : layer.color;
    const mat = new THREE.MeshStandardMaterial(
      { color, roughness: layer.y === 0.01 ? 0.15 : 0.9,
        metalness: layer.y === 0.01 ? 0.8 : 0 });
    matCache.push(mat);
    const mesh = new THREE.Mesh(merged, mat);
    mesh.receiveShadow = true;
    group.add(mesh);
  }
  return {
    group,
    dispose() {
      group.children.forEach((c) => (c as THREE.Mesh).geometry.dispose());
      matCache.forEach((m) => m.dispose());
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

/** Scattered canopy over wood polygons (ILLUSTRATIVE — not a fuel model). */
function woodScatter(origin: { lat: number; lon: number }, ctx: SceneContext):
  THREE.InstancedMesh | null {
  if (!ctx.wood.length) return null;
  let n = 0;
  for (const w of ctx.wood) n += Math.min(30, Math.floor(w.outline.length / 2));
  n = Math.min(n, 120);
  if (!n) return null;
  const geo = new THREE.IcosahedronGeometry(1, 0);
  const mat = new THREE.MeshStandardMaterial({ color: 0x27492b, roughness: 0.95 });
  const im = new THREE.InstancedMesh(geo, mat, n);
  let k = 0;
  for (const w of ctx.wood) {
    const ring = w.outline.map(([la, lo]) => enuUnits(origin, la, lo));
    const x0 = Math.min(...ring.map((p) => p.x));
    const x1 = Math.max(...ring.map((p) => p.x));
    const z0 = Math.min(...ring.map((p) => p.z));
    const z1 = Math.max(...ring.map((p) => p.z));
    const want = Math.min(30, Math.floor(w.outline.length / 2));
    for (let i = 0; i < want && k < n; i++, k++) {
      const r = mulberry32(5000 + k);
      const s = 0.25 + r() * 0.25;
      const m4 = new THREE.Matrix4().compose(
        new THREE.Vector3(x0 + r() * (x1 - x0), 0.03 + s * 0.5, z0 + r() * (z1 - z0)),
        new THREE.Quaternion(),
        new THREE.Vector3(s, s, s));
      im.setMatrixAt(k, m4);
    }
  }
  im.instanceMatrix.needsUpdate = true;
  return im;
}

/** Full OSM context group. Draw calls stay bounded: merged buildings/roads/patches
 *  + instanced trees + wood scatter. Dispose frees every geometry/material. */
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
  return {
    group,
    stats: { buildings: ctx.buildings.length, trees: ctx.trees.length,
             roads: ctx.roads.length, polys: ctx.water.length + ctx.wood.length },
    dispose() {
      parts.forEach((x) => x.dispose());
      group.clear();
    },
  };
}