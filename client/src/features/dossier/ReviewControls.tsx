/**
 * Review controls — the only write surface of the dossier. Mirrors the server
 * review state machine (server re-validates), sends expected_incident_version
 * for optimistic concurrency, and rotates the idempotency key only after a
 * confirmed success (a failed submit retries as the SAME submission).
 */
import { useRef, useState } from 'react';
import type { Disposition } from '@/services/api/v2Types';
import { useSubmitReview } from '@/services/api/useV2Queries';
import { V2ApiError } from '@/services/api/v2Client';
import {
  ACTION_LABELS,
  MIN_NOTE_CHARS,
  allowedActions,
  isNoteRequired,
  isNoteSufficient,
  newIdempotencyKey,
} from './reviewRules';

type Outcome = 'conflict' | 'validation' | 'timeout' | 'success';

export function ReviewControls({
  incidentId,
  currentStatus,
  currentVersion,
}: {
  incidentId: string;
  currentStatus: Disposition;
  currentVersion: number;
}) {
  const mutation = useSubmitReview(incidentId);
  const [pendingAction, setPendingAction] = useState<Disposition | null>(null);
  const [note, setNote] = useState('');
  const [noteTouched, setNoteTouched] = useState(false);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [errorDetail, setErrorDetail] = useState('');
  // One key per intended submission: kept on failure (retry = same submission),
  // rotated only after the server confirms success.
  const idempotencyKeyRef = useRef<string>(newIdempotencyKey());

  const actions = allowedActions(currentStatus);
  const needsNote = pendingAction !== null && isNoteRequired(pendingAction);
  const noteOk = !needsNote || isNoteSufficient(note);

  const handleAction = (action: Disposition) => {
    setPendingAction((prev) => (prev === action ? null : action));
    setOutcome(null);
    setErrorDetail('');
    setNoteTouched(false);
  };

  const handleSubmit = () => {
    if (!pendingAction || !noteOk || mutation.isPending) return;
    setOutcome(null);
    setErrorDetail('');
    mutation.mutate(
      {
        action: pendingAction,
        note: note.trim() ? note.trim() : null,
        expected_incident_version: currentVersion,
        idempotency_key: idempotencyKeyRef.current,
      },
      {
        onSuccess: () => {
          idempotencyKeyRef.current = newIdempotencyKey();
          setOutcome('success');
          setNote('');
          setPendingAction(null);
          setNoteTouched(false);
        },
        onError: (err: unknown) => {
          if (err instanceof V2ApiError) {
            if (err.status === 409) {
              setOutcome('conflict'); // dossier invalidates → fresh version
            } else if (err.status === 0) {
              setOutcome('timeout'); // outcome unknown — same key on retry
            } else {
              setOutcome('validation');
              setErrorDetail(
                typeof err.detail === 'string' ? err.detail : err.message,
              );
            }
          } else {
            setOutcome('timeout');
          }
        },
      },
    );
  };

  return (
    <section
      className="rounded-md border border-edge bg-panel/60 p-3"
      aria-label="Review controls"
    >
      <div className="mb-2 flex items-baseline justify-between">
        <h4 className="mono text-[10px] font-semibold uppercase tracking-widest text-mute">
          Review
        </h4>
        <span className="mono text-[9px] text-dim">v{currentVersion}</span>
      </div>

      {/* Legal transitions only — everything else is hidden, not disabled. */}
      <div className="mb-2 flex flex-wrap gap-1.5" role="group" aria-label="Available actions">
        {actions.length === 0 ? (
          <span className="mono text-[10px] text-dim">No transitions from {currentStatus}.</span>
        ) : (
          actions.map((action) => (
            <button
              key={action}
              type="button"
              onClick={() => handleAction(action)}
              aria-pressed={pendingAction === action}
              className={`mono rounded-sm border px-2 py-1 text-[10px] uppercase tracking-wider transition-colors ${
                pendingAction === action
                  ? 'border-ember/60 bg-ember/15 text-ember'
                  : 'border-edge text-mute hover:border-steel hover:text-ink'
              }`}
            >
              {ACTION_LABELS[action]}
            </button>
          ))
        )}
      </div>

      {pendingAction && (
        <div className="space-y-1.5">
          <label
            htmlFor="review-note"
            className="mono block text-[9px] uppercase tracking-widest text-dim"
          >
            Note
            {isNoteRequired(pendingAction)
              ? ` — required for ${ACTION_LABELS[pendingAction].toLowerCase()} (min ${MIN_NOTE_CHARS})`
              : ' — optional'}
          </label>
          <textarea
            id="review-note"
            rows={3}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            onBlur={() => setNoteTouched(true)}
            placeholder="Justification recorded in the audit trail…"
            aria-invalid={needsNote && noteTouched && !noteOk}
            className="w-full resize-y rounded-sm border border-edge bg-panel2 px-2 py-1.5 text-[11px] text-ink placeholder:text-dim focus:border-ember/50 focus:outline-none"
          />
          {needsNote && noteTouched && !noteOk && (
            <p className="mono text-[9px] text-amber">
              At least {MIN_NOTE_CHARS} characters required before escalating or dismissing.
            </p>
          )}
          <button
            type="button"
            onClick={handleSubmit}
            disabled={!noteOk || mutation.isPending}
            className="mono w-full rounded-sm border border-ember/50 bg-ember/10 px-3 py-1.5 text-[10px] uppercase tracking-wider text-ember transition-colors hover:bg-ember/20 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {mutation.isPending
              ? 'Submitting…'
              : `Confirm — ${ACTION_LABELS[pendingAction]}`}
          </button>
        </div>
      )}


      {/* Outcome panels — every failure mode has an explicit, honest state. */}
      {outcome === 'conflict' && (
        <div
          role="alert"
          className="mt-2 rounded-sm border border-amber/40 bg-amber/10 px-2.5 py-2 text-[10px] text-amber"
        >
          <strong>Version conflict (409).</strong> Someone else changed this incident
          while you were reviewing. The dossier has been refreshed — re-check the
          evidence, then reapply your decision.
        </div>
      )}
      {outcome === 'validation' && (
        <div
          role="alert"
          className="mt-2 rounded-sm border border-magma/40 bg-magma/10 px-2.5 py-2 text-[10px] text-magma"
        >
          <strong>Rejected by server.</strong>{' '}
          {errorDetail || 'The transition or note did not pass validation.'}
        </div>
      )}
      {outcome === 'timeout' && (
        <div
          role="alert"
          className="mt-2 rounded-sm border border-amber/40 bg-amber/10 px-2.5 py-2 text-[10px] text-amber"
        >
          <strong>Outcome unknown.</strong> The request timed out before the server
          replied — the review may or may not have been recorded. Retrying reuses the
          same idempotency key, so a duplicate will never be created.
        </div>
      )}
      {outcome === 'success' && (
        <div
          role="status"
          className="mt-2 rounded-sm border border-ok/40 bg-ok/10 px-2.5 py-2 text-[10px] text-ok"
        >
          Review recorded. The queue and dossier now show the new disposition.
        </div>
      )}

    </section>
  );
}
