import type { ClassFeatures, Classification, FireClass } from '@/types/domain';

/**
 * Context-aware thermal classifier.
 * Proxy for the trained XGBoost ensemble: combines FRP intensity, diurnal
 * behaviour, temporal persistence, OSM facility proximity and land-cover
 * context into normalised multi-class scores. Swap this function for a
 * model-server inference call without touching consumers.
 */
export function classify(f: ClassFeatures): Classification {
  const prox = f.facilityDistanceKm == null ? 0 : Math.exp(-f.facilityDistanceKm / 1.5);
  const hazardBoost = f.facilityHazard === 'G-III' ? 0.12 : f.facilityHazard === 'G-II' ? 0.06 : 0;

  const raw: Record<FireClass, number> = {
    industrial: 0.62 * prox + hazardBoost + 0.22 * norm(f.frp, 900) + 0.16 * f.nightRatio,
    persistent:
      (f.persistDays >= 5 ? 0.68 + 0.012 * Math.min(f.persistDays, 40) : 0.05 * f.persistDays) +
      0.28 * prox +
      0.14 * (1 - f.diurnalVariance),
    wildfire: 0.58 * f.forestProxy + 0.3 * (1 - prox) + 0.22 * f.diurnalVariance,
    agricultural: 0.66 * f.agriWindow + 0.24 * f.clusterDensity + 0.1 * (1 - prox),
  };

  const scores = softmax(raw, 3.2);
  const primary = (Object.keys(scores) as FireClass[]).reduce((a, b) => (scores[a] >= scores[b] ? a : b));
  const confidence = Math.round(Math.min(0.97, Math.max(0.55, scores[primary] + 0.08)) * 100);

  return {
    primary,
    subtype: null, // subtype resolved by caller from facility registry
    scores,
    confidence,
  };
}

const norm = (v: number, max: number): number => Math.min(1, Math.max(0, v / max));

function softmax(v: Record<FireClass, number>, temp: number): Record<FireClass, number> {
  const keys = Object.keys(v) as FireClass[];
  const exps = keys.map((k) => Math.exp(v[k] * temp));
  const sum = exps.reduce((a, b) => a + b, 0);
  return Object.fromEntries(keys.map((k, i) => [k, exps[i] / sum])) as Record<FireClass, number>;
}
