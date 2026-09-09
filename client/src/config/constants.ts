import type { FireClass, IndustrialSubtype, RiskLevel } from '@/types/domain';

export const CLASS_ORDER: FireClass[] = ['industrial', 'persistent', 'wildfire', 'agricultural'];

export const CLASS_META: Record<FireClass, { label: string; short: string; color: string; blurb: string }> = {
  industrial: { label: 'Industrial Fire', short: 'IND', color: '#FF6B35', blurb: 'Acute incident at a mapped industrial facility' },
  persistent: { label: 'Persistent Thermal Source', short: 'PRS', color: '#FFB800', blurb: 'Chronic emission — flare, kiln, chronic hotspot' },
  wildfire:   { label: 'Wildfire', short: 'WLD', color: '#FF4444', blurb: 'Vegetation fire outside industrial context' },
  agricultural:{ label: 'Agricultural Burn', short: 'AGR', color: '#8FD14F', blurb: 'Crop-residue / stubble burning window' },
};

export const SUBTYPE_LABEL: Record<IndustrialSubtype, string> = {
  refinery: 'Refinery',
  steel: 'Steel Plant',
  gas_flare: 'Gas Flare',
  cement: 'Cement Kiln',
  smelter: 'Smelter',
  chemical: 'Chemical Plant',
  power_plant: 'Power Plant',
};

export const RISK_META: Record<RiskLevel, { label: string; color: string }> = {
  low: { label: 'LOW', color: '#3FB950' },
  moderate: { label: 'MODERATE', color: '#FFB800' },
  high: { label: 'HIGH', color: '#FF6B35' },
  critical: { label: 'CRITICAL', color: '#FF4444' },
};

export const INDIA_CENTER: [number, number] = [78.9, 22.5];
export const INDIA_ZOOM = 4.1;

export const TICK_MS = 7000;          // simulated NRT trickle
export const MAX_EVENTS = 1200;       // rolling window cap
export const HISTORY_DAYS = 14;
export const PERSISTENT_DAY_THRESHOLD = 5; // FIRMS STA-aligned persistence rule
