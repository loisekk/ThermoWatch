import { Activity, AlertOctagon, Award, BarChart3, BellRing, Bot, BrainCircuit, Clock3, Factory, Globe2, History, Radio } from 'lucide-react';
import { useUIStore, type PanelKey } from '@/store/useUIStore';
import { cn } from '@/lib/utils/cn';

const ITEMS: { key: PanelKey; icon: typeof Activity; label: string; hint: string }[] = [
  { key: 'global-watch', icon: Globe2, label: 'Global Watch', hint: 'O' },
  { key: 'queue', icon: AlertOctagon, label: 'Incident Queue', hint: 'Q' },
  { key: 'overview', icon: Activity, label: 'Overview', hint: '⇧O' },
  { key: 'persistence', icon: History, label: 'Persistence', hint: 'P' },
  { key: 'alerts', icon: BellRing, label: 'Alerts', hint: 'A' },
  { key: 'facilities', icon: Factory, label: 'Facilities', hint: 'F' },
  { key: 'agent', icon: Bot, label: 'AI Agent', hint: 'G' },
  { key: 'predict', icon: BrainCircuit, label: 'Model Run', hint: 'M' },
  { key: 'model', icon: Award, label: 'Model Card', hint: 'K' },
  { key: 'analytics', icon: BarChart3, label: 'Analytics', hint: 'X' },
  { key: 'history', icon: Clock3, label: 'History', hint: 'H' },
  { key: 'news', icon: Radio, label: 'Live wire', hint: 'N' },
];

export function SideRail() {
  const { panel, setPanel } = useUIStore();
  return (
    <nav aria-label="Workspaces" className="flex w-14 flex-col items-center gap-1 border-r border-edge bg-abyss py-3">
      {ITEMS.map(({ key, icon: Icon, label, hint }) => (
        <button key={key} onClick={() => setPanel(key)} title={`${label} (${hint})`} aria-current={panel === key}
          className={cn('relative grid h-10 w-10 place-items-center rounded-sm transition-colors',
            panel === key ? 'bg-ember/15 text-ember' : 'text-dim hover:bg-panel2 hover:text-ink')}>
          <Icon className="h-4.5 w-4.5" />
          {panel === key && <span className="absolute left-0 top-1/2 h-5 w-0.5 -translate-y-1/2 bg-ember" />}
        </button>
      ))}
    </nav>
  );
}


