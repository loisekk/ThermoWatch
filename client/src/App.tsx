import { useKeyboardShortcuts } from '@/hooks/useKeyboardShortcuts';
import { useSimulationFeed } from '@/hooks/useSimulationFeed';
import { useBackendFeed } from '@/hooks/useBackendFeed';
import { useDeepLink } from '@/hooks/useDeepLink';
import { AppShell } from '@/components/layout/AppShell';

export default function App() {
  useKeyboardShortcuts();
  useSimulationFeed();   // local demo feed
  useBackendFeed();      // upgrades to FastAPI WS feed when backend is live
  useDeepLink();         // /app.html?vp=&panel=&lat=&lon= (landing bridge)
  return <AppShell />;
}

