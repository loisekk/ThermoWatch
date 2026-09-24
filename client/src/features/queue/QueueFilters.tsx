/**
 * Queue filter toolbar — status chips + activity select. Persisted in the
 * queue store (UI state only; server state belongs to TanStack Query).
 */
import { useQueueStore } from '@/store/useQueueStore';
import type { ActivityState, Disposition } from '@/services/api/v2Types';

const STATUSES: (Disposition | 'all')[] = [
  'needs_review', 'reviewed', 'escalated', 'dismissed', 'all',
];
const ACTIVITIES: (ActivityState | 'all')[] = [
  'all', 'acute', 'recurring', 'persistent', 'changing', 'insufficient_history',
];

export function QueueFilters() {
  const filters = useQueueStore((s) => s.filters);
  const setFilters = useQueueStore((s) => s.setFilters);
  const resetFilters = useQueueStore((s) => s.resetFilters);

  return (
    <div className="flex flex-wrap items-center gap-2" role="toolbar" aria-label="Queue filters">
      <div className="flex flex-wrap gap-1" role="group" aria-label="Filter by status">
        {STATUSES.map((s) => {
          const on = filters.status === s;
          return (
            <button
              key={s}
              type="button"
              aria-pressed={on}
              onClick={() => setFilters({ status: s })}
              className={`mono rounded-sm px-1.5 py-0.5 text-[9px] uppercase tracking-wider transition-colors ${
                on
                  ? 'bg-ember/15 text-ember ring-1 ring-ember/40'
                  : 'bg-panel2/60 text-dim hover:bg-panel2 hover:text-mute'
              }`}
            >
              {s === 'all' ? 'all' : s.replace('_', ' ')}
            </button>
          );
        })}
      </div>

      <select
        aria-label="Filter by activity state"
        value={filters.activity}
        onChange={(e) => setFilters({ activity: e.target.value as ActivityState | 'all' })}
        className="mono rounded-sm border border-edge bg-panel2/60 px-1.5 py-0.5 text-[10px] text-mute focus:outline-none focus:ring-1 focus:ring-ember"
      >
        {ACTIVITIES.map((a) => (
          <option key={a} value={a}>
            {a === 'all' ? 'all activity' : a.replace(/_/g, ' ')}
          </option>
        ))}
      </select>

      <button
        type="button"
        onClick={resetFilters}
        className="mono ml-auto text-[9px] uppercase tracking-widest text-dim underline-offset-2 hover:text-mute hover:underline"
      >
        reset
      </button>
    </div>
  );
}
