/**
 * Pure orthographic-globe math. No DOM, no canvas — fully unit-testable.
 *
 * Convention: lat/lon in degrees, rotation in radians. A point is visible when
 * its rotated z is positive (it faces the viewer).
 */
export interface Vec3 {
  x: number;
  y: number;
  z: number;
}

const DEG = Math.PI / 180;

export function latLonToVec3(lat: number, lon: number): Vec3 {
  const la = lat * DEG;
  const lo = lon * DEG;
  return { x: Math.cos(la) * Math.sin(lo), y: Math.sin(la), z: Math.cos(la) * Math.cos(lo) };
}

/** Rotate by view longitude (Y axis) then view tilt (X axis). Radians. */
export function rotateVec(v: Vec3, lonRot: number, latRot: number): Vec3 {
  const cl = Math.cos(lonRot);
  const sl = Math.sin(lonRot);
  const x1 = v.x * cl + v.z * sl;
  const z1 = -v.x * sl + v.z * cl;
  const ct = Math.cos(latRot);
  const st = Math.sin(latRot);
  return { x: x1, y: v.y * ct - z1 * st, z: v.y * st + z1 * ct };
}

export function isVisible(v: Vec3): boolean {
  return v.z > 0;
}

export function toScreen(v: Vec3, cx: number, cy: number, r: number): { x: number; y: number } {
  return { x: cx + v.x * r, y: cy - v.y * r };
}

/** Rotation that centers (lat, lon) facing the viewer. */
export function centerRotation(lat: number, lon: number): { lonRot: number; latRot: number } {
  return { lonRot: -lon * DEG, latRot: lat * DEG };
}

/** Shortest signed angular delta, result in (-PI, PI]. */
export function shortestAngle(from: number, to: number): number {
  let d = (to - from) % (Math.PI * 2);
  if (d > Math.PI) d -= Math.PI * 2;
  if (d <= -Math.PI) d += Math.PI * 2;
  return d;
}

/**
 * Sub-solar point for a UTC date (approximate — visual terminator only, never
 * presented as sun geometry). Declination follows the day-of-year sinusoid;
 * longitude follows the 15°/hour spin off the noon meridian.
 */
export function subsolarPoint(date: Date): { lat: number; lon: number } {
  const start = Date.UTC(date.getUTCFullYear(), 0, 0);
  const doy = (date.getTime() - start) / 86_400_000;
  const decl = 23.44 * Math.sin((2 * Math.PI * (doy - 80)) / 365);
  const utcHours = date.getUTCHours() + date.getUTCMinutes() / 60;
  const lon = -15 * (utcHours - 12);
  return { lat: decl, lon: ((lon + 540) % 360) - 180 };
}
