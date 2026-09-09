/** DuckDB-WASM runtime: in-browser columnar SQL over the live event feed.
 *  WASM bundles load from jsDelivr CDN (canonical duckdb-wasm browser pattern) —
 *  no local bundle files to host. Initialised lazily when Advanced Mode turns on. */
import * as duckdb from '@duckdb/duckdb-wasm';
import type { AsyncDuckDB, AsyncDuckDBConnection } from '@duckdb/duckdb-wasm';
import type { FireEvent, Facility } from '@/types/domain';
import {
  FACILITIES_DDL, FIRES_DDL, buildFacilityInsertSql, buildFacilityStatsSql,
  buildFireInsertSql, buildHexDensitySql, buildNearFacilitySql, buildTimeRangeSql,
  rowToFireEvent,
} from './duckdbSql';

let db: AsyncDuckDB | null = null;
let conn: AsyncDuckDBConnection | null = null;
let workerUrl: string | null = null;

/** Instantiate DuckDB-WASM (idempotent). */
export async function initDuckDB(): Promise<void> {
  if (db) return;
  const bundle = await duckdb.selectBundle(duckdb.getJsDelivrBundles());
  // importScripts shim so the CDN-hosted worker works cross-origin.
  workerUrl = URL.createObjectURL(
    new Blob([`importScripts("${bundle.mainWorker}");`], { type: 'text/javascript' }),
  );
  const worker = new Worker(workerUrl);
  const logger = new duckdb.ConsoleLogger(duckdb.LogLevel.WARNING);
  db = new duckdb.AsyncDuckDB(logger, worker);
  await db.instantiate(bundle.mainModule);
  conn = await db.connect();
  await conn.query(FIRES_DDL);
  await conn.query(FACILITIES_DDL);
}

/** Re-sync the tables with the current store contents (idempotent, cheap at ≤2k rows). */
export async function syncDuckDB(events: FireEvent[], facilities: Facility[]): Promise<void> {
  await initDuckDB();
  await conn!.query('DELETE FROM fires;');
  await conn!.query('DELETE FROM facilities;');
  const fireSql = buildFireInsertSql(events);
  if (fireSql) await conn!.query(fireSql);
  const facSql = buildFacilityInsertSql(facilities);
  if (facSql) await conn!.query(facSql);
}

export function isDuckDBReady(): boolean {
  return conn !== null;
}

/** Fires within a time window, newest first. */
export async function queryFiresByTime(startMs: number, endMs: number): Promise<FireEvent[]> {
  if (!conn) throw new Error('DuckDB not initialized');
  const result = await conn.query(buildTimeRangeSql(startMs, endMs));
  return result.toArray().map((row) => rowToFireEvent(row as Record<string, unknown>));
}

/** Fires near their nearest facility within a radius (optionally hazard-filtered). */
export async function queryFiresNearFacilities(
  radiusKm: number,
  facilityHazard?: string,
): Promise<{ fireId: string; facilityName: string; distanceKm: number }[]> {
  if (!conn) throw new Error('DuckDB not initialized');
  const result = await conn.query(buildNearFacilitySql(radiusKm, facilityHazard));
  return result.toArray().map((row) => {
    const r = row as Record<string, unknown>;
    return {
      fireId: String(r.fire_id),
      facilityName: String(r.facility_name),
      distanceKm: Number(r.distance_km),
    };
  });
}

/** Grid-cell density aggregation (hexId, centroid, count, mean FRP). */
export async function queryHexDensity(
  hexSize = 0.01,
): Promise<{ hexId: string; lat: number; lon: number; count: number; avgFrp: number }[]> {
  if (!conn) throw new Error('DuckDB not initialized');
  const result = await conn.query(buildHexDensitySql(hexSize));
  return result.toArray().map((row) => {
    const r = row as Record<string, unknown>;
    return {
      hexId: String(r.hex_id),
      lat: Number(r.lat),
      lon: Number(r.lon),
      count: Number(r.count),
      avgFrp: Number(r.avg_frp),
    };
  });
}

/** Per-subtype event counts + mean risk. */
export async function queryFacilityStats(): Promise<{ subtype: string; count: number; avgRisk: number }[]> {
  if (!conn) throw new Error('DuckDB not initialized');
  const result = await conn.query(buildFacilityStatsSql());
  return result.toArray().map((row) => {
    const r = row as Record<string, unknown>;
    return {
      subtype: String(r.subtype),
      count: Number(r.count),
      avgRisk: Number(r.avg_risk),
    };
  });
}

/** Tear down the WASM instance (used on hot unmount / tests). */
export async function closeDuckDB(): Promise<void> {
  if (conn) {
    await conn.close();
    conn = null;
  }
  if (db) {
    await db.terminate();
    db = null;
  }
  if (workerUrl) {
    URL.revokeObjectURL(workerUrl);
    workerUrl = null;
  }
}
