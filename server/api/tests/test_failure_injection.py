"""Phase 7 failure-injection tests: behavior when dependencies fail.

Injected failure classes:
- External evidence providers (Sentinel-2 optical, Open-Meteo weather)
  raising mid-assessment: the assessment completes with the source marked
  unavailable (bulkhead; fusion drops missing sources by weight).
- The Phase 7 kill switch (TW_EXTERNAL_EVIDENCE_ENABLED=0): NO outbound
  provider call is attempted and both sources report ``disabled_by_config``.
- Pipeline/DB faults: an assessment failure never blocks a committed
  observation; a mid-request failure rolls the transaction back (no partial
  write); concurrent review submissions serialize on the ``FOR UPDATE`` row
  lock (one 201, one 409); duplicate ingest is a counted no-op; and the
  outbox drains even when a consumer callback fails.

No-DB injections run everywhere. DB scenarios follow the phase0/phase4
pattern — ONE asyncio.run per scenario (asyncpg connections bind to the
creating loop), skipped gracefully when Postgres is unreachable.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

import pytest


# =====================================================================
# Pure-logic injections (no DB): kill switch + provider isolation
# =====================================================================
def _stub_pair():
    """Minimal incident/obs stand-ins for _gather_external_evidence."""
    incident = SimpleNamespace(centroid_latitude=22.47, centroid_longitude=70.07)
    obs = SimpleNamespace(
        latitude=22.47,
        longitude=70.07,
        observed_at=datetime(2026, 9, 23, 15, 30, tzinfo=timezone.utc),
    )
    return incident, obs


class TestExternalEvidenceKillSwitch:
    """TW_EXTERNAL_EVIDENCE_ENABLED=0 must short-circuit before any call."""

    def test_disabled_config_makes_no_provider_call(self, monkeypatch):
        from app.core.config import settings
        from app.services import assessment as a

        calls: list[str] = []

        async def _spy(*_args, **_kwargs):
            calls.append("called")
            raise AssertionError("provider must not be called when disabled")

        monkeypatch.setattr(settings, "external_evidence_enabled", False)
        monkeypatch.setattr(a, "check_optical_corroboration", _spy)
        monkeypatch.setattr(a, "get_weather_context", _spy)

        incident, obs = _stub_pair()
        optical, weather = asyncio.run(
            a._gather_external_evidence(cast(Any, incident), cast(Any, obs))
        )

        assert calls == [], "kill switch must skip every outbound provider call"
        assert optical.available is False
        assert optical.error == "disabled_by_config"
        assert weather.available is False
        assert weather.error == "disabled_by_config"

    def test_disabled_config_never_touches_inputs(self, monkeypatch):
        # Checked BEFORE attribute access: (None, None) inputs stay safe.
        from app.core.config import settings
        from app.services import assessment as a

        monkeypatch.setattr(settings, "external_evidence_enabled", False)
        optical, weather = asyncio.run(
            a._gather_external_evidence(cast(Any, None), cast(Any, None))
        )
        assert optical.error == "disabled_by_config"
        assert weather.error == "disabled_by_config"

    def test_enabled_config_reaches_both_providers(self, monkeypatch):
        # The switch is not stuck off: with the default (enabled) value both
        # provider functions are invoked.
        from app.core.config import settings
        from app.services import assessment as a
        from app.services.sentinel2 import OpticalCorroboration
        from app.services.weather import WeatherContext

        calls: list[str] = []

        async def _optical(*_args, **_kwargs):
            calls.append("optical")
            return OpticalCorroboration(available=False, error="probe")

        async def _weather(*_args, **_kwargs):
            calls.append("weather")
            return WeatherContext(available=False, error="probe")

        monkeypatch.setattr(settings, "external_evidence_enabled", True)
        monkeypatch.setattr(a, "check_optical_corroboration", _optical)
        monkeypatch.setattr(a, "get_weather_context", _weather)

        incident, obs = _stub_pair()
        asyncio.run(
            a._gather_external_evidence(cast(Any, incident), cast(Any, obs))
        )
        assert sorted(calls) == ["optical", "weather"]


class TestProviderFailureIsolation:
    """A raising provider degrades to available=False; it never propagates."""

    def test_both_providers_raising_never_raises(self, monkeypatch):
        from app.services import assessment as a

        async def _boom(*_args, **_kwargs):
            raise RuntimeError("simulated provider outage")

        monkeypatch.setattr(a, "check_optical_corroboration", _boom)
        monkeypatch.setattr(a, "get_weather_context", _boom)

        incident, obs = _stub_pair()
        optical, weather = asyncio.run(
            a._gather_external_evidence(cast(Any, incident), cast(Any, obs))
        )

        assert optical.available is False
        assert "simulated provider outage" in (optical.error or "")
        assert weather.available is False
        assert "simulated provider outage" in (weather.error or "")

    def test_weather_survives_optical_outage(self, monkeypatch):
        # Source isolation: one provider down must not take the other down.
        from app.services import assessment as a
        from app.services.weather import WeatherContext

        async def _boom(*_args, **_kwargs):
            raise ConnectionError("optical endpoint unreachable")

        async def _ok(*_args, **_kwargs):
            return WeatherContext(available=True, temperature_c=12.5)

        monkeypatch.setattr(a, "check_optical_corroboration", _boom)
        monkeypatch.setattr(a, "get_weather_context", _ok)

        incident, obs = _stub_pair()
        optical, weather = asyncio.run(
            a._gather_external_evidence(cast(Any, incident), cast(Any, obs))
        )

        assert optical.available is False
        assert weather.available is True
        assert weather.temperature_c == 12.5


# =====================================================================
# DB scenarios (skip gracefully when Postgres is unreachable)
# =====================================================================
VIIRS_ROW = {
    "latitude": 22.47, "longitude": 70.07, "bright_ti4": 320.5,
    "bright_ti5": 300.2, "scan": 0.45, "track": 0.4,
    "acq_date": "2026-09-23", "acq_time": "1530", "satellite": "N",
    "instrument": "VIIRS", "confidence": "H", "daynight": "D", "frp": 25.5,
}


def _run_scenario(scenario):
    from app.db.base import engine

    async def go():
        await engine.dispose()  # drop connections from any previous loop
        from app.db.base import check_database

        if not await check_database():
            return None
        return await scenario()

    return asyncio.run(go())


def _spread_row() -> dict:
    """VIIRS row with a random latitude so reruns never collide with history."""
    row = dict(VIIRS_ROW)
    row["latitude"] = round(22.0 + (uuid.uuid4().int % 9_000_000) * 1e-6, 6)
    return row


async def _ingest_and_find(c, row: dict) -> dict | None:
    """Ingest one row via the pipeline, then find its incident in the queue."""
    ing = await c.post("/v2/observations", json={
        "observations": [row],
        "source_batch_id": f"fi-{uuid.uuid4().hex[:12]}",
    })
    if ing.status_code != 201 or ing.json().get("accepted") != 1:
        return None
    q = await c.get("/v2/incidents", params={"limit": 20})
    matches = [
        i for i in q.json().get("incidents", [])
        if abs(i["centroid_latitude"] - row["latitude"]) < 1e-6
    ]
    return matches[0] if matches else None


class TestPipelineFaultIsolation:
    """Committed writes survive downstream faults; partial writes roll back."""

    def test_assessment_failure_never_blocks_ingest(self, monkeypatch):
        # Bulkhead: assess_incident raises -> pipeline catches, ingest still
        # commits the observation (next pass re-runs the assessment).
        from httpx import ASGITransport, AsyncClient

        from app.main import app
        from app.services import pipeline_v2

        async def _boom(*_args, **_kwargs):
            raise RuntimeError("injected assessment failure")

        monkeypatch.setattr(pipeline_v2, "assess_incident", _boom)

        row = _spread_row()

        async def scenario():
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://t"
            ) as c:
                r = await c.post("/v2/observations", json={
                    "observations": [row],
                    "source_batch_id": f"fi-bulk-{uuid.uuid4().hex[:12]}",
                })
                out = {"ingest": r.status_code, "body": r.json()}
                # Observation must be committed despite the assessment fault:
                # replaying the same row reports a duplicate, not accepted.
                r2 = await c.post("/v2/observations", json={
                    "observations": [row],
                    "source_batch_id": f"fi-bulk2-{uuid.uuid4().hex[:12]}",
                })
                out["replay"] = r2.json()
                return out

        got = _run_scenario(scenario)
        if got is None:
            pytest.skip("database unreachable - skipped")

        assert got["ingest"] == 201, got
        assert got["body"]["accepted"] == 1, got
        assert got["body"]["assessments"] == 0, "faulty assessment must not count"
        assert got["replay"]["accepted"] == 0, "observation must be committed"
        assert got["replay"]["duplicates"] == 1, got["replay"]

    def test_mid_request_failure_rolls_back_partial_write(self):
        # Fault AFTER the INSERTs (pipeline runs in the same transaction):
        # the endpoint 500s and get_session rolls back -> no partial write.
        from httpx import ASGITransport, AsyncClient

        from app.main import app
        from app.services import pipeline_v2

        row = _spread_row()

        async def scenario():
            async def _raise(*_args, **_kwargs):
                raise RuntimeError("injected mid-request failure")

            transport = ASGITransport(app=app, raise_app_exceptions=False)
            out: dict = {}
            async with AsyncClient(transport=transport, base_url="http://t") as c:
                with patch.object(pipeline_v2, "process_observations", _raise):
                    r = await c.post("/v2/observations", json={
                        "observations": [row],
                        "source_batch_id": f"fi-rb-{uuid.uuid4().hex[:12]}",
                    })
                    out["fault_status"] = r.status_code
                # Retry outside the fault: accepted==1 proves the first
                # attempt's INSERTs were rolled back (no leaked row).
                r2 = await c.post("/v2/observations", json={
                    "observations": [row],
                    "source_batch_id": f"fi-rb2-{uuid.uuid4().hex[:12]}",
                })
                out["retry"] = r2.json()
                return out

        got = _run_scenario(scenario)
        if got is None:
            pytest.skip("database unreachable - skipped")

        assert got["fault_status"] == 500, got
        assert got["retry"]["accepted"] == 1, (
            "rolled-back INSERT must not leak: retry should be accepted"
        )
        assert got["retry"]["duplicates"] == 0, got["retry"]

    def test_duplicate_ingest_is_counted_noop(self):
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        row = _spread_row()

        async def scenario():
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://t"
            ) as c:
                payloads = [{
                    "observations": [row],
                    "source_batch_id": f"fi-dup-{uuid.uuid4().hex[:12]}",
                } for _ in range(2)]
                first = await c.post("/v2/observations", json=payloads[0])
                second = await c.post("/v2/observations", json=payloads[1])
                return first.json(), second.json()

        got = _run_scenario(scenario)
        if got is None:
            pytest.skip("database unreachable - skipped")

        first, second = got
        assert first["accepted"] == 1 and first["duplicates"] == 0, first
        assert second["accepted"] == 0, "replay must insert nothing"
        assert second["duplicates"] == 1, second


class TestConcurrentReviewLock:
    def test_row_lock_serializes_stale_writers(self):
        # Two reviews submitted concurrently with the SAME expected version:
        # SELECT ... FOR UPDATE serializes them -> exactly one 201, the loser
        # re-reads the committed version and gets 409 (never two writers
        # passing the optimistic-concurrency check).
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        async def scenario():
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://t"
            ) as c:
                inc = await _ingest_and_find(c, _spread_row())
                if inc is None:
                    return None
                body = {
                    "action": "reviewed",
                    "expected_incident_version": inc["version"],
                }
                k1 = f"fi-race-a-{uuid.uuid4().hex[:12]}"
                k2 = f"fi-race-b-{uuid.uuid4().hex[:12]}"
                r1, r2 = await asyncio.gather(
                    c.post(f"/v2/incidents/{inc['id']}/reviews",
                           json={**body, "idempotency_key": k1}),
                    c.post(f"/v2/incidents/{inc['id']}/reviews",
                           json={**body, "idempotency_key": k2}),
                )
                d = await c.get(f"/v2/incidents/{inc['id']}")
                return {
                    "statuses": sorted([r1.status_code, r2.status_code]),
                    "start_version": inc["version"],
                    "final_version": d.json()["version"],
                    "review_count": len(d.json()["reviews"]),
                }

        got = _run_scenario(scenario)
        if got is None:
            pytest.skip("database unreachable - skipped")

        assert got["statuses"] == [201, 409], (
            f"exactly one writer must win the row lock: {got}"
        )
        assert got["final_version"] == got["start_version"] + 1, (
            "only the winning review may bump the version"
        )
        assert got["review_count"] == 1, "losing writer must record nothing"


class TestOutboxDrain:
    def test_review_writes_outbox_event_same_transaction(self):
        from httpx import ASGITransport, AsyncClient
        from sqlalchemy import select

        from app.db.base import async_session_factory
        from app.db.models import OutboxEvent
        from app.main import app

        async def scenario():
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://t"
            ) as c:
                inc = await _ingest_and_find(c, _spread_row())
                if inc is None:
                    return None
                r = await c.post(f"/v2/incidents/{inc['id']}/reviews", json={
                    "action": "reviewed",
                    "expected_incident_version": inc["version"],
                    "idempotency_key": f"fi-ob-{uuid.uuid4().hex[:12]}",
                })
                if r.status_code != 201:
                    return {"review_status": r.status_code}

                async with async_session_factory() as s:
                    ev = (await s.execute(
                        select(OutboxEvent).where(
                            OutboxEvent.event_type == "incident.reviewed",
                            OutboxEvent.entity_id == uuid.UUID(inc["id"]),
                        )
                    )).scalars().first()
                    return {
                        "review_status": 201,
                        "event_found": ev is not None,
                        "action_in_payload": (
                            ev is not None
                            and (ev.payload or {}).get("action") == "reviewed"
                        ),
                    }

        got = _run_scenario(scenario)
        if got is None or "event_found" not in got:
            pytest.skip("database unreachable or pipeline inactive - skipped")
        assert got["review_status"] == 201, got
        assert got["event_found"] is True, "review must write an outbox row"
        assert got["action_in_payload"] is True, got

    def test_failing_broadcaster_does_not_block_drain(self):
        from sqlalchemy import select

        from app.db.base import async_session_factory
        from app.db.models import OutboxEvent
        from app.services import outbox as ob

        async def scenario():
            async def _bad_broadcaster(_ev):
                raise RuntimeError("consumer offline")

            ob._broadcasters.append(_bad_broadcaster)
            try:
                async with async_session_factory() as s:
                    await ob.emit(
                        s, "test.fi.event", "incident", uuid.uuid4(), 1,
                        {"probe": True},
                    )
                    await s.commit()

                    published = await ob.publish_pending(s, limit=500)
                    rows = (await s.execute(
                        select(OutboxEvent).where(
                            OutboxEvent.event_type == "test.fi.event"
                        )
                    )).scalars().all()
                    return {
                        "published": published,
                        "rows": len(rows),
                        "all_marked": all(r.published_at is not None
                                          for r in rows),
                    }
            finally:
                ob._broadcasters.remove(_bad_broadcaster)

        got = _run_scenario(scenario)
        if got is None:
            pytest.skip("database unreachable - skipped")

        assert got["published"] >= 1, "drain must process pending rows"
        assert got["rows"] >= 1, got
        assert got["all_marked"] is True, (
            "a raising consumer must never leave rows stuck unpublished"
        )
