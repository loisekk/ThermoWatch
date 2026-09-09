import { useEffect } from 'react';
import { TICK_MS } from '@/config/constants';
import { useFireStore } from '@/store/useFireStore';

/** Drives the simulated NRT ingestion loop. */
export function useSimulationFeed(): void {
  const tick = useFireStore((s) => s.tick);
  useEffect(() => {
    const id = window.setInterval(tick, TICK_MS);
    return () => window.clearInterval(id);
  }, [tick]);
}
