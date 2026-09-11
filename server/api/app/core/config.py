from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TW_", env_file=".env", extra="ignore")
    cors_origins: str = "http://localhost:5173"
    ingest_token: str = ""                    # shared secret for POST /ingest/events (optional; set TW_INGEST_TOKEN)
    api_v1: str = "/api/v1"
    persistence_day_threshold: int = 5      # FIRMS STA rule
    cell_deg: float = 0.004                  # ~400 m grid proxy (h3 res-9 is the upgrade path)
    max_events: int = 5000

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

settings = Settings()
