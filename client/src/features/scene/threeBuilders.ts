/** three.js builders for the per-detection incident scene (Session 23).
 *  Everything returns a dispose() — WebGL context-loss remounts rely on it. */
import * as THREE from 'three';
import { hotspotColor, hotspotRadius, toEnu, clusterEllipse,
  type Detection, type Ellipse } from './sceneData';

const UNIT = 100; // metres per scene unit
const M_TO_U = 1 / UNIT;

let _tex: THREE.Texture | null = null;
function radialTexture(): THREE.Texture {
  if (_tex) return _tex;
  const c = document.createElement('canvas');
  c.width = c.height = 64;
  const g = c.getContext('2d')!;
  const grd = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  grd.addColorStop(0, 'rgba(255,255,255,1)');
  grd.addColorStop(0.4, 'rgba(255,180,80,0.8)');
  grd.addColorStop(1, 'rgba(255,107,53,0)');
  g.fillStyle = grd;
  g.fillRect(0, 0, 64, 64);
  _tex = new THREE.CanvasTexture(c);
  return _tex;
}

export function disposeSharedTexture(): void {
  _tex?.dispose();
  _tex = null;
}

export interface HotspotField {
  group: THREE.Group;
  addDetection(d: Detection): void;
  /** null = show everything (latest); epoch ms = hide detections acquired after t. */
  setReplay(tMs: number | null): void;
  update(nowMs: number): void;
  dispose(): void;
}

/** ONE additive sprite per FIRMS VIIRS 375 m detection, at its true lat/lon —
 *  per-detection placement, never a centroid ball. */
export function buildHotspotField(origin: { lat: number; lon: number },
                                  dets: Detection[]): HotspotField {
  const group = new THREE.Group();
  const sprites: { sp: THREE.Sprite; acqMs: number; seed: number; base: number }[] = [];
  const add = (d: Detection) => {
    const enu = toEnu(origin.lat, origin.lon, d.lat, d.lon);
    const mat = new THREE.SpriteMaterial({
      map: radialTexture(),
      color: new THREE.Color(hotspotColor(d.brightness_k)),
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      transparent: true,
    });
    const sp = new THREE.Sprite(mat);
    const r = hotspotRadius(d.frp_mw);
    sp.position.set(enu.e * M_TO_U, 0.05, -enu.n * M_TO_U);
    group.add(sp);
    sprites.push({
      sp,
      acqMs: d.acq_epoch_ms ?? (d.acq_at ? Date.parse(d.acq_at) : 0),
      seed: Math.abs(Math.round(d.lat * 7919 + d.lon * 104729)) % 97,
      base: r * 2,
    });
  };
  dets.forEach(add);

  let replayMs: number | null = null;
  const applyReplay = () => {
    for (const s of sprites) {
      const visible = replayMs == null || s.acqMs === 0 || s.acqMs <= replayMs;
      s.sp.visible = visible;
    }
  };

  return {
    group,
    addDetection: add,
    setReplay: (tMs) => { replayMs = tMs; applyReplay(); },
    update(nowMs) {
      for (const s of sprites) {
        if (!s.sp.visible) continue;
        const flick = 1 + 0.08 * Math.sin(nowMs / 140 + s.seed);
        s.sp.scale.setScalar(s.base * flick);
      }
    },
    dispose() {
      for (const s of sprites) s.sp.material.dispose();
      group.clear();
    },
  };
}

/** 2σ cluster ellipse outline on the ground plane. */
export function buildEllipseLine(el: Ellipse, color = '#FF6B35'): THREE.LineLoop {
  const pts: THREE.Vector3[] = [];
  for (let i = 0; i < 64; i++) {
    const t = (i / 64) * Math.PI * 2;
    const x = el.a * Math.cos(t) * M_TO_U;
    const y = el.b * Math.sin(t) * M_TO_U;
    const rx = x * Math.cos(el.rot) - y * Math.sin(el.rot);
    const ry = x * Math.sin(el.rot) + y * Math.cos(el.rot);
    pts.push(new THREE.Vector3(rx, 0.02, -ry));
  }
  const loop = new THREE.LineLoop(
    new THREE.BufferGeometry().setFromPoints(pts),
    new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.8 }),
  );
  loop.position.set(el.ce * M_TO_U, 0, -el.cn * M_TO_U);
  return loop;
}

/** ILLUSTRATIVE plume (buoyancy + fixed-wind drift) — not a dispersion model. */
export function buildPlume(windDeg = 225, count = 180):
  { points: THREE.Points; update(dtSec: number): void; dispose(): void } {
  const pos = new Float32Array(count * 3);
  const vel = new Float32Array(count * 3);
  const life = new Float32Array(count);
  const wr = (windDeg * Math.PI) / 180;
  for (let i = 0; i < count; i++) {
    life[i] = Math.random();
    vel.set([Math.sin(wr) * 0.35, 0.5 + Math.random() * 0.4, Math.cos(wr) * 0.35], i * 3);
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  const mat = new THREE.PointsMaterial({
    color: 0x9aa4ad, size: 0.12, transparent: true, opacity: 0.35, depthWrite: false,
  });
  const points = new THREE.Points(geo, mat);
  return {
    points,
    update(dt) {
      const p = geo.attributes.position as THREE.BufferAttribute;
      for (let i = 0; i < count; i++) {
        life[i] += dt / 6;
        if (life[i] > 1) { life[i] = 0; p.setXYZ(i, 0, 0, 0); }
        p.setXYZ(i, p.getX(i) + vel[i * 3] * dt, p.getY(i) + vel[i * 3 + 1] * dt,
          p.getZ(i) + vel[i * 3 + 2] * dt);
      }
      p.needsUpdate = true;
    },
    dispose() { geo.dispose(); mat.dispose(); },
  };
}

export { clusterEllipse };
