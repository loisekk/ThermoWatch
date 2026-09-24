from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TW_", env_file=".env", extra="ignore")
    cors_origins: str = "http://localhost:5173"
    ingest_token: str = ""                    # shared secret for POST /ingest/events (optional; set TW_INGEST_TOKEN)
    # --- Shared-deployment write authorization (FR-SEC-01) --------------------
    # Unset (None/empty) = local single-user mode: write endpoints accept
    # anonymous callers and reviews are attributed to the request's actor_id
    # (default "analyst-demo"). Set TW_WRITE_TOKEN to require
    # `Authorization: Bearer <token>` on every state-changing v2 endpoint
    # (observation ingest, analyst reviews). Read endpoints stay public.
    write_token: str | None = None
    # Expose /docs, /redoc and /openapi.json. Set TW_DOCS_ENABLED=0 on any
    # shared or internet-facing deployment (keeps the API surface unenumerable).
    docs_enabled: bool = True
    # Regex allow-list for browser origins (used by CORS + WS). Covers prod, every
    # Vercel preview/deployment URL and localhost — exact-match lists break whenever
    # Vercel rotates a URL, which is exactly the failure class this field kills.
    origin_regex: str = r"https://[a-zA-Z0-9.-]+\.vercel\.app|http://localhost(:\d+)?|http://127\.0\.0\.1(:\d+)?"
    api_v1: str = "/api/v1"
    api_v2: str = "/v2"
    persistence_day_threshold: int = 5      # FIRMS STA rule
    cell_deg: float = 0.004                  # ~400 m grid proxy (h3 res-9 is the upgrade path)
    max_events: int = 5000

    # --- Phase 0: durable storage (PostgreSQL 17 + PostGIS) -------------------
    # Async SQLAlchemy URL. In compose this is set via TW_DATABASE_URL; locally the
    # default matches the docker-compose db service credentials.
    database_url: str = "postgresql+asyncpg://thermowatch:thermowatch_dev@localhost:5432/thermowatch"
    db_echo: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 20
    # When False (default) the API boots without a database — the V1 in-memory
    # pipeline keeps serving and /health/ready reports degraded. Set TW_DB_REQUIRED=1
    # to make startup fail hard when PostGIS is unreachable (docker-compose does this).
    db_required: bool = False
    # NullPool: create a connection per checkout and close it on release.
    # Tests set TW_DB_NULL_POOL=1 because pytest-asyncio gives each test its
    # own event loop (and TestClient runs the lifespan in an anyio portal
    # loop) while asyncpg connections are bound to their creating loop —
    # pooling would hand out connections attached to a dead loop.
    db_null_pool: bool = False

    # --- Phase 0: external providers (v2 ingest/context caching) ---------------
    firms_api_key: str = ""
    firms_base_url: str = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
    osm_overpass_url: str = "https://overpass-api.de/api/interpreter"
    open_meteo_url: str = "https://api.open-meteo.com/v1/forecast"
    gdelt_base_url: str = "https://api.gdeltproject.org/api/v2/doc/doc"

    # --- v2 incident association thresholds (calibrated via research harness) ---
    assoc_max_distance_km: float = 2.0
    assoc_max_time_hours: int = 72
    assoc_link_threshold: float = 0.35     # min score to link vs create-new
    assoc_rule_version: str = "assoc-v0.1.0"

    # --- Facility normal state (Phase 3; calibrate via E-experiments) ---
    state_min_obs: int = 10                # below this: INSUFFICIENT_HISTORY
    state_min_days: int = 14
    state_lookback_days: int = 90
    state_zone_eps_km: float = 1.0         # DBSCAN cluster radius
    state_zone_min_samples: int = 3
    state_cache_ttl_s: int = 300

    # --- Abnormality thresholds (rule detector; tuned on train folds in E02) ---
    abnormal_z: float = 3.5                # |intensity z-score| gate
    abnormal_new_zone_km: float = 1.5      # distance beyond nearest zone
    abnormal_interval_z: float = 3.0       # inter-detection gap gate
    abstain_min_obs: int = 2               # incident obs below this -> INSUFFICIENT_EVIDENCE

    # --- Phase 5/6: Sentinel-2 optical corroboration (Copernicus Data Space) ---
    # OAuth2 client_credentials (leave unset -> optical evidence unavailable,
    # fusion proceeds without it by design).
    cdse_client_id: str | None = None
    cdse_client_secret: str | None = None
    cdse_token_url: str = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
    sh_statistics_url: str = "https://sh.dataspace.copernicus.eu/api/v1/statistics"
    s2_data_source: str = "sentinel-2-l2a"
    s2_lookback_days: int = 5              # search window for optical corroboration
    s2_max_cloud_pct: float = 40.0         # skip scenes above this
    s2_timeout_s: int = 30

    # --- Phase 5/6: Open-Meteo historical archive (real weather context) ---
    open_meteo_archive_url: str = "https://archive-api.open-meteo.com/v1/archive"
    weather_cache_ttl_s: int = 3600        # 1h
    weather_timeout_s: int = 10

    # --- Phase 7: validation & release evidence ---
    # Kill switch for Phase 6 external evidence (optical + weather). With
    # False, assessments skip every outbound provider call and record the
    # sources as unavailable (offline-safe bulkhead, exercised by the
    # failure-injection suite).
    external_evidence_enabled: bool = True           # TW_EXTERNAL_EVIDENCE_ENABLED
    # Target row count for the load-test DB growth phase.
    loadtest_db_rows: int = 100_000                  # TW_LOADTEST_DB_ROWS

    # --- Evidence fusion weights (tuned on train folds) ---
    fusion_thermal_weight: float = 0.45
    fusion_optical_weight: float = 0.25
    fusion_weather_weight: float = 0.15
    fusion_context_weight: float = 0.15

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def sync_database_url(self) -> str:
        """Alembic runs on the async engine too; kept for ops tooling that needs a
        psycopg-style URL."""
        return self.database_url.replace("+asyncpg", "")


settings = Settings()
