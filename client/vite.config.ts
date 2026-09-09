import { fileURLToPath, URL } from 'node:url';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: { port: 5173 },
  build: {
    // three.js (globe) and MapLibre (2D) are irreducibly large; they are split
    // into lazy chunks below, so only raise the warning floor to match reality.
    chunkSizeWarningLimit: 2100,
    rollupOptions: {
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

