/** Standalone FIRMS key self-test: bun run src/firmsTest.ts (or npm script firms:test).
 *  Prints the archive-edge row count for the India bbox; exits 1 on auth errors or empty archive. */
import { cfg } from './config';

if (!cfg.firmsKey) {
  console.error('[firms-test] FIRMS_API_KEY is not set — put it in server/ingest/.env');
  process.exit(1);
}

const iso = (d: Date) => d.toISOString().slice(0, 10);
let ok = false;
for (const back of [1, 8, 15]) {
  const dayEnd = iso(new Date(Date.now() - back * 86_400_000));
  const url = `https://firms.modaps.eosdis.nasa.gov/api/area/csv/${cfg.firmsKey}/VIIRS_SNPP_NRT/${cfg.bbox}/5/${dayEnd}`;
  const res = await fetch(url);
  if (res.status === 401 || res.status === 403 || res.status === 429) {
    console.error(`[firms-test] key rejected: HTTP ${res.status}`);
    process.exit(1);
  }
  const text = await res.text();
  const rows = text.trim().split('\n').length - 1;
  console.log(`[firms-test] day_end=${dayEnd} → HTTP ${res.status} · ${rows} detection row(s)`);
  if (res.ok && rows > 0) {
    console.log(`[firms-test] first row: ${text.trim().split('\n')[1]}`);
    console.log(`[firms-test] PASS — key live (archive edge ≈ ${dayEnd})`);
    ok = true;
    break;
  }
}
process.exit(ok ? 0 : 1);