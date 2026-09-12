export const cfg = {
  apiUrl: process.env.TW_API_URL ?? 'http://localhost:8000',
  firmsKey: process.env.VITE_FIRMS_API_KEY ?? process.env.FIRMS_API_KEY ?? '',
  pollMs: Number(process.env.POLL_MS ?? 900_000),
  ingestToken: process.env.TW_INGEST_TOKEN ?? '',
  singleShot: process.env.SINGLE_SHOT === '1',
  bbox: '68,6,98,36', // India: west,south,east,north (FIRMS area endpoint wants a bbox, not a country code)
} as const;
