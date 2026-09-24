/** Shared empty/error state for the queue. */
export function QueueEmptyState({
  title,
  message,
  actionLabel,
  onAction,
}: {
  title: string;
  message: string;
  actionLabel?: string;
  onAction?: () => void;
}) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-2 rounded-md border border-edge bg-panel/40 p-8 text-center">
      <div className="text-xs font-medium text-mute">{title}</div>
      <div className="max-w-sm text-[10px] text-dim">{message}</div>
      {actionLabel && onAction && (
        <button
          type="button"
          onClick={onAction}
          className="mono mt-3 rounded-sm border border-ember/40 bg-ember/10 px-3 py-1.5 text-[10px] uppercase tracking-wider text-ember transition-colors hover:bg-ember/20"
        >
          {actionLabel}
        </button>
      )}
    </div>
  );
}
