import { gibsTileUrl, GIBS_LAYERS, type GibsKey } from '@/config/imagery';

const RAD = Math.PI / 180;
const DEG = 180 / Math.PI;
const SLICES = 12; // vertical reprojection slices per tile — exact enough, cheap

const cache = new Map<string, HTMLImageElement>();
const CACHE_CAP = 220;

/** Inverse Web-Mercator: tile-row float → latitude (degrees). */
export function mercatorLat(yFloat: number, n: number): number {
  return Math.atan(Math.sinh(Math.PI - (2 * Math.PI * yFloat) / n)) * DEG;
}

/** Forward Web-Mercator: latitude → tile-row float. */
export function mercatorYFloat(lat: number, n: number): number {
  const clamped = Math.max(-85.05112878, Math.min(85.05112878, lat));
  return (n / 2) * (1 - Math.log(Math.tan(Math.PI / 4 + (clamped * RAD) / 2)) / Math.PI);
}

export interface TileRange { x0: number; x1: number; y0: number; y1: number; n: number }

/** Visible Mercator tile indices for a lon/lat window at zoom z. */
export function visibleTiles(lonMin: number, lonMax: number, latMin: number, latMax: number, z: number): TileRange {
  const n = 2 ** z;
  const xF = (lon: number) => ((lon + 180) / 360) * n;
  const x0 = Math.max(0, Math.floor(xF(lonMin)));
  const x1 = Math.min(n - 1, Math.floor(xF(lonMax)));
  const y0 = Math.max(0, Math.floor(mercatorYFloat(latMax, n)));
  const y1 = Math.min(n - 1, Math.floor(mercatorYFloat(latMin, n)));
  return { x0, x1, y0, y1, n };
}

export interface GibbsView {
  base: number;              // px per world-unit (world = 2000x1000 equirect)
  tx: number; ty: number;    // screen offset of world origin (lon -180, lat 90)
  worldW: number; worldH: number;
}

/**
 * Paints NASA GIBS (EPSG:3857) tiles onto an EQUIRECTANGULAR canvas correctly:
 * each Mercator tile is sliced into SLICES horizontal bands; every band's true
 * lat extent (via mercatorLat) is mapped to its equirect destination rect, so
 * coastlines register exactly with vector data at all latitudes.
 */
export function drawGibs(
  ctx: CanvasRenderingContext2D,
  layer: GibsKey,
  view: GibbsView,
  _cw: number,
  ch: number,
  alpha: number,
  requestRedraw: () => void,
): void {
  const maxZ = GIBS_LAYERS[layer].maxZ;
  // choose zoom so one tile lands ~256-512 screen px wide
  const z = Math.max(0, Math.min(maxZ, Math.round(Math.log2((view.worldW * view.base) / 256))));
  const n = 2 ** z;

  // screen-space projector (equirect)
  const X = (lon: number) => view.tx + ((lon + 180) / 360) * view.worldW * view.base;
  const Y = (lat: number) => view.ty + ((90 - lat) / 180) * view.worldH * view.base;

  // visible lon/lat window from screen edges
  const lonMin = -180, lonMax = 180;
  const latMax = 90 - ((0 - view.ty) / (view.worldH * view.base)) * 180;
  const latMin = 90 - ((ch - view.ty) / (view.worldH * view.base)) * 180;
  const { x0, x1, y0, y1 } = visibleTiles(lonMin, lonMax, Math.max(-85, latMin), Math.min(85, latMax), z);

  const tileSize = 256;
  ctx.save();
  ctx.globalAlpha = alpha;

  for (let x = x0; x <= x1; x++) {
    const west = (x / n) * 360 - 180;
    const east = ((x + 1) / n) * 360 - 180;
    const dx0 = X(west), dx1 = X(east);
    for (let y = y0; y <= y1; y++) {
      const key = `${layer}/${z}/${x}/${y}`;
      let img = cache.get(key);
      if (!img) {
        img = new Image();
        img.crossOrigin = 'anonymous';
        img.src = gibsTileUrl(layer, z, x, y);
        img.onload = () => requestRedraw();
        cache.set(key, img);
        if (cache.size > CACHE_CAP) cache.delete(cache.keys().next().value as string);
      }
      if (!img.complete || img.naturalWidth === 0) continue;

      // slice the tile vertically: each slice's true lat band → equirect dest rect
      for (let s = 0; s < SLICES; s++) {
        const latN = mercatorLat(y + s / SLICES, n);
        const latS = mercatorLat(y + (s + 1) / SLICES, n);
        const dy0 = Y(latN), dy1 = Y(latS);
        if (dy1 < 0 || dy0 > ch) continue;
        ctx.drawImage(
          img,
          0, (s * tileSize) / SLICES, tileSize, tileSize / SLICES,
          dx0, dy0, dx1 - dx0 + 0.5, dy1 - dy0 + 0.5,
        );
      }
    }
  }
  ctx.restore();
}