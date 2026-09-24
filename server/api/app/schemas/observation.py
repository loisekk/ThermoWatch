"""Observation domain schemas (Phase 0, Pydantic v2).

Contract notes:
- FIRMSObservationRaw is the immutable evidence record built from a raw FIRMS CSV
  row (VIIRS column names bright_ti4/bright_ti5 are aliases; MODIS names
  brightness/bright_t31 land in model_extra and are read by the normalizer).
- Malformed rows are NEVER rejected at the batch level — the ingest service
  validates per row and quarantines failures so one bad CSV line cannot block
  a full FIRMS pull.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)


class SensorType(StrEnum):
    """Satellite sensor identifiers."""

    MODIS = "modis"
    VIIRS = "viirs"
    LANDSAT_OLI = "landsat_oli"


class SatellitePlatform(StrEnum):
    """Satellite platforms carrying thermal sensors."""

    TERRA = "terra"
    AQUA = "aqua"
    SNPP = "snpp"
    NOAA20 = "noaa20"
    NOAA21 = "noaa21"
    LANDSAT8 = "landsat8"
    LANDSAT9 = "landsat9"


class ConfidenceLevel(StrEnum):
    """FIRMS confidence levels (VIIRS: L/N/H string, MODIS: 0-100 numeric)."""

    LOW = "low"
    NOMINAL = "nominal"
    HIGH = "high"
    UNKNOWN = "unknown"


class DayNightFlag(StrEnum):
    DAY = "day"
    NIGHT = "night"
    UNKNOWN = "unknown"


class IngestStatus(StrEnum):
    """Processing state of an observation."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    QUARANTINED = "quarantined"
    DUPLICATE = "duplicate"


