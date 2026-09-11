/** Orthographic-sphere inverse mapping: camera-disc coords → lat/lon. Pure math, unit-tested. */
export interface SphereHit {
  lat: number;
  lon: number;
  z: number;
}

const DEG = 180 / Math.PI;

/**
 * dx, dyUp in [-1, 1] on the visible disc (dyUp positive = up), z = sqrt(1-r²).
 * Returns null for points outside the disc. Used to paint a texture onto the
 * canvas globe by sampling the equirectangular source at the hit's lat/lon.
 */
export function orthoInverse(dx: number, dyUp: number, lon0Deg: number, lat0Deg: number): SphereHit | null {
  const rho = Math.hypot(dx, dyUp);
  if (rho > 1) return null;
  const z = Math.sqrt(Math.max(0, 1 - rho * rho));
  const lon0 = lon0Deg / DEG;
  const lat0 = lat0Deg / DEG;
  if (rho < 1e-9) return { lat: lat0Deg, lon: lon0Deg, z: 1 };
  const c = Math.asin(rho);
  const sinC = Math.sin(c), cosC = Math.cos(c);
  const lat = Math.asin(cosC * Math.sin(lat0) + (dyUp * sinC * Math.cos(lat0)) / rho);
  const lon = lon0 + Math.atan2(dx * sinC, rho * cosC * Math.cos(lat0) - dyUp * sinC * Math.sin(lat0));
  return { lat: lat * DEG, lon: ((lon * DEG + 540) % 360) - 180, z };
}

/** Equirectangular UV for a lat/lon sample. */
export function latLonToUV(lat: number, lon: number): { u: number; v: number } {
  return { u: (lon + 180) / 360, v: (90 - lat) / 180 };
}