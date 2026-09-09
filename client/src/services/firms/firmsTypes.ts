/** Raw NASA FIRMS active-fire record (API CSV/JSON column contract). */
export interface FirmsRecord {
  latitude: number;
  longitude: number;
  bright_ti4: number;
  scan: number;
  track: number;
  acq_date: string;
  acq_time: string;
  satellite: string;
  instrument: string;
  confidence: number;
  frp: number;
  daynight: 'D' | 'N';
  type: number;
}
