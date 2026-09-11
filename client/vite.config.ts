import { fileURLToPath, URL } from 'node:url';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

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
  server: { port: 5173 },
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

