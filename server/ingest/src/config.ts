export const cfg = {
  apiUrl: process.env.TW_API_URL ?? 'http://localhost:8000',
  firmsKey: process.env.VITE_FIRMS_API_KEY ?? process.env.FIRMS_API_KEY ?? '',
  pollMs: Number(process.env.POLL_MS ?? 20_000),
  ingestToken: process.env.TW_INGEST_TOKEN ?? '',
  singleShot: process.env.SINGLE_SHOT === '1',
  areaCode: '3', // India
} as const;
