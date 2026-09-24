/**
 * Pure display adapters for the Global Watch deck — risk level, incident code
 * and the counts the rail renders. No React, no DOM (node-testable).
 *
 * Risk colors come from the mission-console theme so the globe, the queue's
 * disposition spines and the dossier's abstain banner all agree: uncertainty
 * is amber, never green.
 */
import type { IncidentSummary } from '@/services/api/v2Types';

export type RiskLevel = 'high' | 'medium' | 'low' | 'unknown';

export interface RiskMeta {
  label: string;
  /** Blip / chip color (theme token hex). */
  color: string;
  /** Translucent halo used for the static blip ring. */
  ring: string;
}

export const RISK_META: Record<RiskLevel, RiskMeta> = {
  high: { label: 'HIGH', color: '#ff4444', ring: 'rgba(255,68,68,0.45)' },
  medium: { label: 'MEDIUM', color: '#ffb800', ring: 'rgba(255,184,0,0.45)' },
  low: { label: 'LOW', color: '#3fb950', ring: 'rgba(63,185,80,0.35)' },
  unknown: { label: 'UNKNOWN', color: '#5b6b7d', ring: 'rgba(91,107,125,0.35)' },
};

/** Render order for distribution bars (most severe first). */
export const RISK_ORDER: RiskLevel[] = ['high', 'medium', 'low', 'unknown'];

/**
 * Escalated/abnormal → HIGH; uncertainty → MEDIUM (never LOW — abstention is
 * not safety); assessed normal → LOW; nothing assessed → UNKNOWN.
 * Mirrors the queue's disposition semantics.
 */
export function deriveRiskLevel(incident: IncidentSummary): RiskLevel {
  const asm = incident.current_assessment;
  if (incident.status === 'escalated') return 'high';
  if (!asm) return 'unknown';
  if (asm.status === 'abnormal') return 'high';
  if (asm.status === 'insufficient_evidence') return 'medium';
  return 'low'; // assessed normal
}

/** UUID → "#TW-2847" style code, deterministic (first 4 hex of the id). */
export function incidentCode(id: string): string {
  return `#TW-${id.replace(/-/g, '').slice(0, 4).toUpperCase()}`;
}

export function topClass(incident: IncidentSummary): string {
  return incident.current_assessment?.top_class ?? 'unassessed';
}

/** Risk tally in RISK_ORDER order. */
export function countByRisk(incidents: IncidentSummary[]): Record<RiskLevel, number> {
  const counts: Record<RiskLevel, number> = { high: 0, medium: 0, low: 0, unknown: 0 };
  for (const i of incidents) counts[deriveRiskLevel(i)] += 1;
  return counts;
}

/** `top_class` tally, most frequent first (ties keep first-seen order). */
export function countByClass(incidents: IncidentSummary[]): Map<string, number> {
  const counts = new Map<string, number>();
  for (const i of incidents) {
    const c = topClass(i);
    counts.set(c, (counts.get(c) ?? 0) + 1);
  }
  return new Map([...counts.entries()].sort((a, b) => b[1] - a[1]));
}
