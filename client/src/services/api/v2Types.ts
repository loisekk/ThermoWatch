/**
 * TypeScript types matching the FastAPI v2 Phase-4 Pydantic schemas
 * (server/api/app/api/v2/incidents.py). Keep both sides in lockstep.
 */

export type Disposition = "needs_review" | "reviewed" | "escalated" | "dismissed";
export type ActivityState =
  | "acute" | "recurring" | "persistent" | "changing"
  | "insufficient_history" | "unknown";
export type AssessmentStatus = "normal" | "abnormal" | "insufficient_evidence";

export interface AssessmentSummary {
  id: string;
  assessment_version: string;
  assessed_at: string;
  status: AssessmentStatus;
  top_class: string;
  top_confidence: number | null;
  activity_state: ActivityState;
  abstain_reason: string | null;
}

export interface IncidentSummary {
  id: string;
  status: Disposition;
  version: number;
  centroid_latitude: number;
  centroid_longitude: number;
  first_seen_at: string;
  last_seen_at: string;
  observation_count: number;
  current_assessment: AssessmentSummary | null;
  days_active: number;
}

export interface IncidentListResponse {
  incidents: IncidentSummary[];
  next_cursor: string | null;
  total_approx: number;
}

export interface ObservationDetail {
  id: string;
  observed_at: string;
  ingested_at: string;
  latitude: number;
  longitude: number;
  sensor: string;
  platform: string;
  frp: number | null;
  brightness_ti4: number | null;
  confidence: string;
  day_night: string;
  scan: number;
  track: number;
  association_score: number;
  association_method: string;
  association_rationale: Record<string, unknown>;
}

export interface AssessmentDetail {
  id: string;
  assessment_version: string;
  normal_state_version: string | null;
  assessed_at: string;
  source_class_scores: Record<string, number>;
  activity_state: ActivityState;
  residuals: Record<string, number | null> | null;
  status: AssessmentStatus;
  confidence: number | null;
  abstain_reason: string | null;
  evidence_quality: Record<string, unknown>;
  explanation: Record<string, unknown>;
  feature_schema_version: string;
  model_config_version: string;
}

export interface ReviewDetail {
  id: string;
  actor_id: string;
  action: Disposition;
  note: string | null;
  occurred_at: string;
  expected_incident_version: number;
  resulting_incident_version: number;
}

export interface ContextDetail {
  provider: string;
  provider_type: string;
  retrieved_at: string;
  distance_m: number | null;
  payload: Record<string, unknown>;
}

export interface IncidentDossier {
  id: string;
  status: Disposition;
  version: number;
  created_at: string;
  centroid_latitude: number;
  centroid_longitude: number;
  first_seen_at: string;
  last_seen_at: string;
  observation_count: number;
  association_rule_version: string;
  observations: ObservationDetail[];
  assessments: AssessmentDetail[];
  reviews: ReviewDetail[];
  context: ContextDetail[];
}

export interface ReviewRequest {
  action: Disposition;
  note?: string | null;
  expected_incident_version: number;
  idempotency_key: string;
}

export interface ReviewResponse {
  review_id: string;
  incident_id: string;
  new_status: Disposition;
  new_version: number;
  occurred_at: string;
}

export interface TimelineEntry {
  id: string;
  observed_at: string;
  latitude: number;
  longitude: number;
  sensor: string;
  platform: string;
  frp: number | null;
  brightness_ti4: number | null;
  confidence: string;
  day_night: string;
}

export interface TimelineResponse {
  observations: TimelineEntry[];
  next_cursor: string | null;
}

/** WebSocket event envelope (server /v2/stream). */
export interface StreamEvent {
  event_id: string;
  sequence: number;
  entity_type: string;
  entity_id: string;
  entity_version: number | null;
  event_type: string;
  committed_at: string;
  schema_version: string;
}

/** Queue filter state (Zustand). */
export interface QueueFilters {
  status: Disposition | "all";
  activity: ActivityState | "all";
  minConfidence: number | null;
  timeRangeHours: number | null;
}
