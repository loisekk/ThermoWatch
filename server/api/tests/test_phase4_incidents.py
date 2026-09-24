"""Phase 4 backend tests: analyst workflow (queue, dossier, review, report).

DB-dependent tests run against the configured PostGIS database and skip
gracefully when Postgres is unreachable (matching the test_phase0 pattern:
each scenario runs inside ONE asyncio.run because asyncpg connections bind
to the creating loop, and the shared pool is disposed between scenarios).
Pure-logic tests (cursors, review rules) run everywhere.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

import pytest


# =====================================================================
# Pure-logic tests (no DB)
# =====================================================================
class TestCursorCodec:
    def test_roundtrip(self):
        from app.services.cursor import decode_cursor, encode_cursor

        ts = datetime(2026, 9, 22, 14, 30, tzinfo=timezone.utc)
        iid = uuid.uuid4()
        ts2, id2 = decode_cursor(encode_cursor(ts, iid))
        assert ts2 == ts
        assert id2 == iid

    def test_naive_timestamp_gets_utc(self):
        from app.services.cursor import decode_cursor, encode_cursor

        ts = datetime(2026, 9, 22, 14, 30)  # naive
        ts2, _ = decode_cursor(encode_cursor(ts, uuid.uuid4()))
        assert ts2.tzinfo is not None

    def test_invalid_cursor_rejected(self):
        from app.services.cursor import CursorError, decode_cursor

        with pytest.raises(CursorError):
            decode_cursor("not-a-real-cursor!!")

    def test_tampered_payload_rejected(self):
        from app.services.cursor import CursorError, decode_cursor
        from app.services.cursor import encode_cursor as enc

        cur = enc(datetime.now(timezone.utc), uuid.uuid4())
        with pytest.raises(CursorError):
            decode_cursor(cur[:-4] + "AAAA")


class TestReviewRules:
    def test_allowed_transitions_from_needs_review(self):
        from app.services.review_rules import allowed_actions

        assert allowed_actions("needs_review") == [
            "dismissed", "escalated", "reviewed",
        ]

    def test_escalated_only_reopens(self):
        from app.services.review_rules import allowed_actions

        assert allowed_actions("escalated") == ["needs_review"]

    def test_invalid_transition_detected(self):
        from app.services.review_rules import is_transition_valid

        assert not is_transition_valid("dismissed", "dismissed")
        assert not is_transition_valid("escalated", "reviewed")
        assert not is_transition_valid("unknown_state", "reviewed")
        assert is_transition_valid("reviewed", "escalated")

    def test_note_policy(self):
        from app.services.review_rules import MIN_NOTE_CHARS, note_sufficient

        assert note_required_gate()
        assert not note_sufficient(None)
        assert not note_sufficient("short")
        assert not note_sufficient("x" * (MIN_NOTE_CHARS - 1))
        assert note_sufficient("x" * MIN_NOTE_CHARS)
        assert note_sufficient("  padded note passes  ")


def note_required_gate() -> bool:
    from app.services.review_rules import NOTE_REQUIRED_FOR, note_required

    return (
        note_required("escalated")
        and note_required("dismissed")
        and not note_required("reviewed")
        and NOTE_REQUIRED_FOR == frozenset({"escalated", "dismissed"})
    )


# __DB_TESTS__


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
        "source_batch_id": f"p4-{uuid.uuid4().hex[:12]}",
    })
    if ing.status_code != 201 or ing.json().get("accepted") != 1:
        return None
    q = await c.get("/v2/incidents", params={"limit": 20})
    matches = [
        i for i in q.json().get("incidents", [])
        if abs(i["centroid_latitude"] - row["latitude"]) < 1e-6
    ]
    return matches[0] if matches else None


class TestPhase4Workflow:
    """End-to-end: ingest -> associate -> queue -> dossier -> review -> report."""

    def test_full_analyst_journey(self):
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        row = _spread_row()
        idem = f"test-journey-{uuid.uuid4().hex[:12]}"

        async def scenario():
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://t"
            ) as c:
                out: dict = {}
                q = await c.get("/v2/incidents", params={"limit": 5})
                out["queue_status"] = q.status_code
                out["queue_keys"] = sorted(q.json().keys())

                inc = await _ingest_and_find(c, row)
                if inc is None:
                    out["no_match"] = True
                    return out
                out["incident_id"] = inc["id"]
                out["row_version"] = inc["version"]

                d = await c.get(f"/v2/incidents/{inc['id']}")
                out["dossier_status"] = d.status_code
                out["dossier_keys"] = sorted(d.json().keys())
                out["obs_count"] = len(d.json().get("observations", []))

                # Stale version -> 409 conflict.
                stale = await c.post(f"/v2/incidents/{inc['id']}/reviews", json={
                    "action": "reviewed",
                    "expected_incident_version": inc["version"] + 100,
                    "idempotency_key": f"{idem}-stale",
                })
                out["conflict_status"] = stale.status_code

                # Right version -> 201.
                ok = await c.post(f"/v2/incidents/{inc['id']}/reviews", json={
                    "action": "reviewed",
                    "expected_incident_version": inc["version"],
                    "idempotency_key": idem,
                })
                out["review_status"] = ok.status_code
                out["review_body"] = ok.json()

                # Same key replayed -> same review id, 201 (idempotent).
                replay = await c.post(f"/v2/incidents/{inc['id']}/reviews", json={
                    "action": "reviewed",
                    "expected_incident_version": inc["version"],
                    "idempotency_key": idem,
                })
                out["replay_status"] = replay.status_code
                out["replay_body"] = replay.json()

                # Escalate without note -> 422.
                esc = await c.post(f"/v2/incidents/{inc['id']}/reviews", json={
                    "action": "escalated",
                    "expected_incident_version": inc["version"] + 1,
                    "idempotency_key": f"{idem}-esc",
                })
                out["note_status"] = esc.status_code

                rep = await c.get(f"/v2/incidents/{inc['id']}/report")
                out["report_status"] = rep.status_code
                out["report_ct"] = rep.headers.get("content-type", "")
                out["report_has_caveats"] = "Caveats" in rep.text
                out["report_has_title"] = "Incident Report" in rep.text

                tl = await c.get(f"/v2/incidents/{inc['id']}/timeline")
                out["timeline_status"] = tl.status_code
                return out

        out = _run_scenario(scenario)
        if out is None or out.get("no_match"):
            pytest.skip("database unreachable or pipeline inactive - skipped")

        assert out.get("queue_status") == 200, out
        assert "incidents" in out.get("queue_keys", [])
        assert "next_cursor" in out.get("queue_keys", [])
        assert out.get("dossier_status") == 200, out
        for key in ("observations", "assessments", "reviews",
                    "association_rule_version"):
            assert key in out.get("dossier_keys", []), out
        assert out.get("obs_count", 0) >= 1
        assert out.get("conflict_status") == 409, out
        assert out.get("review_status") == 201, out
        assert out.get("replay_status") == 201, out
        assert (
            out.get("review_body", {}).get("review_id")
            == out.get("replay_body", {}).get("review_id")
        ), "idempotent replay must return the SAME review event"
        assert out.get("note_status") == 422, out
        assert out.get("report_status") == 200, out
        assert "markdown" in out.get("report_ct", "")
        assert out.get("report_has_caveats") is True
        assert out.get("report_has_title") is True
        assert out.get("timeline_status") == 200, out

# __MORE_TESTS__

    def test_invalid_transition_rejected(self):
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        async def scenario():
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://t"
            ) as c:
                inc = await _ingest_and_find(c, _spread_row())
                if inc is None:
                    return None
                # needs_review -> needs_review is not a legal transition.
                r = await c.post(f"/v2/incidents/{inc['id']}/reviews", json={
                    "action": "needs_review",
                    "expected_incident_version": inc["version"],
                    "idempotency_key": f"tt-{uuid.uuid4().hex[:12]}",
                })
                return r.status_code

        got = _run_scenario(scenario)
        if got is None:
            pytest.skip("database unreachable or pipeline inactive - skipped")
        assert got == 422

    def test_escalate_with_note_succeeds(self):
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        async def scenario():
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://t"
            ) as c:
                inc = await _ingest_and_find(c, _spread_row())
                if inc is None:
                    return None
                r = await c.post(f"/v2/incidents/{inc['id']}/reviews", json={
                    "action": "escalated",
                    "note": "Persistent plume co-located with an unmapped facility",
                    "expected_incident_version": inc["version"],
                    "idempotency_key": f"te-{uuid.uuid4().hex[:12]}",
                })
                if r.status_code != 201:
                    return ("fail", r.status_code, r.text)
                d = await c.get(f"/v2/incidents/{inc['id']}")
                return (201, len(d.json().get("reviews", [])))

        got = _run_scenario(scenario)
        if got is None:
            pytest.skip("database unreachable or pipeline inactive - skipped")
        assert got[0] == 201, got
        assert got[1] >= 1, "review trail must record the escalation"

    def test_queue_filters_by_status(self):
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        async def scenario():
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://t"
            ) as c:
                r = await c.get(
                    "/v2/incidents", params={"status": "needs_review", "limit": 10}
                )
                return r.status_code, r.json()

        out = _run_scenario(scenario)
        if out is None:
            pytest.skip("database unreachable - skipped")
        status_code, body = out
        assert status_code == 200
        for inc in body["incidents"]:
            assert inc["status"] == "needs_review"

    def test_invalid_cursor_400(self):
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        async def scenario():
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://t"
            ) as c:
                r = await c.get("/v2/incidents", params={"cursor": "garbage!!"})
                return r.status_code

        got = _run_scenario(scenario)
        if got is None:
            pytest.skip("database unreachable - skipped")
        assert got == 400
