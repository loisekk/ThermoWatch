/** Scene 2.0 pure math — per-detection placement (1 scene unit = 100 m).
 *  No three.js / canvas imports: fully unit-testable, shared by ThreeScene,
 *  CanvasScene and future engines. Coordinates: east = +x, north = +n metres;
 *  Three consumes (x, z = -n), Canvas consumes (x, y = +n). */

export interface Detection {
  lat: number;
  lon: number;
  frp_mw: number;
  brightness_k: number;
  acq_epoch_ms?: number;
  acq_at: string;
  sat?: string | null;
}

export interface Enu { e: number; n: number }

export interface Ellipse {
  /** centre, metres east/north of origin */
  ce: number;
  cn: number;
  /** 2-sigma semi-axes, metres */
  a: number;
  b: number;
  /** rotation, radians (east-ccw) */
  rot: number;
}

export const M_PER_DEG_LAT = 111_320;
export const HOTSPOT_CAP = 200;

const rad = (d: number) => (d * Math.PI) / 180;

/** Local east/north metres (equirectangular at mid-latitude — scene-scale accurate). */
export function toEnu(oLat: number, oLon: number, lat: number, lon: number): Enu {
  const mLat = (lat + oLat) / 2;
  return {
    e: (lon - oLon) * M_PER_DEG_LAT * Math.cos(rad(mLat)),
    n: (lat - oLat) * M_PER_DEG_LAT,
  };
}

/** 2-sigma covariance ellipse of the detection cluster — measured extent, not a guess.
 *  Returns null below 3 points (too few to speak about spread). */
export function clusterEllipse(pts: Enu[]): Ellipse | null {
  if (pts.length < 3) return null;
  const me = pts.reduce((s, p) => s + p.e, 0) / pts.length;
  const mn = pts.reduce((s, p) => s + p.n, 0) / pts.length;
  let cee = 0, cen = 0, cnn = 0;
  for (const p of pts) {
    const de = p.e - me, dn = p.n - mn;
    cee += de * de; cen += de * dn; cnn += dn * dn;
  }
  const n = pts.length - 1 || 1;
  cee /= n; cen /= n; cnn /= n;
  const tr = cee + cnn;
  const det = cee * cnn - cen * cen;
  const disc = Math.sqrt(Math.max(0, (tr * tr) / 4 - det));
  const l1 = tr / 2 + disc;
  const l2 = tr / 2 - disc;
  return {
    ce: me, cn: mn,
    a: 2 * Math.sqrt(Math.max(l1, 1)),
    b: 2 * Math.sqrt(Math.max(l2, 1)),
    rot: 0.5 * Math.atan2(2 * cen, cee - cnn),
  };
}

/** Hotspot footprint radius (scene units, 1 u = 100 m). Size by FRP, clamped. */
export function hotspotRadius(frpMw: number): number {
  return Math.min(4, Math.max(0.6, 0.6 + Math.sqrt(Math.max(0, frpMw)) / 6));
}

/** Taxonomy-consistent brightness ramp (Kelvin → colour token). */
export function hotspotColor(brightnessK: number): string {
  if (brightnessK < 350) return '#FFB800';
  if (brightnessK < 450) return '#FF6B35';
  return '#FF4444';
}

/** Keep the highest-FRP detections when the cloud would overwhelm the scene. */
export function capByFrp(dets: Detection[], cap = HOTSPOT_CAP): Detection[] {
  return [...dets].sort((a, b) => b.frp_mw - a.frp_mw).slice(0, cap);
}

/** Replay window from detection acquisition times; falls back to the last 24 h. */
export function replayWindow(dets: Detection[]): { fromMs: number; toMs: number } {
  const ts = dets
    .map((d) => (d.acq_epoch_ms ?? (d.acq_at ? Date.parse(d.acq_at) : NaN)))
    .filter((t) => Number.isFinite(t));
  if (!ts.length) return { fromMs: Date.now() - 86_400_000, toMs: Date.now() };
  return { fromMs: Math.min(...ts), toMs: Math.max(...ts) };
}
