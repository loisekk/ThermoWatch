import { useRef } from 'react';

interface Props {
  edge: 'left' | 'right';
  width: number;
  min: number;
  max: number;
  onChange: (w: number) => void;
  onReset: () => void;
  label: string;
}

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

/** Keyboard/pointer resizable edge for dock + drawers.
 *  Drag or arrow-keys resize; double-click resets to the default width. */
export function ResizeHandle({ edge, width, min, max, onChange, onReset, label }: Props) {
  const drag = useRef<{ x: number; w: number } | null>(null);
  const step = edge === 'left' ? -16 : 16;
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      tabIndex={0}
      onDoubleClick={onReset}
      onPointerDown={(e) => {
        drag.current = { x: e.clientX, w: width };
        (e.target as HTMLElement).setPointerCapture(e.pointerId);
      }}
      onPointerMove={(e) => {
        if (!drag.current) return;
        const d = edge === 'left' ? drag.current.x - e.clientX : e.clientX - drag.current.x;
        onChange(clamp(drag.current.w + d, min, max));
      }}
      onPointerUp={(e) => {
        drag.current = null;
        (e.target as HTMLElement).releasePointerCapture(e.pointerId);
      }}
      onPointerCancel={() => { drag.current = null; }}
      onKeyDown={(e) => {
        if (e.key === 'ArrowLeft') { e.preventDefault(); onChange(clamp(width - step, min, max)); }
        if (e.key === 'ArrowRight') { e.preventDefault(); onChange(clamp(width + step, min, max)); }
      }}
      className={`absolute top-0 bottom-0 z-40 w-1.5 cursor-col-resize outline-none transition-colors
        hover:bg-ember/60 focus-visible:bg-ember/60 ${edge === 'left' ? 'left-0' : 'right-0'}`}
    />
  );
}
