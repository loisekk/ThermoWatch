/**
 * Canvas palette for the dossier instruments — mirrors the @theme design
 * tokens in styles/globals.css (2D contexts cannot read CSS variables).
 * Semantics: ok = within-normal, magma = deviation, amber = caution,
 * ember = brand accent (sweep, fingerprint, night).
 */
export const INSTR = {
  ok: '#3fb950',
  magma: '#ff4444',
  amber: '#ffb800',
  ember: '#ff6b35',
  steel: '#7d8da1',
  ink: '#e8eef5',
  mute: '#8ca0b3',
  dim: '#5b6b7d',
  edge: '#1d2833',
  edge2: '#2a3644',
  panel: '#0e141b',
} as const;
