/**
 * Risk/code adapter tests (vitest node env — full typed fixtures, no casts).
 */
import { describe, expect, it } from 'vitest';
import type { AssessmentSummary, AssessmentStatus, IncidentSummary } from '@/services/api/v2Types';
import {
  RISK_ORDER,
  countByClass,
  countByRisk,
  deriveRiskLevel,
  incidentCode,
  topClass,
} from '../incidentDisplay';

function asm(status: AssessmentStatus, top_class = 'refinery'): AssessmentSummary {
  return {
    id: 'asm-1',
    assessment_version: 'v1',
    assessed_at: '2026-09-22T12:00:00Z',
    status,
    top_class,
    top_confidence: 0.8,
    activity_state: 'persistent',
    abstain_reason: null,
  };
}

function inc(over: Partial<IncidentSummary> = {}): IncidentSummary {
  return {
    id: 'a1b2c3d4-0000-0000-0000-000000000000',
    status: 'needs_review',
    version: 1,
    centroid_latitude: 22.47,
    centroid_longitude: 70.07,
    first_seen_at: '2026-09-20T10:00:00Z',
    last_seen_at: '2026-09-22T14:00:00Z',
    observation_count: 5,
    current_assessment: null,
    days_active: 2,
    ...over,
  };
}

describe('deriveRiskLevel', () => {
  it('escalated disposition is always HIGH — even over a normal assessment', () => {
    expect(deriveRiskLevel(inc({ status: 'escalated' }))).toBe('high');
    expect(deriveRiskLevel(inc({ status: 'escalated', current_assessment: asm('normal') }))).toBe('high');
  });

  it('an abnormal assessment is HIGH', () => {
    expect(deriveRiskLevel(inc({ current_assessment: asm('abnormal') }))).toBe('high');
  });

  it('insufficient evidence is MEDIUM — never LOW (abstention is not safety)', () => {
    expect(deriveRiskLevel(inc({ current_assessment: asm('insufficient_evidence') }))).toBe('medium');
  });

  it('an assessed normal incident is LOW', () => {
    expect(deriveRiskLevel(inc({ current_assessment: asm('normal') }))).toBe('low');
    expect(deriveRiskLevel(inc({ status: 'reviewed', current_assessment: asm('normal') }))).toBe('low');
    expect(deriveRiskLevel(inc({ status: 'dismissed', current_assessment: asm('normal') }))).toBe('low');
  });

  it('no assessment is UNKNOWN (nothing is claimed either way)', () => {
    expect(deriveRiskLevel(inc())).toBe('unknown');
  });
});

describe('incidentCode', () => {
  it('formats a UUID as #TW-XXXX deterministically', () => {
    expect(incidentCode('a1b2c3d4-eeee-ffff-0000-1234567890ab')).toBe('#TW-A1B2');
    expect(incidentCode('a1b2c3d4-eeee-ffff-0000-1234567890ab')).toBe(
      incidentCode('a1b2c3d4-eeee-ffff-0000-1234567890ab'),
    );
  });

  it('always yields the #TW- plus 4 hex-char shape', () => {
    for (const id of ['deadbeef-0000-0000-0000-000000000000', '0f7c1a2b-3c4d-5e6f-7a8b-9c0d1e2f3a4b']) {
      expect(incidentCode(id)).toMatch(/^#TW-[0-9A-F]{4}$/);
    }
    expect(incidentCode('deadbeef-0000-0000-0000-000000000000')).toBe('#TW-DEAD');
  });
});

describe('topClass', () => {
  it('reads the latest assessment class', () => {
    expect(topClass(inc({ current_assessment: asm('abnormal', 'gas_flare') }))).toBe('gas_flare');
  });

  it('falls back to "unassessed" when nothing has been assessed', () => {
    expect(topClass(inc())).toBe('unassessed');
  });
});

describe('countByRisk', () => {
  it('tallies every incident exactly once', () => {
    const list = [
      inc({ id: 'i1', status: 'escalated' }),
      inc({ id: 'i2', current_assessment: asm('abnormal') }),
      inc({ id: 'i3', current_assessment: asm('insufficient_evidence') }),
      inc({ id: 'i4', current_assessment: asm('normal') }),
      inc({ id: 'i5' }),
    ];
    const counts = countByRisk(list);
    expect(counts).toEqual({ high: 2, medium: 1, low: 1, unknown: 1 });
    expect(RISK_ORDER.reduce((s, r) => s + counts[r], 0)).toBe(list.length);
  });

  it('is all zeros for an empty feed', () => {
    expect(countByRisk([])).toEqual({ high: 0, medium: 0, low: 0, unknown: 0 });
  });
});

describe('countByClass', () => {
  it('sorts most frequent first and buckets unassessed incidents', () => {
    const counts = countByClass([
      inc({ id: 'i1', current_assessment: asm('normal', 'refinery') }),
      inc({ id: 'i2', current_assessment: asm('abnormal', 'refinery') }),
      inc({ id: 'i3', current_assessment: asm('normal', 'gas_flare') }),
      inc({ id: 'i4' }),
    ]);
    expect([...counts.entries()]).toEqual([
      ['refinery', 2],
      ['gas_flare', 1],
      ['unassessed', 1],
    ]);
  });
});
