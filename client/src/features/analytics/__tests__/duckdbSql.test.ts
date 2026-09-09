import { describe, expect, it } from 'vitest';
import {
  buildFacilityInsertSql, buildFacilityStatsSql, buildFireInsertSql, buildHexDensitySql,
  buildNearFacilitySql, buildTimeRangeSql, rowToFireEvent, sqlStr,
} from '@/features/analytics/duckdbSql';
import type { FireEvent, Facility } from '@/types/domain';

const event: FireEvent = {
  id: 'TW-00042', lat: 22.47, lon: 70.06, frp: 480.5, brightnessK: 341.2, confidence: 85,
  detectedAt: 1_750_000_000_000, satellite: 'VIIRS-SNPP', dayNight: 'N',
  classification: { primary: 'industrial', subtype: 'refinery', scores: { industrial: 1, persistent: 0, wildfire: 0, agricultural: 0 }, confidence: 85 },
  persistence: { consecutiveDays: 6, detections30d: 18, regime: 'persistent' },
  risk: { score: 78, level: 'high', drivers: [] },
  nearestFacilityId: 'F-001', facilityDistanceKm: 0.42,
};

const facility: Facility = {
  id: 'F-001', name: "O'Brien Refinery", subtype: 'refinery', lat: 22.47, lon: 70.06, hazard: 'G-III',
};

describe('sqlStr', () => {
  it('escapes single quotes (no SQL injection via facility names)', () => {
    expect(sqlStr("O'Brien")).toBe("'O''Brien'");
  });
});

describe('insert builders', () => {
  it('builds one VALUES tuple per event with NULL handling', () => {
    const sql = buildFireInsertSql([{ ...event, classification: { ...event.classification, subtype: null }, facilityDistanceKm: null }]);
    expect(sql.startsWith('INSERT INTO fires VALUES (')).toBe(true);
    expect(sql).toContain("'TW-00042'");
    expect(sql).toContain("'industrial', NULL,"); // NULL subtype
    expect(sql.endsWith('NULL);')).toBe(true);     // NULL facility distance (last column)
  });

  it('returns empty string for empty batches', () => {
    expect(buildFireInsertSql([])).toBe('');
    expect(buildFacilityInsertSql([])).toBe('');
  });

  it('escapes quotes in facility inserts', () => {
    const sql = buildFacilityInsertSql([facility]);
    expect(sql).toContain("'O''Brien Refinery'");
  });
});

describe('query builders', () => {
  it('time-range SQL is inclusive on both ends', () => {
    const sql = buildTimeRangeSql(1000, 2000);
    expect(sql).toContain('detected_at >= 1000');
    expect(sql).toContain('detected_at <= 2000');
    expect(sql).toContain('ORDER BY detected_at DESC');
  });

  it('near-facility SQL filters radius and optional hazard', () => {
    expect(buildNearFacilitySql(5)).toContain('facility_distance_km <= 5');
    expect(buildNearFacilitySql(5, 'G-III')).toContain("fa.hazard = 'G-III'");
  });

  it('hex density SQL groups and filters sparse cells', () => {
    const sql = buildHexDensitySql(0.01);
    expect(sql).toContain('ROUND(lat / 0.01)');
    expect(sql).toContain('HAVING COUNT(*) >= 3');
  });

  it('facility stats SQL joins and aggregates', () => {
    expect(buildFacilityStatsSql()).toContain('AVG(fi.risk_score) AS avg_risk');
  });
});

describe('rowToFireEvent', () => {
  it('maps a snake_case DuckDB row into the FireEvent domain model', () => {
    const row = {
      id: 'TW-00042', lat: 22.47, lon: 70.06, frp: 480.5, brightness_k: 341.2,
      confidence: 85, detected_at: '1750000000000', satellite: 'VIIRS-SNPP', day_night: 'N',
      primary_class: 'industrial', subtype: null, persistence_regime: 'persistent',
      consecutive_days: 6, detections_30d: 18, risk_score: 78, risk_level: 'high',
      nearest_facility_id: 'F-001', facility_distance_km: 0.42,
    };
    const e = rowToFireEvent(row);
    expect(e.id).toBe('TW-00042');
    expect(e.brightnessK).toBeCloseTo(341.2);
    expect(e.detectedAt).toBe(1_750_000_000_000);
    expect(e.classification.primary).toBe('industrial');
    expect(e.classification.subtype).toBeNull();
    expect(e.persistence.regime).toBe('persistent');
    expect(e.risk.level).toBe('high');
    expect(e.facilityDistanceKm).toBeCloseTo(0.42);
  });

  it('handles NULL facility context', () => {
    const e = rowToFireEvent({ ...({ id: 'x', lat: 0, lon: 0, frp: 0, brightness_k: 0, confidence: 0, detected_at: 0, satellite: 'MODIS', day_night: 'D', primary_class: 'wildfire', subtype: null, persistence_regime: 'transient', consecutive_days: 1, detections_30d: 1, risk_score: 10, risk_level: 'low', nearest_facility_id: null, facility_distance_km: null } as Record<string, unknown>) });
    expect(e.nearestFacilityId).toBeNull();
    expect(e.facilityDistanceKm).toBeNull();
  });
});
