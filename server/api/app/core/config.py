from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TW_", env_file=".env", extra="ignore")
    cors_origins: str = "http://localhost:5173"
    ingest_token: str = ""                    # shared secret for POST /ingest/events (optional; set TW_INGEST_TOKEN)
    # Regex allow-list for browser origins (used by CORS + WS). Covers prod, every
    # Vercel preview/deployment URL and localhost — exact-match lists break whenever
    # Vercel rotates a URL, which is exactly the failure class this field kills.
    origin_regex: str = r"https://[a-zA-Z0-9.-]+\.vercel\.app|http://localhost(:\d+)?|http://127\.0\.0\.1(:\d+)?"
    api_v1: str = "/api/v1"
    persistence_day_threshold: int = 5      # FIRMS STA rule
    cell_deg: float = 0.004                  # ~400 m grid proxy (h3 res-9 is the upgrade path)
    max_events: int = 5000

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

settings = Settings()
