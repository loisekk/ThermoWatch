/**
 * Review history — append-only audit trail of every recorded disposition
 * change. Newest first; empty state is explicit rather than blank.
 */
import type { ReviewDetail } from '@/services/api/v2Types';

const ACTION_STYLE: Record<string, string> = {
  reviewed: 'border-ok/40 text-ok',
  escalated: 'border-magma/40 text-magma',
  dismissed: 'border-dim text-dim',
  needs_review: 'border-amber/40 text-amber',
};

export function ReviewHistory({ reviews }: { reviews: ReviewDetail[] }) {
  return (
    <section
      className="rounded-md border border-edge bg-panel/60 p-3"
      aria-label="Review history"
    >
      <div className="mb-2 flex items-baseline justify-between">
        <h4 className="mono text-[10px] font-semibold uppercase tracking-widest text-mute">
          Review History
        </h4>
        <span className="mono text-[9px] text-dim">{reviews.length} entries</span>
      </div>

      {reviews.length === 0 ? (
        <p className="mono text-[10px] italic text-dim">
          No reviews recorded yet — this incident is awaiting first triage.
        </p>
      ) : (
        <ol className="space-y-2">
          {/* Server returns newest first; keep that order (audit trail is append-only). */}
          {reviews.map((review) => (
            <li
              key={review.id}
              className="rounded-sm border border-edge bg-panel2/60 px-2 py-1.5"
            >
              <div className="flex items-center justify-between gap-2">
                <span
                  className={`mono rounded-sm border px-1.5 py-0.5 text-[9px] uppercase tracking-wider ${
                    ACTION_STYLE[review.action] ?? 'border-edge text-mute'
                  }`}
                >
                  {review.action.replace(/_/g, ' ')}
                </span>
                <span className="mono text-[9px] tabular-nums text-dim">
                  v{review.expected_incident_version} → v{review.resulting_incident_version}
                </span>
              </div>
              {review.note && (
                <p className="mt-1.5 text-[10px] leading-relaxed text-mute">
                  {review.note}
                </p>
              )}
              <div className="mono mt-1 flex justify-between text-[9px] text-dim">
                <span className="truncate">{review.actor_id}</span>
                <span>{new Date(review.occurred_at).toLocaleString()}</span>
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