class FIRMSObservationRaw(BaseModel):
    """Raw FIRMS CSV row — exactly as received from the provider.

    Frozen + extra-allow: the parsed row is immutable evidence and unknown
    provider columns are preserved for future compatibility.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="allow",
        str_strip_whitespace=True,
    )

    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    # VIIRS CSV column names as aliases; MODIS names (brightness/bright_t31)
    # arrive as extras and are recovered by normalize_observation.
    brightness: float | None = Field(
        None, alias="bright_ti4", description="I-4 / mid-IR brightness temperature (K)"
    )
    scan: float = Field(..., gt=0, description="Pixel scan width (degrees)")
    track: float = Field(..., gt=0, description="Pixel track height (degrees)")
    acq_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    acq_time: str = Field(..., description="HHMM (MODIS) or seconds-of-scan (VIIRS)")
    satellite: str = Field(..., min_length=1)
    instrument: str = Field(..., min_length=1)
    confidence: str | int = Field(..., description="L/N/H (VIIRS) or 0-100 (MODIS)")
    bright_t31: float | None = Field(
        None, alias="bright_ti5", description="Background channel brightness (K)"
    )
    frp: float | None = Field(None, ge=0, description="Fire Radiative Power (MW)")
    daynight: str = Field(..., pattern="^[DN]$")
    version: str | None = Field(None, description="FIRMS data version")

    @field_validator("confidence", mode="before")
    @classmethod
    def normalize_confidence(cls, v: str | int) -> str:
        """Normalize MODIS numeric confidence and VIIRS single letters to canonical
        lowercase levels, so downstream code never sees raw provider codes."""
        if isinstance(v, int):
            if v < 30:
                return "low"
            if v < 80:
                return "nominal"
            return "high"
        s = str(v).strip().lower()
        return {"l": "low", "n": "nominal", "h": "high"}.get(s, s)

    @field_validator("acq_time", mode="after")
    @classmethod
    def validate_time_format(cls, v: str) -> str:
        """VIIRS may use seconds-of-scan (up to 86399); MODIS uses HHMM."""
        if v.isdigit() and len(v) == 4:
            hh, mm = int(v[:2]), int(v[2:])
            if hh > 23 or mm > 59:
                raise ValueError(f"Invalid HHMM time: {v}")
        elif v.isdigit() and int(v) <= 86399:
            pass  # VIIRS seconds-of-scan format
        else:
            raise ValueError(f"Invalid acquisition time: {v}")
        return v

    @model_validator(mode="after")
    def validate_spatial_bounds(self) -> FIRMSObservationRaw:
        """Reject observations at exactly (0,0) — common data-corruption marker."""
        if self.latitude == 0 and self.longitude == 0:
            raise ValueError("Observation at (0,0) — likely malformed")
        return self

    def confidence_level(self) -> ConfidenceLevel:
        try:
            return ConfidenceLevel(str(self.confidence))
        except ValueError:
            return ConfidenceLevel.UNKNOWN

    def modis_brightness(self) -> float | None:
        """Brightness for MODIS rows (columns brightness/bright_t31 are extras)."""
        extra = self.model_extra or {}
        val = self.brightness
        if val is None:
            raw = extra.get("brightness")
            try:
                val = float(raw) if raw not in (None, "") else None
            except (TypeError, ValueError):
                val = None
        return val

    def modis_bright_t31(self) -> float | None:
        """Background channel for MODIS rows (extra column bright_t31)."""
        if self.bright_t31 is not None:
            return self.bright_t31
        extra = self.model_extra or {}
        raw = extra.get("bright_t31")
        try:
            return float(raw) if raw not in (None, "") else None
        except (TypeError, ValueError):
            return None


def compute_observation_key(raw: FIRMSObservationRaw) -> str:
    """Stable identity hash: same provider observation always yields the same key
    (satellite, instrument, acq_date, acq_time, lat, lon to 6 decimals)."""
    import hashlib

    identity = "|".join(
        [
            raw.satellite.upper(),
            raw.instrument.upper(),
            raw.acq_date,
            raw.acq_time,
            f"{raw.latitude:.6f}",
            f"{raw.longitude:.6f}",
        ]
    )
    return hashlib.sha256(identity.encode()).hexdigest()[:32]


class ObservationNormalized(BaseModel):
    """Normalized observation for database persistence and querying.

    Separated from raw so the normalized schema can evolve without losing evidence.
    """

    model_config = ConfigDict(from_attributes=True, validate_assignment=True)

    id: UUID = Field(default_factory=uuid4)
    provider: str = "firms"
    provider_observation_key: str = Field(..., max_length=64)

    # Temporal
    observed_at: datetime
    ingested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Spatial
    latitude: float
    longitude: float

    # Sensor metadata
    sensor: SensorType
    platform: SatellitePlatform
    scan: float
    track: float

    # Thermal properties
    brightness_ti4: float | None = None
    brightness_ti5: float | None = None
    frp: float | None = Field(None, ge=0)

    # Quality
    confidence: ConfidenceLevel
    day_night: DayNightFlag
    quality_flags: dict[str, Any] = Field(default_factory=dict)

    # Processing
    ingest_status: IngestStatus = IngestStatus.PENDING
    raw_payload: dict[str, Any]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def pixel_area_km2(self) -> float | None:
        """Approximate pixel footprint in km² (degrees × ~111.32 km/degree)."""
        if self.scan and self.track:
            return round(self.scan * self.track * 111.32 * 111.32, 4)
        return None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_night(self) -> bool:
        return self.day_night == DayNightFlag.NIGHT


def normalize_observation(raw: FIRMSObservationRaw) -> ObservationNormalized:
    """Convert a raw FIRMS observation into the normalized persistence schema."""
    from datetime import datetime as _dt

    # Parse acquisition timestamp: MODIS HHMM vs VIIRS seconds-of-scan
    if len(raw.acq_time) == 4:  # HHMM
        hh, mm, ss = int(raw.acq_time[:2]), int(raw.acq_time[2:]), 0
    else:  # seconds-of-scan
        total = int(raw.acq_time)
        hh, mm, ss = total // 3600, (total % 3600) // 60, total % 60

    observed_at = _dt(
        int(raw.acq_date[:4]),
        int(raw.acq_date[5:7]),
        int(raw.acq_date[8:10]),
        hh,
        mm,
        ss,
        tzinfo=timezone.utc,
    )

    # Map satellite code -> platform (MODIS: T/A or 1/2; VIIRS: N/G/J)
    platform_map = {
        "T": SatellitePlatform.TERRA,
        "1": SatellitePlatform.TERRA,
        "A": SatellitePlatform.AQUA,
        "2": SatellitePlatform.AQUA,
        "N": SatellitePlatform.SNPP,
        "S": SatellitePlatform.SNPP,
        "G": SatellitePlatform.NOAA20,
        "J": SatellitePlatform.NOAA21,
        "L8": SatellitePlatform.LANDSAT8,
        "L9": SatellitePlatform.LANDSAT9,
    }
    platform = platform_map.get(
        raw.satellite.upper(),
        SatellitePlatform(raw.satellite.lower())
        if raw.satellite.lower() in SatellitePlatform._value2member_map_
        else SatellitePlatform.SNPP,
    )

    # Map instrument -> sensor
    sensor_map = {
        "MODIS": SensorType.MODIS,
        "VIIRS": SensorType.VIIRS,
        "VNP13": SensorType.VIIRS,
        "OLI": SensorType.LANDSAT_OLI,
        "OLI-2": SensorType.LANDSAT_OLI,
    }
    sensor = sensor_map.get(raw.instrument.upper(), SensorType.VIIRS)

    day_night = DayNightFlag.NIGHT if raw.daynight == "N" else DayNightFlag.DAY

    return ObservationNormalized(
        provider="firms",
        provider_observation_key=compute_observation_key(raw),
        observed_at=observed_at,
        latitude=raw.latitude,
        longitude=raw.longitude,
        sensor=sensor,
        platform=platform,
        scan=raw.scan,
        track=raw.track,
        brightness_ti4=raw.modis_brightness(),
        brightness_ti5=raw.modis_bright_t31(),
        frp=raw.frp,
        confidence=raw.confidence_level(),
        day_night=day_night,
        quality_flags={"provider_version": raw.version} if raw.version else {},
        raw_payload=raw.model_dump(mode="json"),
    )


class ObservationCreate(BaseModel):
    """Request schema for POST /v2/observations (batch ingest).

    Rows are loose dicts here on purpose: the ingest service validates each row
    independently so a single malformed CSV line is quarantined instead of
    rejecting the whole FIRMS pull.
    """

    observations: list[dict[str, Any]] = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="Batch of raw FIRMS observations (VIIRS or MODIS CSV row dicts)",
    )
    source_batch_id: str | None = Field(
        None, max_length=128, description="Optional batch identifier for idempotency tracking"
    )


class ObservationResponse(BaseModel):
    """Response schema for GET /v2/observations."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    provider: str
    provider_observation_key: str
    observed_at: datetime
    ingested_at: datetime
    latitude: float
    longitude: float
    sensor: SensorType
    platform: SatellitePlatform
    frp: float | None = None
    brightness_ti4: float | None = None
    brightness_ti5: float | None = None
    confidence: ConfidenceLevel
    day_night: DayNightFlag
    ingest_status: IngestStatus
    quality_flags: dict[str, Any] = Field(default_factory=dict)
    pixel_area_km2: float | None = None
    is_night: bool = False


class ObservationListResponse(BaseModel):
    """Paginated observation list response."""

    observations: list[ObservationResponse]
    total: int
    page: int
    page_size: int
    has_next: bool


class IngestResult(BaseModel):
    """Result of a batch ingestion operation."""

    accepted: int = Field(0, description="New observations persisted")
    duplicates: int = Field(0, description="Already-existing observations (idempotent skip)")
    quarantined: int = Field(0, description="Invalid observations moved to quarantine")
    errors: list[dict[str, Any]] = Field(default_factory=list)
    batch_id: str | None = None
    # Phase 2: association + assessment counts (0 unless ?process=true)
    incidents_touched: int = Field(0, description="Incidents linked or created by association")
    assessments: int = Field(0, description="Versioned assessment rows appended")
    # ORM rows actually inserted this call — consumed by the v2 pipeline, never
    # serialized (excluded) so the response contract stays unchanged.
    accepted_rows: list[Any] = Field(
        default_factory=list, exclude=True, repr=False
    )

