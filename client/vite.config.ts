import { fileURLToPath, URL } from 'node:url';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

// Where the dev proxy forwards API traffic (uvicorn). 127.0.0.1, NOT localhost:
// uvicorn binds IPv4 by default and on Windows `localhost` can resolve to ::1 —
// that mismatch surfaces as a browser "Failed to fetch" even when the API is up.
const API_PROXY = process.env.TW_API_PROXY ?? 'http://127.0.0.1:8000';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
    // CRITICAL: globe.gl ships a nested three.js copy; two three instances in one
    // page crash the GL render loop ("intersectsFrustum is not a function" in
    // projectObject) and paint the 3D orb black. Dedupe every three import to the
    // single top-level copy.
    dedupe: ['three'],
  },
  server: {
    port: 5173,
    // Same-origin dev mode: the browser only ever talks to localhost:5173 and
    // Vite forwards /api, /v2 and /health to uvicorn — no CORS round-trip, so
    // the classic "Failed to fetch" (preflight/connection class) cannot happen.
    // ws:true proxies the WebSocket upgrades (/v2/stream, /api/v1/ws/live).
    // Vite reads proxy config at startup only — restart `npm run dev` after edits.
    proxy: {
      '/api': { target: API_PROXY, changeOrigin: true, ws: true },
      '/v2': { target: API_PROXY, changeOrigin: true, ws: true },
      '/health': { target: API_PROXY, changeOrigin: true },
    },
  },
  build: {
    // three.js (globe) and MapLibre (2D) are irreducibly large; they are split
    // into lazy chunks below, so only raise the warning floor to match reality.
    chunkSizeWarningLimit: 2100,
    rollupOptions: {
      input: {
        landing: fileURLToPath(new URL('./index.html', import.meta.url)),
        app: fileURLToPath(new URL('./app.html', import.meta.url)),
      },
      output: {
        // Split the heavy geo/3D/UI vendors so the console shell stays a small
        // fast first paint; each chunk is cached independently by the browser.
        manualChunks(id) {
          if (id.includes('world-110m.json')) return 'world-geo';
          if (id.includes('node_modules')) {
            if (id.includes('three') || id.includes('globe.gl')) return 'globe-3d';
            if (id.includes('maplibre')) return 'map-2d';
            if (id.includes('@mui') || id.includes('@emotion')) return 'mui';
            if (id.includes('lucide')) return 'icons';
          }
        },
      },
    },
  },
});

