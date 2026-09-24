import { Suspense, lazy, useEffect } from 'react';
import { TopBar } from './TopBar';
import { SideRail } from './SideRail';
import { StatusTicker } from './StatusTicker';
import { ViewStage } from '@/components/views/ViewStage';
import { RightDock } from '@/components/panels/RightDock';
import { EventDrawer } from '@/components/detail/EventDrawer';
import { Scene3DViewer } from '@/components/detail/Scene3DViewer';
import { FacilityDrawer } from '@/features/facility/FacilityDrawer';
import { QueueWorkspace } from '@/features/queue/QueueWorkspace';
// Lazy: the deck pulls the bundled world-geo chunk only when it is shown, so the
// console shell keeps its fast first paint (same pattern as the viewport engines).
const GlobalWatchWorkspace = lazy(() =>
  import('@/features/globalwatch/GlobalWatchWorkspace').then((m) => ({ default: m.GlobalWatchWorkspace })),
);
import { useUIStore } from '@/store/useUIStore';
import { useFireStore } from '@/store/useFireStore';

export function AppShell() {
  const hydrate = useFireStore((s) => s.hydrate);
  useEffect(() => { hydrate(); }, [hydrate]);
  // Full-width workspaces replace the map + dock region entirely: Global Watch
  // (the v2 landing deck) and the analyst queue. Everything else is map + dock.
  const panel = useUIStore((s) => s.panel);
  const workspace =
    panel === 'queue' ? (
      <QueueWorkspace />
    ) : panel === 'global-watch' ? (
      <GlobalWatchWorkspace />
    ) : null;

  return (
    <div className="grid h-full grid-rows-[auto_1fr_auto] grid-cols-[auto_1fr]">
      <div className="col-span-2"><TopBar /></div>
      <SideRail />
      {workspace ? (
        <main className="flex min-h-0 min-w-0 flex-col overflow-hidden bg-abyss">
          <Suspense
            fallback={
              <div className="mono flex h-full items-center justify-center text-[10px] uppercase tracking-widest text-dim">
                loading workspace…
              </div>
            }
          >
            {workspace}
          </Suspense>
        </main>
      ) : (
        <main className="relative flex min-h-0">
          <ViewStage />
          <RightDock />
        </main>
      )}
      <div className="col-span-2"><StatusTicker /></div>
      <EventDrawer />
      <FacilityDrawer />
      <Scene3DViewer />
    </div>
  );
}
