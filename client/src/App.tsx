import { useKeyboardShortcuts } from '@/hooks/useKeyboardShortcuts';
import { useSimulationFeed } from '@/hooks/useSimulationFeed';
import { useBackendFeed } from '@/hooks/useBackendFeed';
import { AppShell } from '@/components/layout/AppShell';

export default function App() {
  useKeyboardShortcuts();
  useSimulationFeed();   // local demo feed
  useBackendFeed();      // upgrades to FastAPI WS feed when backend is live
  return <AppShell />;
}

