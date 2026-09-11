import { describe, expect, it } from 'vitest';
import { buildPredictRequest, DEFAULT_FORM, PRESETS } from '../predictPayload';

describe('predictPayload', () => {
  it('builds the exact server contract keys', () => {
    const body = buildPredictRequest(DEFAULT_FORM);
    for (const k of ['frp', 'brightness_k', 'night_ratio', 'diurnal_variance', 'persist_days', 'detections_30d', 'frp_stability', 'lat', 'lon', 'facility_subtype', 'forest_proxy', 'agri_window', 'cluster_density', 'include_spread', 'wind_speed_ms', 'wind_dir_deg']) {
      expect(body).toHaveProperty(k);
    }
  });
  it('maps empty facility subtype to null', () => {
    expect(buildPredictRequest({ ...DEFAULT_FORM, facility_subtype: '' }).facility_subtype).toBeNull();
  });
  it('presets override thermal signature coherently', () => {
    const flare = { ...DEFAULT_FORM, ...PRESETS.gas_flare };
    expect(flare.frp_stability).toBeGreaterThan(0.9);
    expect(flare.night_ratio).toBeGreaterThan(0.8);
    const fire = { ...DEFAULT_FORM, ...PRESETS.wildfire };
    expect(fire.forest_proxy).toBeGreaterThan(0.8);
  });
});