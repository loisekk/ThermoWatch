"""Golden-fixture association tests — require live DB (auto-skip if down)."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

pytestmark = pytest.mark.asyncio


def _db_up() -> bool:
    """Synchronous connectivity probe (module import must never hang)."""
    try:
        from app.db.base import engine

        async def probe() -> None:
            try:
                async with engine.connect() as c:
                    await c.execute(sa.text("SELECT 1"))
            finally:
                # Pooled asyncpg connections are event-loop-bound; dispose so
                # the next probe (fresh asyncio.run loop) starts with a clean
                # pool instead of failing on a connection from a dead loop.
                try:
                    await engine.dispose()
                except Exception:
                    pass

        asyncio.run(probe())
        return True
    except Exception:
        return False


requires_db = pytest.mark.skipif(not _db_up(), reason="DB unavailable")


def _obs(lat, lon, when):
    from app.db.models import Observation

    return Observation(
        provider="firms", provider_observation_key=f"k-{lat}-{lon}-{when}",
        observed_at=when, location=f"POINT({lon} {lat})",
        latitude=lat, longitude=lon, sensor="viirs", platform="snpp",
        scan=0.4, track=0.4, confidence="high", day_night="day",
        raw_payload={},
    )


# Every provider_observation_key these tests insert — purged before each test
# so previously committed runs never collide with the unique constraint or
# pollute the spatiotemporal association queries.
_FIXTURE_KEYS = [
    "ga-0", "ga-1", "ga-2", "gb-1", "gb-2", "gc-1", "gc-2", "ta-1", "ta-2",
]


async def _purge_all(session) -> None:
    """Delete fixture rows (and the incidents they created) from prior runs."""
    from app.db.models import (
        Assessment,
        IncidentCandidate,
        IncidentObservation,
        Observation,
    )

    obs_ids = list((await session.execute(
        sa.select(Observation.id).where(
            Observation.provider_observation_key.in_(_FIXTURE_KEYS)
        )
    )).scalars())
    if not obs_ids:
        return
    inc_ids = list((await session.execute(
        sa.select(IncidentObservation.incident_id).where(
            IncidentObservation.observation_id.in_(obs_ids)
        )
    )).scalars())
    if inc_ids:
        await session.execute(
            sa.delete(Assessment).where(Assessment.incident_id.in_(inc_ids)))
        await session.execute(
            sa.delete(IncidentObservation).where(
                IncidentObservation.incident_id.in_(inc_ids)))
        await session.execute(
            sa.delete(IncidentCandidate).where(
                IncidentCandidate.id.in_(inc_ids)))
    await session.execute(
        sa.delete(Observation).where(Observation.id.in_(obs_ids)))
    await session.commit()


@requires_db
class TestAssociation:
    async def test_three_close_observations_one_incident(self):
        from sqlalchemy import select

        from app.db.base import async_session_factory
        from app.db.models import IncidentCandidate, IncidentObservation
        from app.services.association import associate_observation

        t0 = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
        async with async_session_factory() as s:
            await _purge_all(s)
            touched: list[str] = []
            for i, mins in enumerate((0, 30, 60)):
                o = _obs(22.47 + i * 1e-4, 70.07, t0 + timedelta(minutes=mins))
                o.provider_observation_key = f"ga-{i}"
                s.add(o)
                await s.flush()
                touched += await associate_observation(s, o)
            await s.commit()
            assert len(set(touched)) == 1  # ONE incident
            inc = await s.get(IncidentCandidate, touched[0])
            assert inc is not None
            assert inc.observation_count == 3
            assert inc.version == 3  # bumped per link
            links = (await s.execute(
                select(IncidentObservation)
                .where(IncidentObservation.incident_id == inc.id)
            )).scalars().all()
            assert len(links) == 3
            for link in links:
                assert link.rationale["rule_version"]
                assert link.rationale["decision"] in ("linked", "created_new")

    async def test_distant_observation_creates_new_incident(self):
        from app.db.base import async_session_factory
        from app.services.association import associate_observation

        async with async_session_factory() as s:
            await _purge_all(s)
            o1 = _obs(22.47, 70.07, datetime(2026, 9, 1, 12, tzinfo=timezone.utc))
            o1.provider_observation_key = "gb-1"
            s.add(o1)
            await s.flush()
            i1 = (await associate_observation(s, o1))[0]

            o2 = _obs(28.62, 77.10,
                      datetime(2026, 9, 1, 13, tzinfo=timezone.utc))  # ~700 km away
            o2.provider_observation_key = "gb-2"
            s.add(o2)
            await s.flush()
            i2 = (await associate_observation(s, o2))[0]
            await s.commit()
            assert i1 != i2

    async def test_stale_observation_outside_time_window(self):
        """An observation 8 days later than an incident must NOT merge into it."""
        from app.db.base import async_session_factory
        from app.services.association import associate_observation

        async with async_session_factory() as s:
            await _purge_all(s)
            o1 = _obs(22.47, 70.07, datetime(2026, 9, 1, 12, tzinfo=timezone.utc))
            o1.provider_observation_key = "gc-1"
            s.add(o1)
            await s.flush()
            i1 = (await associate_observation(s, o1))[0]

            o2 = _obs(22.47, 70.07,
                      datetime(2026, 9, 9, 12, tzinfo=timezone.utc))  # 8 days later
            o2.provider_observation_key = "gc-2"
            s.add(o2)
            await s.flush()
            i2 = (await associate_observation(s, o2))[0]
            await s.commit()
            assert i1 != i2  # 72 h window exceeded -> new incident
