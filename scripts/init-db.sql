-- ThermoWatch Phase 0: enable required extensions (server-level).
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- NOTE: memory tuning (shared_buffers, effective_cache_size, work_mem,
-- maintenance_work_mem) is a server-level parameter set — it cannot be applied
-- per-database and is configured via the postgres -c flags in docker-compose.
