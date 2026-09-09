import type { ClassFeatures, RiskInfo, RiskLevel } from '@/types/domain';

/** Multi-factor risk scoring: intensity + persistence + asset exposure + confidence. */
export function scoreRisk(f: ClassFeatures, confidence: number): RiskInfo {
  const intensity = Math.min(1, f.frp / 700);
  const persistence = Math.min(1, f.persistDays / 20);
  const exposure =
    f.facilityHazard === 'G-III' ? 0.9 : f.facilityHazard === 'G-II' ? 0.6 : f.facilityDistanceKm == null ? 0.25 : 0.4;
  const conf = confidence / 100;

  const score = Math.round(100 * (0.4 * intensity + 0.25 * persistence + 0.2 * exposure + 0.15 * conf));
  const level: RiskLevel = score >= 75 ? 'critical' : score >= 55 ? 'high' : score >= 35 ? 'moderate' : 'low';

  const drivers: string[] = [];
  if (intensity > 0.45) drivers.push(`FRP ${Math.round(f.frp)} MW (elevated)`);
  if (f.persistDays >= 5) drivers.push(`${f.persistDays}-day persistence`);
  if (f.facilityHazard) drivers.push(`Within proximity of ${f.facilityHazard} hazard facility`);
  if (f.nightRatio > 0.4) drivers.push('Night-time detection (uncontrolled-burn indicator)');
  if (drivers.length === 0) drivers.push('No aggravating factors');

  return { score, level, drivers };
}
