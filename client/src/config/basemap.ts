/** Optional night-lights texture candidates (layer default OFF; vector is the default basemap). */
export const NIGHT_TEXTURE_CANDIDATES = [
  '/textures/earth-night.jpg',
  'https://unpkg.com/three-globe/example/img/earth-night.jpg',
] as const;

export const WORLD_IMAGE_COORDS: [[number, number], [number, number], [number, number], [number, number]] = [
  [-180, 85], [180, 85], [180, -60], [-180, -60],
];

export const WORLD_BOUNDS: [[number, number], [number, number]] = [[-179, -58], [179, 74]];

/** Resolves the first candidate URL whose image actually decodes; null if none. */
export function probeNightTexture(timeoutMs = 4000): Promise<string | null> {
  const probe = (url: string) =>
    new Promise<boolean>((resolve) => {
      const img = new Image();
      const t = window.setTimeout(() => resolve(false), timeoutMs);
      img.onload = () => { window.clearTimeout(t); resolve(img.naturalWidth > 512); };
      img.onerror = () => { window.clearTimeout(t); resolve(false); };
      img.src = url;
    });
  return NIGHT_TEXTURE_CANDIDATES.reduce(
    (chain, url) => chain.then((hit) => hit ?? probe(url).then((ok) => (ok ? url : null))),
    Promise.resolve<string | null>(null),
  );
}


