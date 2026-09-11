import { cfg } from './config';
import { fetchFirms, toEpochMs, type FirmsRaw } from './firmsClient';
import { simBatch } from './simulator';
import { publish } from './publisher';

console.log(`[ingest] bun ${Bun.version} | target ${cfg.apiUrl} | mode ${cfg.firmsKey ? 'FIRMS-LIVE' : 'SIM'}`);

const seen = new Set<string>();
const toPayload = (r: FirmsRaw & { _ts?: number }) => ({
  latitude: r.latitude, longitude: r.longitude, frp: r.frp, bright_ti4: r.bright_ti4,
  confidence: r.confidence, satellite: r.satellite, daynight: r.daynight,
  acq_epoch_ms: r._ts ?? toEpochMs(r),
});

async function poll() {
  let rows: (FirmsRaw & { _ts?: number })[] = [];
  if (cfg.firmsKey) {
    try {
      rows = [...await fetchFirms('VIIRS_SNPP_NRT'), ...await fetchFirms('MODIS_NRT')]
        .filter((r) => !seen.has(`${r.latitude},${r.longitude},${r.acq_date},${r.acq_time}`));
      rows.forEach((r) => seen.add(`${r.latitude},${r.longitude},${r.acq_date},${r.acq_time}`));
    } catch (e) {
      console.warn('[ingest] FIRMS fetch failed, sim fallback:', (e as Error).message);
      rows = simBatch();
    }
  } else rows = simBatch();
  if (rows.length === 0) return;
  const { sent, queued } = await publish(rows.map(toPayload));
  if (sent > 0) console.log(`[ingest] published ${sent} detection(s) -> accepted`);
  else console.warn(`[ingest] API unreachable | ${queued} detection(s) queued (retrying next poll)`);
}

await poll();
// GH-Actions cron mode: one batch, then exit (free keep-warm + ingest cadence).
if (cfg.singleShot) process.exit(0);
setInterval(poll, cfg.pollMs);

