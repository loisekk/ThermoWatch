import { PERSISTENT_DAY_THRESHOLD } from '@/config/constants';
import type { PersistenceInfo } from '@/types/domain';

/**
 * Persistence intelligence — separates acute incidents from chronic
 * thermal sources (PS requirement: "persistent thermal sources").
 * Rule aligned with FIRMS STA: >=5 detections-window days = persistent.
 */
export function assessPersistence(consecutiveDays: number, detections30d: number): PersistenceInfo {
  let regime: PersistenceInfo['regime'] = 'transient';
  if (consecutiveDays >= PERSISTENT_DAY_THRESHOLD) regime = 'persistent';
  else if (detections30d >= 12 && consecutiveDays < PERSISTENT_DAY_THRESHOLD) regime = 'seasonal';
  return { consecutiveDays, detections30d, regime };
}
