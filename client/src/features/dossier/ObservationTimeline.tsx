/** Chronological observation table for the dossier. */
import type { ObservationDetail } from '@/services/api/v2Types';

export function ObservationTimeline({ observations }: { observations: ObservationDetail[] }) {
  if (observations.length === 0) {
    return (
      <section className="rounded-md border border-edge bg-panel/60 p-3 text-xs text-dim">
        No observations linked.
      </section>
    );
  }

  return (
    <section
      className="rounded-md border border-edge bg-panel/60 p-3"
      aria-label="Observation timeline"
    >
      <h4 className="mono mb-2 text-[10px] font-semibold uppercase tracking-widest text-mute">
        Observation Timeline ({observations.length})
      </h4>

      <div className="max-h-56 space-y-0 overflow-y-auto">
        <table className="w-full text-[10px]">
          <thead className="sticky top-0 bg-panel text-dim">
            <tr className="border-b border-edge">
              <th className="px-1.5 py-1 text-left font-medium">Observed (UTC)</th>
              <th className="px-1.5 py-1 text-left font-medium">Sensor</th>
              <th className="px-1.5 py-1 text-right font-medium">FRP</th>
              <th className="px-1.5 py-1 text-right font-medium">BTi4</th>
              <th className="px-1.5 py-1 text-center font-medium">Conf</th>
              <th className="px-1.5 py-1 text-center font-medium">D/N</th>
            </tr>
          </thead>
          <tbody>
            {observations.map((obs) => (
              <tr key={obs.id} className="border-b border-edge/50 hover:bg-panel2/40">
                <td className="mono px-1.5 py-1 text-mute">
                  {new Date(obs.observed_at).toISOString().slice(0, 16).replace('T', ' ')}
                </td>
                <td className="mono px-1.5 py-1 text-mute">{obs.sensor}/{obs.platform}</td>
                <td className="mono px-1.5 py-1 text-right tabular-nums text-mute">
                  {obs.frp?.toFixed(1) ?? '—'}
                </td>
                <td className="mono px-1.5 py-1 text-right tabular-nums text-dim">
                  {obs.brightness_ti4?.toFixed(0) ?? '—'}
                </td>
                <td className="px-1.5 py-1 text-center">
                  <span
                    className={`mono rounded-sm px-1 text-[9px] ${
                      obs.confidence === 'high' ? 'bg-ok/15 text-ok'
                      : obs.confidence === 'nominal' ? 'bg-amber/15 text-amber'
                      : 'bg-steel/15 text-dim'
                    }`}
                    title={obs.confidence}
                  >
                    {obs.confidence[0]?.toUpperCase() ?? '?'}
                  </span>
                </td>
                <td className="mono px-1.5 py-1 text-center text-dim">
                  {obs.day_night === 'night' ? 'N' : 'D'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
