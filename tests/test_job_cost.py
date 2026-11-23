"""Per-job Claude cost (``app/ai/job_cost.py``): one ``ingest_claude_call`` row per call, the job
detail's breakdown, each listed job's total and the monthly spend."""

import logging
from datetime import UTC, datetime

import pytest

from app.ai import job_cost
from app.log_context import log_context
from app.models.orm import IngestClaudeCall, IngestJob
from app.services.ingest_events import add_event
from app.services.ingest_jobs import extract_paper_metadata_safely, record_paper_metadata


class _Borrowed:
    """Lets the cost writer use the test session without closing it."""

    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self.db

    def __exit__(self, *a):
        return False


@pytest.fixture
def writer(db_session, monkeypatch):
    monkeypatch.setattr(job_cost, "session_factory", lambda: (lambda: _Borrowed(db_session)))
    return job_cost


def _job(db_session, admin_user):
    job = IngestJob(created_by=admin_user.id, filename="RI_2024_Math_P1.pdf", source_key="k")
    db_session.add(job)
    db_session.flush()
    return job


def _usage(inp=1000, out=200, cached=50):
    return type("U", (), {"input_tokens": inp, "output_tokens": out, "cache_read_input_tokens": cached})()


def _calls(db_session, job):
    return db_session.query(IngestClaudeCall).filter_by(job_id=job.id).order_by(IngestClaudeCall.id).all()


def _row(db_session, job, at, cost, kind="segment", **extra):
    extra.setdefault("model", "claude-haiku-4-5")
    row = IngestClaudeCall(job_id=job.id, at=at, kind=kind, cost_usd=cost, **extra)
    db_session.add(row)
    db_session.flush()
    return row


# --- writes -------------------------------------------------------------------------------


def test_each_call_is_stored_with_its_paper_stage_and_tokens(db_session, admin_user, caplog, writer):
    job = _job(db_session, admin_user)
    caplog.set_level(logging.INFO, logger="pillora")
    with log_context(job_id=str(job.id), stage="segment", task_attempt=1):
        writer.record_usage("find papers", "claude-haiku-4-5", _usage(), "req_a", kind="segment", seconds=2.5)
        with log_context(paper="q1"):
            writer.record_usage(
                "read cover", "claude-haiku-4-5-20251001", _usage(), "req_b", kind="metadata", source="cover"
            )
    writer.record_usage("label", "claude-haiku-4-5", _usage(), "req_c", kind="segment")  # no job: only logged

    segment, metadata = _calls(db_session, job)
    assert (segment.kind, segment.paper_key, segment.stage, segment.attempt, segment.run) == (
        "segment", None, "segment", 1, 0,
    )
    assert (segment.request_id, segment.seconds) == ("req_a", 2.5)
    assert (metadata.kind, metadata.paper_key, metadata.source) == ("metadata", "q1", "cover")
    assert (metadata.input_tokens, metadata.output_tokens, metadata.cache_hit) == (1000, 200, 50)
    assert metadata.cost_usd == pytest.approx((1000 * 1.0 + 50 * 0.1 + 200 * 5.0) / 1e6)
    logged = {rid: r for r in caplog.records for rid in ("req_a", "req_b", "req_c") if rid in r.getMessage()}
    assert set(logged) == {"req_a", "req_b", "req_c"}
    assert logged["req_a"].job_id == str(job.id)


def test_a_call_after_a_retry_is_tagged_with_the_run(db_session, admin_user, writer):
    job = _job(db_session, admin_user)
    with log_context(job_id=str(job.id)):
        writer.record_usage("p", "claude-haiku-4-5", _usage(), kind="segment")
        add_event(db_session, job.id, "retry")
        db_session.flush()
        writer.record_usage("p", "claude-opus-5", _usage(), kind="segment")
    assert [c.run for c in _calls(db_session, job)] == [0, 1]


def test_an_unpriced_model_is_stored_without_a_cost(db_session, admin_user, writer):
    job = _job(db_session, admin_user)
    with log_context(job_id=str(job.id)):
        writer.record_usage("p", "claude-unknown-9", _usage(), kind="segment")
    (call,) = _calls(db_session, job)
    assert call.cost_usd is None and call.input_tokens == 1000
    cost = writer.job_cost(db_session, job.id)
    assert cost["unpriced"] is True and cost["total_usd"] == 0


def test_a_failed_cost_write_does_not_fail_the_call(db_session, admin_user, monkeypatch):
    def broken():
        raise RuntimeError("db down")

    monkeypatch.setattr(job_cost, "session_factory", lambda: broken)
    job = _job(db_session, admin_user)
    with log_context(job_id=str(job.id)):
        job_cost.record_usage("p", "claude-haiku-4-5", _usage(), kind="segment")  # does not raise


