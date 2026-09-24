/**
 * Pure data adapters for the dossier instruments — no DOM, no React, so they
 * run in the node vitest environment. Every adapter is defensive: the API
 * types are wide JSON records (explanation/residuals), so malformed or
 * missing payloads degrade to honest empties instead of NaN shapes.
 */

/** One evidence source in the fusion constellation (server EvidenceSource). */
export interface FusionSource {
  name: string;
  score: number;
  weight: number;
  confidence: number;
}

export interface FusionView {
  sources: FusionSource[];
  fusedScore: number;
  fusedConfidence: number;
  dominantSource: string | null;
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

function finite(v: unknown, fallback = 0): number {
  return typeof v === 'number' && Number.isFinite(v) ? v : fallback;
}

function clamp01(v: number): number {
  return v < 0 ? 0 : v > 1 ? 1 : v;
}

function emptyFusion(): FusionView {
  return { sources: [], fusedScore: 0, fusedConfidence: 0, dominantSource: null };
}

/** Extract fusion sources + verdict from AssessmentDetail.explanation. */
export function fusionFromExplanation(
  explanation: Record<string, unknown> | null | undefined,
): FusionView {
  const block = explanation?.evidence_fusion;
  if (!isRecord(block)) return emptyFusion();
  const raw: unknown[] = Array.isArray(block.sources) ? block.sources : [];
  const sources: FusionSource[] = [];
  for (const entry of raw) {
    if (!isRecord(entry) || typeof entry.name !== 'string' || entry.name === '') continue;
    sources.push({
      name: entry.name,
      score: clamp01(finite(entry.score)),
      weight: finite(entry.weight),
      confidence: clamp01(finite(entry.confidence)),
    });
  }
  return {
    sources,
    fusedScore: clamp01(finite(block.fused_score)),
    fusedConfidence: clamp01(finite(block.fused_confidence)),
    dominantSource: typeof block.dominant_source === 'string' ? block.dominant_source : null,
  };
}

/** Robust intensity z-score for the residual gauge; null = no baseline. */
export function intensityZ(
  residuals: Record<string, unknown> | null | undefined,
): number | null {
  const v = residuals?.intensity_z;
  return typeof v === 'number' && Number.isFinite(v) ? v : null;
}

/** Spatial novelty flag (the server sends a real boolean inside residuals). */
export function isNewZone(
  residuals: Record<string, unknown> | null | undefined,
): boolean {
  return residuals?.is_new_zone === true;
}

export interface Envelope {
  lo: number;
  hi: number;
  baselineKnown: boolean;
}

/**
 * Normal envelope for the FRP stream, in log1p space. Uses the facility
 * p10/p90 band when the API exposes one; otherwise falls back to the data
 * IQR and the chart says so — it never invents a baseline it doesn't have.
 */
export function frpEnvelope(
  logFrps: number[],
  expectedP10?: number | null,
  expectedP90?: number | null,
): Envelope {
  const sorted = [...logFrps].sort((a, b) => a - b);
  const q = (p: number): number =>
    sorted.length === 0
      ? 0
      : sorted[Math.min(sorted.length - 1, Math.floor(p * sorted.length))];
  if (expectedP10 != null && expectedP90 != null) {
    let lo = Math.log1p(Math.max(expectedP10, 0));
    let hi = Math.log1p(Math.max(expectedP90, 0));
    if (lo > hi) {
      const t = lo;
      lo = hi;
      hi = t;
    }
    return { lo, hi, baselineKnown: true };
  }
  return { lo: q(0.25), hi: q(0.75), baselineKnown: false };
}

/** 24-bin detection histogram for the temporal dial. */
export function hourHistogram(hours: number[]): number[] {
  const counts = Array.from({ length: 24 }, () => 0);
  for (const h of hours) {
    if (!Number.isFinite(h)) continue;
    counts[((Math.floor(h) % 24) + 24) % 24] += 1;
  }
  return counts;
}

/** Night window used by the dial: 18:00–05:59 (diurnal flare read). */
export function isNightHour(hour: number): boolean {
  const h = ((Math.floor(hour) % 24) + 24) % 24;
  return h >= 18 || h < 6;
}

/**
 * Reduced-motion probe shared by every instrument (implementation lives in
 * lib/runtime so non-dossier surfaces don't import dossier internals).
 * Node-safe for vitest.
 */
export { prefersReducedMotion } from '@/lib/runtime/motion';
