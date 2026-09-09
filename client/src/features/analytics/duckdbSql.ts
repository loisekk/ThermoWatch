/** Pure SQL builders + row mappers for the DuckDB analytics engine.
 *  Kept free of any WASM/browser dependency so they are unit-testable in node. */
import type { FireEvent, Facility } from '@/types/domain';

/** Escape a string for a SQL single-quoted literal. */
export function sqlStr(v: string): string {
  return `'${v.replace(/'/g, "''")}'`;
}

export const FIRES_DDL = `
  CREATE TABLE IF NOT EXISTS fires (
    id VARCHAR, lat DOUBLE, lon DOUBLE, frp DOUBLE, brightness_k DOUBLE,
    confidence INTEGER, detected_at BIGINT, satellite VARCHAR, day_night VARCHAR,
    primary_class VARCHAR, subtype VARCHAR, persistence_regime VARCHAR,
    consecutive_days INTEGER, detections_30d INTEGER, risk_score INTEGER,
    risk_level VARCHAR, nearest_facility_id VARCHAR, facility_distance_km DOUBLE
  );`;

export const FACILITIES_DDL = `
  CREATE TABLE IF NOT EXISTS facilities (
    id VARCHAR, name VARCHAR, subtype VARCHAR, lat DOUBLE, lon DOUBLE, hazard VARCHAR
  );`;

export function buildFireInsertSql(events: FireEvent[]): string {
  if (events.length === 0) return '';
  const values = events.map((e) =>
    `(${sqlStr(e.id)}, ${e.lat}, ${e.lon}, ${e.frp}, ${e.brightnessK}, ${e.confidence}, ${e.detectedAt}, ` +
    `${sqlStr(e.satellite)}, ${sqlStr(e.dayNight)}, ${sqlStr(e.classification.primary)}, ` +
    `${e.classification.subtype ? sqlStr(e.classification.subtype) : 'NULL'}, ` +
    `${sqlStr(e.persistence.regime)}, ${e.persistence.consecutiveDays}, ${e.persistence.detections30d}, ` +
    `${e.risk.score}, ${sqlStr(e.risk.level)}, ` +
    `${e.nearestFacilityId ? sqlStr(e.nearestFacilityId) : 'NULL'}, ` +
    `${e.facilityDistanceKm !== null ? e.facilityDistanceKm : 'NULL'})`,
  );
  return `INSERT INTO fires VALUES ${values.join(', ')};`;
}

export function buildFacilityInsertSql(facilities: Facility[]): string {
  if (facilities.length === 0) return '';
  const values = facilities.map(
    (f) => `(${sqlStr(f.id)}, ${sqlStr(f.name)}, ${sqlStr(f.subtype)}, ${f.lat}, ${f.lon}, ${sqlStr(f.hazard)})`,
  );
  return `INSERT INTO facilities VALUES ${values.join(', ')};`;
}

export function buildTimeRangeSql(startMs: number, endMs: number): string {
  return `SELECT * FROM fires WHERE detected_at >= ${Math.floor(startMs)} AND detected_at <= ${Math.floor(endMs)} ORDER BY detected_at DESC`;
}

export function buildNearFacilitySql(radiusKm: number, facilityHazard?: string): string {
  const hazard = facilityHazard ? ` AND fa.hazard = ${sqlStr(facilityHazard)}` : '';
  return (
    `SELECT fi.id AS fire_id, fa.name AS facility_name, fi.facility_distance_km AS distance_km ` +
    `FROM fires fi JOIN facilities fa ON fi.nearest_facility_id = fa.id ` +
    `WHERE fi.facility_distance_km <= ${radiusKm}${hazard}`
  );
}

export function buildHexDensitySql(hexSize: number): string {
  // Grid-based hex approximation (H3 indexing is the upgrade path)
  return (
    `SELECT CAST(ROUND(lat / ${hexSize}) AS VARCHAR) || ':' || CAST(ROUND(lon / ${hexSize}) AS VARCHAR) AS hex_id, ` +
    `AVG(lat) AS lat, AVG(lon) AS lon, COUNT(*) AS count, AVG(frp) AS avg_frp ` +
    `FROM fires GROUP BY hex_id HAVING COUNT(*) >= 3`
  );
}

export function buildFacilityStatsSql(): string {
  return (
    `SELECT fa.subtype AS subtype, COUNT(*) AS count, AVG(fi.risk_score) AS avg_risk ` +
    `FROM fires fi JOIN facilities fa ON fi.nearest_facility_id = fa.id GROUP BY fa.subtype`
  );
}

/** Map a snake_case DuckDB row back into the FireEvent domain model. */
export function rowToFireEvent(row: Record<string, unknown>): FireEvent {
  return {
    id: String(row.id),
    lat: Number(row.lat),
    lon: Number(row.lon),
    frp: Number(row.frp),
    brightnessK: Number(row.brightness_k),
    confidence: Number(row.confidence),
    detectedAt: Number(row.detected_at),
    satellite: String(row.satellite) as FireEvent['satellite'],
    dayNight: String(row.day_night) as FireEvent['dayNight'],
    classification: {
      primary: String(row.primary_class) as FireEvent['classification']['primary'],
      subtype: (row.subtype as FireEvent['classification']['subtype']) || null,
      scores: { industrial: 0, persistent: 0, wildfire: 0, agricultural: 0 }, // full posterior not stored
      confidence: Number(row.confidence),
    },
    persistence: {
      consecutiveDays: Number(row.consecutive_days),
      detections30d: Number(row.detections_30d),
      regime: String(row.persistence_regime) as FireEvent['persistence']['regime'],
    },
    risk: {
      score: Number(row.risk_score),
      level: String(row.risk_level) as FireEvent['risk']['level'],
      drivers: [], // not stored
    },
    nearestFacilityId: (row.nearest_facility_id as string) || null,
    facilityDistanceKm: row.facility_distance_km === null || row.facility_distance_km === undefined ? null : Number(row.facility_distance_km),
  };
}
