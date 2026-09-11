import { useEffect } from 'react';
import { TopBar } from './TopBar';
import { SideRail } from './SideRail';
import { StatusTicker } from './StatusTicker';
import { ViewStage } from '@/components/views/ViewStage';
import { RightDock } from '@/components/panels/RightDock';
import { EventDrawer } from '@/components/detail/EventDrawer';
import { Scene3DViewer } from '@/components/detail/Scene3DViewer';
import { FacilityDrawer } from '@/features/facility/FacilityDrawer';
import { useFireStore } from '@/store/useFireStore';

export function AppShell() {
  const hydrate = useFireStore((s) => s.hydrate);
  useEffect(() => { hydrate(); }, [hydrate]);

  return (
    <div className="grid h-full grid-rows-[auto_1fr_auto] grid-cols-[auto_1fr]">
      <div className="col-span-2"><TopBar /></div>
      <SideRail />
      <main className="relative flex min-h-0">
        <ViewStage />
        <RightDock />
      </main>
      <div className="col-span-2"><StatusTicker /></div>
      <EventDrawer />
      <FacilityDrawer />
      <Scene3DViewer />
    </div>
  );
}
