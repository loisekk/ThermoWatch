"""Assessment pipeline tests — require live DB (auto-skip if down)."""
import pytest

from tests.test_association import requires_db  # reuse the skip gate

pytestmark = pytest.mark.asyncio


@requires_db
class TestAssessment:
    async def test_versioned_and_abstaining(self):
        """Two assessments on one incident: append-only, versions preserved,
        cold-start (no facility) -> INSUFFICIENT_EVIDENCE."""
        from datetime import datetime, timedelta, timezone

        from sqlalchemy import select

        from app.db.base import async_session_factory
        from app.db.models import Assessment
        from app.services.assessment import assess_incident
        from app.services.association import associate_observation
        from tests.test_association import _obs, _purge_all

        t0 = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
        async with async_session_factory() as s:
            await _purge_all(s)
            o = _obs(40.0, -100.0, t0)  # mid-US: no facility in registry
            o.provider_observation_key = "ta-1"
            s.add(o)
            await s.flush()
            iid = (await associate_observation(s, o))[0]
            a1 = await assess_incident(s, iid)
            await s.commit()

            assert a1 is not None
            assert a1.status == "insufficient_evidence"
            assert a1.abstain_reason is not None
            assert "normal state unavailable" in a1.abstain_reason
            assert a1.assessment_version  # versioned

            # Second assessment (state unchanged) -> appended, not overwritten
            o2 = _obs(40.0, -100.0, t0 + timedelta(hours=2))
            o2.provider_observation_key = "ta-2"
            s.add(o2)
            await s.flush()
            await associate_observation(s, o2)
            await assess_incident(s, iid)
            await s.commit()

            rows = (await s.execute(
                select(Assessment).where(Assessment.incident_id == iid)
            )).scalars().all()
            assert len(rows) == 2  # append-only

    async def test_assessment_version_stable_and_deterministic(self):
        from app.services.assessment import assessment_version

        assert assessment_version() == assessment_version()
        assert len(assessment_version()) == 16

    async def test_classify_source_is_a_distribution(self):
        from app.services.assessment import classify_source

        scores = classify_source(3.4, 0.5, "refinery")
        assert set(scores) == set(
            ["refinery", "steel", "gas_flare", "cement", "smelter",
             "waste_incineration", "power_plant", "chemical",
             "unknown_industrial", "natural_fire"]
        )
        assert sum(scores.values()) == pytest.approx(1.0)
        assert scores["refinery"] == max(scores.values())
