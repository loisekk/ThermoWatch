import { useEffect } from 'react';
import { useFireStore } from '@/store/useFireStore';
import { useUIStore } from '@/store/useUIStore';

/** 1/2 viewport · space hold feed · o/p/a/f/g/m/k panels · esc close drawer */
export function useKeyboardShortcuts(): void {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const ui = useUIStore.getState();
      const fire = useFireStore.getState();
      switch (e.key) {
        case '1': ui.setViewMode('2d'); break;
        case '2': ui.setViewMode('3d'); break;
        case ' ': e.preventDefault(); fire.togglePause(); break;
        case 'Escape': fire.select(null); break;
        case 'o': ui.setPanel('overview'); break;
        case 'p': ui.setPanel('persistence'); break;
        case 'a': ui.setPanel('alerts'); break;
        case 'f': ui.setPanel('facilities'); break;
        case 'g': ui.setPanel('agent'); break;
        case 'm': ui.setPanel('predict'); break;
        case 'k': ui.setPanel('model'); break;
        case 'x': ui.setPanel('analytics'); break;
        default: break;
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);
}
