import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import { Providers } from '@/app/providers';
import { installRafShimIfDead } from '@/lib/runtime/rafShim';
import './styles/globals.css';
import 'maplibre-gl/dist/maplibre-gl.css';

function boot() {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <Providers>
        <App />
      </Providers>
    </StrictMode>,
  );
}

// Must run BEFORE React mounts so lazy viewport engines capture the shimmed rAF.
// Costs ~1 frame on healthy hosts; ~400 ms once, only on rAF-dead hosts.
installRafShimIfDead().then(boot, boot);
