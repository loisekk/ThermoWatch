import { useEffect } from 'react';
import { useFireStore } from '@/store/useFireStore';
import { useUIStore } from '@/store/useUIStore';

/** True when the event originates from a text-entry surface — shortcuts must stay silent there. */
export function isTypingTarget(e: KeyboardEvent): boolean {
  const t = e.target as HTMLElement | null;
  if (!t || typeof t.tagName !== 'string') return false;
  const tag = t.tagName.toLowerCase();
  return tag === 'input' || tag === 'textarea' || tag === 'select' || t.isContentEditable === true;
}

/** 1/2 viewport · space hold feed · o/p/a/f/g/m/k/x/h panels · t self-test · esc close.
 *  NEVER fires while the user is typing (agent chat, forms, search boxes). */
export function useKeyboardShortcuts(): void {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.isComposing || isTypingTarget(e)) return;
      const ui = useUIStore.getState();
      const fire = useFireStore.getState();
      switch (e.key) {
        case '1': ui.setViewMode('2d'); break;
        case '2': ui.setViewMode('3d'); break;
        case ' ': e.preventDefault(); fire.togglePause(); break;
        case 'Escape': fire.select(null); fire.selectFacility(null); break;
        case 'o': ui.setPanel('overview'); break;
        case 'p': ui.setPanel('persistence'); break;
        case 'a': ui.setPanel('alerts'); break;
        case 'f': ui.setPanel('facilities'); break;
        case 'g': ui.setPanel('agent'); break;
        case 'm': ui.setPanel('predict'); break;
        case 'k': ui.setPanel('model'); break;
        case 'x': ui.setPanel('analytics'); break;
        case 'h': ui.setPanel('history'); break;
        case 't': ui.toggleSelfTest(); break;
        default: break;
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);
}
