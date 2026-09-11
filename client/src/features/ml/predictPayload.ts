/** Manual-run form state = full 12-feature contract + environment/spread params. */
export interface PredictFormState {
  frp: number;
  brightness_k: number;
  night_ratio: number;
  diurnal_variance: number;
  persist_days: number;
  detections_30d: number;
  frp_stability: number;
  lat: number;
  lon: number;
  facility_subtype: string;
  forest_proxy: number;
  agri_window: number;
  cluster_density: number;
  include_spread: boolean;
  wind_speed_ms: number;
  wind_dir_deg: number;
}

export const DEFAULT_FORM: PredictFormState = {
  frp: 150, brightness_k: 340, night_ratio: 0.5, diurnal_variance: 0.35,
  persist_days: 6, detections_30d: 18, frp_stability: 0.7,
  lat: 22.47, lon: 70.06, facility_subtype: 'refinery',
  forest_proxy: 0.1, agri_window: 0.1, cluster_density: 0.3,
  include_spread: true, wind_speed_ms: 4, wind_dir_deg: 270,
};

export const PRESETS: Record<string, Partial<PredictFormState>> = {
  refinery: { frp: 150, brightness_k: 345, night_ratio: 0.6, persist_days: 6, frp_stability: 0.7, facility_subtype: 'refinery', forest_proxy: 0.05, agri_window: 0.05 },
  steel: { frp: 190, brightness_k: 355, night_ratio: 0.5, persist_days: 14, frp_stability: 0.75, facility_subtype: 'steel', forest_proxy: 0.05, agri_window: 0.05 },
  gas_flare: { frp: 320, brightness_k: 370, night_ratio: 0.9, persist_days: 30, frp_stability: 0.95, facility_subtype: 'gas_flare', forest_proxy: 0.05, agri_window: 0.05 },
  cement: { frp: 90, brightness_k: 325, night_ratio: 0.45, persist_days: 20, frp_stability: 0.8, facility_subtype: 'cement', forest_proxy: 0.1, agri_window: 0.1 },
  wildfire: { frp: 140, brightness_k: 330, night_ratio: 0.15, diurnal_variance: 0.7, persist_days: 2, frp_stability: 0.25, facility_subtype: '', forest_proxy: 0.85, agri_window: 0.15, cluster_density: 0.45 },
  agri: { frp: 35, brightness_k: 305, night_ratio: 0.1, diurnal_variance: 0.5, persist_days: 2, frp_stability: 0.3, facility_subtype: '', forest_proxy: 0.2, agri_window: 0.9, cluster_density: 0.8 },
};

/** Exact POST /api/v1/predict body (server schema: PredictRequest). */
export function buildPredictRequest(f: PredictFormState) {
  return { ...f, facility_subtype: f.facility_subtype || null };
}