/** Core domain model — shared by services, store, selectors and UI. */

export type FireClass = 'industrial' | 'persistent' | 'wildfire' | 'agricultural';

export type IndustrialSubtype =
  | 'refinery'
  | 'steel'
  | 'gas_flare'
  | 'cement'
  | 'smelter'
  | 'chemical'
  | 'power_plant';

export type FireRegime = 'transient' | 'persistent' | 'seasonal';
export type RiskLevel = 'low' | 'moderate' | 'high' | 'critical';
export type AlertStatus = 'new' | 'acknowledged' | 'dispatched' | 'resolved';
export type HazardClass = 'G-I' | 'G-II' | 'G-III'; // NBC 2016 industrial hazard classes

export interface Facility {
  id: string;
  name: string;
  subtype: IndustrialSubtype;
  lat: number;
  lon: number;
  hazard: HazardClass;
}

export interface Classification {
  primary: FireClass;
  subtype: IndustrialSubtype | null;
  /** Normalised ensemble scores, sum ≈ 1. */
  scores: Record<FireClass, number>;
  confidence: number; // 0-100
}

export interface PersistenceInfo {
  consecutiveDays: number;
  detections30d: number;
  regime: FireRegime;
}

export interface RiskInfo {
  score: number; // 0-100
  level: RiskLevel;
  drivers: string[];
}

export interface FireEvent {
  id: string;
  lat: number;
  lon: number;
  frp: number; // Fire Radiative Power, MW
  brightnessK: number; // brightness temperature, Kelvin
  confidence: number; // FIRMS detection confidence 0-100
  detectedAt: number; // epoch ms
  satellite: 'VIIRS-SNPP' | 'VIIRS-NOAA20' | 'MODIS';
  dayNight: 'D' | 'N';
  classification: Classification;
  persistence: PersistenceInfo;
  risk: RiskInfo;
  nearestFacilityId: string | null;
  facilityDistanceKm: number | null;
}

export interface AlertItem {
  id: string;
  eventId: string;
  level: RiskLevel;
  message: string;
  createdAt: number;
  status: AlertStatus;
}

export interface LogLine {
  ts: number;
  kind: 'ingest' | 'classify' | 'alert' | 'system';
  text: string;
}

export interface Filters {
  classes: FireClass[];
  minConfidence: number;
  persistentOnly: boolean;
}

/** Feature vector fed to the classifier (mirrors the trained-model contract). */
export interface ClassFeatures {
  frp: number;
  brightnessK: number;
  nightRatio: number;
  diurnalVariance: number;
  persistDays: number;
  facilityDistanceKm: number | null;
  facilityHazard: HazardClass | null;
  forestProxy: number; // 0-1 land-cover context
  agriWindow: number; // 0-1 seasonal residue-burn context
  clusterDensity: number; // 0-1 same-day neighbourhood density
}
