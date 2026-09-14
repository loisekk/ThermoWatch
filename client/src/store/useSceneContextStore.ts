/** Scene context cache shared between Scene3DViewer (fetcher) and EventDrawer
 *  (provenance section). `nearest` is the top-FRP-hotspot -> closest REAL OSM
 *  building distance used for the anti-confusion callout sprite + drawer line. */
import { create } from 'zustand';
import type { OsmBuildingKind, SceneContext } from '@/features/scene/osmScene';

export interface NearestOsmBuilding {
  m: number;
  id: number;
  kind: OsmBuildingKind;
}

interface SceneContextState {
  eventId: string | null;
  context: SceneContext | null;
  nearest: NearestOsmBuilding | null;
  loading: boolean;
  refreshKey: number;
  /** Viewer-owned update (the viewer owns the abortable fetch lifecycle). */
  setCtx: (k: Partial<Pick<SceneContextState, 'eventId' | 'context' | 'nearest' | 'loading'>>) => void;
  bumpRefresh: () => void;
}

export const useSceneContextStore = create<SceneContextState>()((set) => ({
  eventId: null,
  context: null,
  nearest: null,
  loading: false,
  refreshKey: 0,
  setCtx: (k) => set(k),
  bumpRefresh: () => set((s) => ({ refreshKey: s.refreshKey + 1 })),
}));