def test_metadata_call_cost_survives_the_paper_metadata_write(db_session, admin_user, writer):
    job = _job(db_session, admin_user)

    def extractor(filename, db, cover=None):
        with log_context(job_id=str(job.id), paper="q1"):
            writer.record_usage(
                "m", "claude-haiku-4-5-20251001", _usage(10, 5, 0), "req_m", kind="metadata", source="cover"
            )
        return {"school_id": 1}

    metadata = extract_paper_metadata_safely(extractor, job.filename, db_session, b"%PDF")
    record_paper_metadata(job, db_session, {"q1": metadata})
    assert job.report["paper_metadata"] == {"q1": {"school_id": 1}}
    assert [c.request_id for c in _calls(db_session, job)] == ["req_m"]


# --- reads --------------------------------------------------------------------------------


def test_job_detail_carries_the_cost_breakdown(admin_client, db_session, admin_user):
    job = _job(db_session, admin_user)
    at = datetime(2026, 11, 2, tzinfo=UTC)
    _row(db_session, job, at, 0.25, kind="legacy", model="", input_tokens=900, output_tokens=90)
    _row(db_session, job, at, 0.01, input_tokens=100, output_tokens=10, cache_hit=5)
    _row(db_session, job, at, 0.002, kind="metadata", paper_key="q1", source="cover", run=1, input_tokens=20)

    cost = admin_client.get(f"/api/import/jobs/{job.id}").json()["cost"]
    assert cost["total_usd"] == pytest.approx(0.262)
    assert cost["calls"] == 2  # the legacy row stands for an unknown number of calls
    assert (cost["input_tokens"], cost["output_tokens"], cost["cache_hit"]) == (1020, 100, 5)
    assert cost["unpriced"] is False
    assert [(i["kind"], i["paper_key"], i["source"], i["run"]) for i in cost["items"]] == [
        ("legacy", None, None, 0), ("segment", None, None, 0), ("metadata", "q1", "cover", 1),
    ]


def test_job_detail_cost_is_null_without_calls(admin_client, db_session, admin_user):
    job = _job(db_session, admin_user)
    assert admin_client.get(f"/api/import/jobs/{job.id}").json()["cost"] is None


def test_job_list_carries_each_jobs_cost_and_the_monthly_spend(admin_client, db_session, admin_user):
    spent, idle = _job(db_session, admin_user), _job(db_session, admin_user)
    now = datetime.now(UTC)
    _row(db_session, spent, now, 0.1)
    _row(db_session, spent, now, 0.05)

    body = admin_client.get("/api/import/jobs").json()
    by_id = {j["id"]: j for j in body["data"]}
    assert by_id[str(spent.id)]["cost_usd"] == pytest.approx(0.15)
    assert by_id[str(idle.id)]["cost_usd"] is None
    assert body["spend"]["this_month"]["usd"] == pytest.approx(0.15)
    assert body["spend"]["this_month"]["jobs"] == 1


def test_monthly_spend_counts_calendar_months_in_singapore_time(db_session, admin_user):
    a, b = _job(db_session, admin_user), _job(db_session, admin_user)
    # 1 Nov 00:30 SGT is still 31 Oct in UTC: it counts in November.
    _row(db_session, a, datetime(2026, 10, 31, 16, 30, tzinfo=UTC), 1.0)
    _row(db_session, a, datetime(2026, 11, 20, tzinfo=UTC), 2.0)
    # 31 Oct 23:30 SGT: October.
    _row(db_session, b, datetime(2026, 10, 31, 15, 30, tzinfo=UTC), 4.0)
    # 30 Sep 23:59 SGT: before last month, not counted.
    _row(db_session, b, datetime(2026, 9, 30, 15, 59, tzinfo=UTC), 8.0)

    spend = job_cost.monthly_spend(db_session, now=datetime(2026, 11, 23, 4, tzinfo=UTC))
    assert spend["this_month"] == {"month": "2026-11", "usd": 3.0, "jobs": 1}
    assert spend["last_month"] == {"month": "2026-10", "usd": 4.0, "jobs": 1}


def test_month_bounds_in_january_reach_back_to_december():
    last, this = job_cost.month_bounds(datetime(2027, 1, 5, tzinfo=UTC))
    assert last == datetime(2026, 11, 30, 16, tzinfo=UTC)  # 1 Dec 00:00 SGT
    assert this == datetime(2026, 12, 31, 16, tzinfo=UTC)  # 1 Jan 00:00 SGT
