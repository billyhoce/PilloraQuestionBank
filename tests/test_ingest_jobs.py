"""Auto-import job routes (POST/GET/DELETE /api/import/jobs) over a fake object store."""

import hashlib
import uuid
from datetime import UTC, datetime

import fitz
import pytest
from unittest.mock import patch
from sqlalchemy.exc import IntegrityError

from app.models.orm import IngestJob, IngestTask, Paper
from app.services.ingest_jobs import extract_paper_metadata_safely, record_paper_metadata


def make_pdf(pages: int = 3) -> bytes:
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page()
    data = doc.tobytes()
    doc.close()
    return data


def start_upload(client, name="RI_2024_Math_P1.pdf", size=1000):
    return client.post("/api/import/uploads", json={"filename": name, "size": size})


def upload(client, data=None, name="RI_2024_Math_P1.pdf", content_type="application/pdf", store=None):
    """The whole direct-to-S3 flow with the browser's S3 POST simulated by a put into the fake store.
    Returns the ``uploaded`` response (``{"job_id", "status"}``)."""
    from app.deps import get_object_store
    from app.main import app

    data = make_pdf() if data is None else data
    created = start_upload(client, name, max(len(data), 1))
    if created.status_code != 201:
        return created
    job_id = created.json()["job_id"]
    store = store or app.dependency_overrides[get_object_store]()
    store.put(f"ingest/{job_id}/source.pdf", data, content_type)
    return client.post(f"/api/import/jobs/{job_id}/uploaded")


def test_non_admin_forbidden(public_client, fake_object_store):
    assert start_upload(public_client).status_code == 403
    assert public_client.post(f"/api/import/jobs/{uuid.uuid4()}/uploaded").status_code == 403
    assert public_client.get("/api/import/jobs").status_code == 403
    assert public_client.get(f"/api/import/jobs/{uuid.uuid4()}").status_code == 403
    assert public_client.delete(f"/api/import/jobs/{uuid.uuid4()}").status_code == 403
    assert fake_object_store.objects == {}


def test_presign_response_carries_the_conditions(admin_client, db_session, admin_user, fake_object_store):
    resp = start_upload(admin_client, "RI_2024_Math_P1.pdf", 5000)
    assert resp.status_code == 201
    body = resp.json()
    job_id = body["job_id"]
    key = f"ingest/{job_id}/source.pdf"
    assert body["url"] and body["fields"]["key"] == key
    assert body["fields"]["Content-Type"] == "application/pdf"
    policy = body["fields"]["policy"]
    assert policy["expiration_seconds"] == 15 * 60
    assert {"Content-Type": "application/pdf"} in policy["conditions"]
    assert ["content-length-range", 1, 100 * 1024 * 1024] in policy["conditions"]

    job = db_session.get(IngestJob, uuid.UUID(job_id))
    assert (job.status, job.created_by, job.filename, job.source_key) == (
        "awaiting_upload", admin_user.id, "RI_2024_Math_P1.pdf", key,
    )
    assert job.tasks == []
    assert fake_object_store.objects == {}


@pytest.mark.parametrize("size", [0, -5, 100 * 1024 * 1024 + 1])
def test_presign_rejects_sizes_outside_the_range(admin_client, db_session, fake_object_store, size):
    assert start_upload(admin_client, size=size).status_code == 422
    assert db_session.query(IngestJob).count() == 0


def test_awaiting_upload_job_is_listed_and_cancellable(admin_client, db_session, fake_object_store):
    job_id = start_upload(admin_client).json()["job_id"]
    [row] = admin_client.get("/api/import/jobs").json()["data"]
    assert (row["id"], row["status"], row["tasks_total"]) == (job_id, "awaiting_upload", 0)
    assert admin_client.get("/api/import/jobs?status=review_ready,failed").json()["data"] == []
    assert admin_client.post(f"/api/import/jobs/{job_id}/retry").status_code == 409
    assert admin_client.delete(f"/api/import/jobs/{job_id}").status_code == 204
    assert fake_object_store.deleted_prefixes == [f"ingest/{job_id}/"]
    assert db_session.get(IngestJob, uuid.UUID(job_id)).status == "cancelled"


def test_uploaded_happy_path(admin_client, db_session, admin_user, fake_object_store):
    pdf = make_pdf(3)
    resp = upload(admin_client, pdf)
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]
    assert resp.json()["status"] == "queued"

    key = f"ingest/{job_id}/source.pdf"
    assert fake_object_store.objects[key] == pdf
    job = db_session.get(IngestJob, uuid.UUID(job_id))
    assert job.status == "queued"
    assert job.created_by == admin_user.id
    assert job.filename == "RI_2024_Math_P1.pdf"
    assert job.source_key == key
    # the upload does not read the PDF: the worker's register task fills these in
    assert job.sha256 is None and job.page_count is None
    assert job.report is None
    [task] = job.tasks
    assert (task.section, task.stage, task.status) == (None, "register", "ready")


def test_uploaded_does_not_run_filename_extraction(admin_client, fake_object_store):
    with patch("app.ai.filename_extractor.extract_metadata") as extract:
        assert upload(admin_client).status_code == 200
    extract.assert_not_called()


def test_uploaded_missing_object(admin_client, db_session, fake_object_store):
    job_id = start_upload(admin_client).json()["job_id"]
    resp = admin_client.post(f"/api/import/jobs/{job_id}/uploaded")
    assert resp.status_code == 409
    job = db_session.get(IngestJob, uuid.UUID(job_id))
    assert job.status == "awaiting_upload" and job.tasks == []


def test_uploaded_wrong_size(admin_client, db_session, fake_object_store, monkeypatch):
    empty = upload(admin_client, b"")
    assert empty.status_code == 422
    monkeypatch.setattr("app.services.ingest_jobs.MAX_UPLOAD_BYTES", 10)
    big = upload(admin_client, b"x" * 11)
    assert big.status_code == 422
    assert {j.status for j in db_session.query(IngestJob)} == {"awaiting_upload"}
    assert db_session.query(IngestTask).count() == 0


def test_uploaded_wrong_content_type(admin_client, db_session, fake_object_store):
    assert upload(admin_client, b"hello", "a.pdf", "text/plain").status_code == 422
    assert db_session.query(IngestTask).count() == 0


def test_uploaded_twice_inserts_one_task(admin_client, db_session, fake_object_store):
    job_id = upload(admin_client).json()["job_id"]
    assert admin_client.post(f"/api/import/jobs/{job_id}/uploaded").status_code == 409
    assert db_session.query(IngestTask).filter(IngestTask.job_id == uuid.UUID(job_id)).count() == 1


def test_uploaded_on_other_states_and_unknown_job(admin_client, db_session, fake_object_store):
    job_id = upload(admin_client).json()["job_id"]
    db_session.get(IngestJob, uuid.UUID(job_id)).status = "failed"
    assert admin_client.post(f"/api/import/jobs/{job_id}/uploaded").status_code == 409
    assert admin_client.post(f"/api/import/jobs/{uuid.uuid4()}/uploaded").status_code == 404


def test_pdf_content_type_but_garbage_bytes_still_creates_a_job(
    admin_client, db_session, fake_object_store
):
    """Validation is the worker's job now: the upload accepts the bytes, register fails them."""
    resp = upload(admin_client, b"definitely not a pdf")
    assert resp.status_code == 200
    assert db_session.query(IngestJob).count() == 1
    assert len(fake_object_store.objects) == 1


def test_list_is_all_admins_jobs_newest_first_and_filters(
    admin_client, db_session, admin_user, fake_object_store
):
    first = upload(admin_client, name="a.pdf").json()["job_id"]
    second = upload(admin_client, name="b.pdf").json()["job_id"]
    # Another admin's job shows up too (oldest here).
    from tests.conftest import _create_user
    other = _create_user(db_session, "admin2@test.com", "x", "admin")
    theirs = IngestJob(
        created_by=other.id, filename="theirs.pdf", source_key="k", sha256="0" * 64, page_count=1,
        created_at=datetime(2025, 1, 1, tzinfo=UTC),
    )
    db_session.add(theirs)
    db_session.flush()
    db_session.get(IngestJob, uuid.UUID(first)).status = "failed"
    # The server default is second-resolution on SQLite; make the order explicit.
    db_session.get(IngestJob, uuid.UUID(first)).created_at = datetime(2026, 1, 1, tzinfo=UTC)
    db_session.get(IngestJob, uuid.UUID(second)).created_at = datetime(2026, 1, 2, tzinfo=UTC)
    db_session.flush()

    rows = admin_client.get("/api/import/jobs").json()["data"]
    assert [r["filename"] for r in rows] == ["b.pdf", "a.pdf", "theirs.pdf"]
    assert rows[0]["id"] == second and rows[0]["status"] == "queued" and rows[0]["created_at"]

    failed = admin_client.get("/api/import/jobs?status=failed").json()["data"]
    assert [r["id"] for r in failed] == [first]
    assert admin_client.get("/api/import/jobs?status=bogus").status_code == 422
    assert admin_client.get("/api/import/jobs?status=failed,bogus").status_code == 422
    several = admin_client.get("/api/import/jobs?status=failed,review_ready").json()["data"]
    assert [r["id"] for r in several] == [first]
    assert admin_client.get("/api/import/jobs?status=queued,failed").json()["data"][0]["id"] == second

    by_id = admin_client.get(f"/api/import/jobs?job_id={theirs.id}").json()["data"]
    assert [r["id"] for r in by_id] == [str(theirs.id)]


def test_list_filters_by_paper_id(admin_client, db_session, admin_user, fake_object_store):
    from tests.conftest import _create_user
    other = _create_user(db_session, "admin2@test.com", "x", "admin")
    via_ids = IngestJob(created_by=other.id, filename="x.pdf", source_key="k", sha256="0" * 64,
                        page_count=1, confirmed_paper_ids=[9001])
    via_paper = IngestJob(created_by=other.id, filename="y.pdf", source_key="k", sha256="0" * 64, page_count=1)
    db_session.add_all([via_ids, via_paper])
    db_session.flush()
    assert [r["id"] for r in admin_client.get("/api/import/jobs?paper_id=9001").json()["data"]] == [str(via_ids.id)]
    assert admin_client.get("/api/import/jobs?paper_id=1234").json()["data"] == []


def test_get_job_with_tasks(admin_client, fake_object_store):
    job_id = upload(admin_client).json()["job_id"]
    body = admin_client.get(f"/api/import/jobs/{job_id}").json()
    assert body["id"] == job_id and body["status"] == "queued" and body["page_count"] is None
    assert [(t["stage"], t["section"], t["status"]) for t in body["tasks"]] == [("register", None, "ready")]
    assert admin_client.get(f"/api/import/jobs/{uuid.uuid4()}").status_code == 404


def test_other_admins_job_is_visible_and_actionable_to_admins(admin_client, db_session, fake_object_store):
    from tests.conftest import _create_user
    other = _create_user(db_session, "admin2@test.com", "x", "admin")
    job = IngestJob(created_by=other.id, filename="t.pdf", source_key="k", sha256="0" * 64, page_count=1)
    db_session.add(job)
    db_session.flush()
    assert admin_client.get(f"/api/import/jobs/{job.id}").status_code == 200
    assert admin_client.delete(f"/api/import/jobs/{job.id}").status_code == 204


def test_cancel_marks_cancelled_and_deletes_prefix(
    admin_client, db_session, fake_object_store
):
    job_id = upload(admin_client).json()["job_id"]
    assert admin_client.delete(f"/api/import/jobs/{job_id}").status_code == 204
    assert db_session.get(IngestJob, uuid.UUID(job_id)).status == "cancelled"
    assert fake_object_store.deleted_prefixes == [f"ingest/{job_id}/"]
    assert fake_object_store.objects == {}
    # Cancelling twice is a conflict, not a second delete.
    assert admin_client.delete(f"/api/import/jobs/{job_id}").status_code == 409


def test_cancel_confirmed_job_conflicts(
    admin_client, db_session, fake_object_store
):
    job_id = upload(admin_client).json()["job_id"]
    db_session.get(IngestJob, uuid.UUID(job_id)).status = "confirmed"
    db_session.flush()
    assert admin_client.delete(f"/api/import/jobs/{job_id}").status_code == 409
    assert fake_object_store.deleted_prefixes == []


def test_failed_s3_delete_does_not_fail_cancel(
    admin_client, db_session, fake_object_store
):
    job_id = upload(admin_client).json()["job_id"]

    def boom(prefix):
        raise RuntimeError("s3 down")

    fake_object_store.delete_prefix = boom
    assert admin_client.delete(f"/api/import/jobs/{job_id}").status_code == 204
    assert db_session.get(IngestJob, uuid.UUID(job_id)).status == "cancelled"


def test_job_level_task_is_unique_per_stage(admin_client, db_session, fake_object_store):
    job_id = uuid.UUID(upload(admin_client).json()["job_id"])
    db_session.add(IngestTask(job_id=job_id, section=None, stage="register"))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_deleting_job_cascades_tasks_and_unlinks_paper(db_session, admin_user):
    job = IngestJob(created_by=admin_user.id, filename="t.pdf", source_key="k", sha256="0" * 64, page_count=1)
    job.tasks.append(IngestTask(section=None, stage="register"))
    db_session.add(job)
    db_session.flush()
    db_session.delete(job)
    db_session.flush()
    assert db_session.query(IngestTask).count() == 0


def test_s3_object_store_roundtrip_and_delete_prefix(mock_s3):
    from app.storage.object_store import S3ObjectStore

    store = S3ObjectStore()
    store.put("tmp/ingest/a/source.pdf", b"%PDF", "application/pdf")
    store.put("tmp/ingest/a/other.bin", b"x")
    store.put("tmp/ingest/b/source.pdf", b"keep")
    assert store.get("tmp/ingest/a/source.pdf") == b"%PDF"
    assert store.presign("tmp/ingest/a/source.pdf").startswith("http")
    assert store.delete_prefix("tmp/ingest/a/") == 2
    keys = [o["Key"] for o in mock_s3.list_objects_v2(Bucket="test-bucket").get("Contents", [])]
    assert keys == ["tmp/ingest/b/source.pdf"]


def _job(db_session, admin_user, report=None):
    job = IngestJob(
        created_by=admin_user.id, filename="RI_2024_Math_P1.pdf", source_key="k",
        sha256="0" * 64, page_count=1, report=report,
    )
    db_session.add(job)
    db_session.flush()
    return job


def test_record_paper_metadata_stores_results_by_paper_key(db_session, admin_user):
    job = _job(db_session, admin_user)
    record_paper_metadata(job, db_session, {"q1": {"year": 2024}, "a2": {"year": 2023}})
    assert db_session.get(IngestJob, job.id).report == {
        "paper_metadata": {"q1": {"year": 2024}, "a2": {"year": 2023}}
    }


def test_record_paper_metadata_merges_into_existing_report(db_session, admin_user):
    job = _job(db_session, admin_user, report={"warnings": ["x"], "filename_metadata": {"a": 1}})
    record_paper_metadata(job, db_session, {"q1": {"year": 2024}})
    assert job.report == {
        "warnings": ["x"], "filename_metadata": {"a": 1}, "paper_metadata": {"q1": {"year": 2024}},
    }


def test_extract_paper_metadata_safely_passes_the_cover(db_session, fake_metadata_extractor):
    out = extract_paper_metadata_safely(fake_metadata_extractor, "f.pdf", db_session, b"%PDF")
    assert out == fake_metadata_extractor.result
    assert fake_metadata_extractor.calls == ["f.pdf"]


def test_extract_paper_metadata_safely_falls_back_to_filename_then_empty(db_session):
    seen = []

    def cover_breaks(filename, db, cover=None):
        seen.append(cover)
        if cover is not None:
            raise RuntimeError("claude down")
        return {"year": 2024}

    assert extract_paper_metadata_safely(cover_breaks, "f.pdf", db_session, b"%PDF") == {"year": 2024}
    assert seen == [b"%PDF", None]

    def boom(filename, db, cover=None):
        raise RuntimeError("claude down")

    assert extract_paper_metadata_safely(boom, "f.pdf", db_session, b"%PDF") == {}
    assert extract_paper_metadata_safely(boom, "f.pdf", db_session, None) == {}


# --- retry, progress and worker liveness -----------------------------------


def _tasks(db_session, job_id):
    db_session.expire_all()
    return {t.stage: t for t in db_session.get(IngestJob, uuid.UUID(job_id)).tasks}


def _seed_failed_job(db_session, job_id):
    """register done; segment failed; split done (stale, downstream); report blocked."""
    job = db_session.get(IngestJob, uuid.UUID(job_id))
    t = _tasks(db_session, job_id)["register"]
    t.status, t.attempts = "done", 1
    for stage, status, attempts in (("segment", "failed", 3), ("split", "done", 1), ("report", "blocked", 0)):
        job.tasks.append(IngestTask(section=None, stage=stage, status=status, attempts=attempts, error="boom" if status == "failed" else ""))
    job.status = "failed"
    job.error = "segment failed: boom"
    db_session.flush()


def test_retry_resets_failed_blocked_and_downstream(admin_client, db_session, fake_object_store):
    job_id = upload(admin_client).json()["job_id"]
    _seed_failed_job(db_session, job_id)

    resp = admin_client.post(f"/api/import/jobs/{job_id}/retry")
    assert resp.status_code == 200
    assert resp.json()["reopened"] == 3
    tasks = _tasks(db_session, job_id)
    assert tasks["register"].status == "done"  # upstream of the failure: untouched
    assert tasks["segment"].status == "ready" and tasks["segment"].attempts == 0
    assert tasks["segment"].error == ""
    assert tasks["split"].status == "pending"  # downstream finished task, waits for segment
    assert tasks["report"].status == "pending"
    body = admin_client.get(f"/api/import/jobs/{job_id}").json()
    assert body["status"] == "running" and body["error"] is None  # re-derived; the worker picks it up


def test_retry_with_nothing_broken_is_a_noop(admin_client, db_session, fake_object_store):
    job_id = upload(admin_client).json()["job_id"]
    resp = admin_client.post(f"/api/import/jobs/{job_id}/retry")
    assert resp.status_code == 200 and resp.json()["reopened"] == 0
    assert resp.json()["status"] == "queued"


@pytest.mark.parametrize("status", ["cancelled", "confirmed", "expired"])
def test_retry_of_api_owned_job_conflicts(admin_client, db_session, fake_object_store, status):
    job_id = upload(admin_client).json()["job_id"]
    db_session.get(IngestJob, uuid.UUID(job_id)).status = status
    db_session.flush()
    assert admin_client.post(f"/api/import/jobs/{job_id}/retry").status_code == 409


def test_retry_of_partially_decided_job_conflicts(admin_client, db_session, fake_object_store):
    job_id = upload(admin_client).json()["job_id"]
    job = db_session.get(IngestJob, uuid.UUID(job_id))
    job.status = "review_ready"
    job.report = {"review_outcome": {"q1": "skipped"}}
    db_session.flush()
    resp = admin_client.post(f"/api/import/jobs/{job_id}/retry")
    assert resp.status_code == 409
    assert "already confirmed or skipped" in resp.json()["detail"]


def test_retry_non_admin_forbidden(public_client):
    assert public_client.post(f"/api/import/jobs/{uuid.uuid4()}/retry").status_code == 403


def test_retry_unknown_job_is_404(admin_client, db_session, fake_object_store):
    from tests.conftest import _create_user
    other = _create_user(db_session, "admin2@test.com", "x", "admin")
    job = IngestJob(created_by=other.id, filename="t.pdf", source_key="k", sha256="0" * 64, page_count=1)
    db_session.add(job)
    db_session.flush()
    assert admin_client.post(f"/api/import/jobs/{uuid.uuid4()}/retry").status_code == 404


def test_list_and_detail_report_progress(admin_client, db_session, fake_object_store):
    job_id = upload(admin_client).json()["job_id"]
    row = admin_client.get("/api/import/jobs").json()["data"][0]
    assert (row["stage"], row["tasks_done"], row["tasks_total"]) == (None, 0, 1)

    job = db_session.get(IngestJob, uuid.UUID(job_id))
    reg = job.tasks[0]
    reg.status, reg.warnings, reg.finished_at = "done", ["w1", "w2"], datetime(2026, 1, 1, tzinfo=UTC)
    job.tasks.append(IngestTask(section=None, stage="segment", status="running"))
    job.tasks.append(IngestTask(section=None, stage="split", status="pending", needs_review=True))
    job.tasks.append(IngestTask(section="q1", stage="locate", status="failed"))
    job.tasks.append(IngestTask(section="q1", stage="render", status="blocked"))
    db_session.flush()
    row = admin_client.get("/api/import/jobs").json()["data"][0]
    assert row["stage"] == "segment"  # the running task
    assert (row["tasks_done"], row["tasks_total"], row["warnings_count"], row["needs_review"]) == (1, 5, 2, True)
    assert row["tasks_failed"] == 2  # failed and blocked: what Retry would reopen

    job.tasks[1].status = "done"
    job.tasks[1].finished_at = datetime(2026, 1, 2, tzinfo=UTC)
    db_session.flush()
    detail = admin_client.get(f"/api/import/jobs/{job_id}").json()
    assert detail["stage"] == "segment"  # nothing running: the latest finished


def test_worker_liveness_from_heartbeat(admin_client, db_session, fake_object_store):
    from datetime import timedelta
    from app.models.orm import WorkerHeartbeat
    from app.services.ingest_jobs import WORKER_STALE_SECONDS

    job_id = upload(admin_client).json()["job_id"]
    listing = admin_client.get("/api/import/jobs").json()
    assert listing["worker_alive"] is False and listing["heartbeat_age_s"] is None  # never started

    now = datetime.now(UTC)
    db_session.add(WorkerHeartbeat(id=1, seen_at=now - timedelta(seconds=10)))
    db_session.flush()
    listing = admin_client.get("/api/import/jobs").json()
    assert listing["worker_alive"] is True and 9 <= listing["heartbeat_age_s"] <= 15
    assert admin_client.get(f"/api/import/jobs/{job_id}").json()["worker_alive"] is True

    db_session.get(WorkerHeartbeat, 1).seen_at = now - timedelta(seconds=WORKER_STALE_SECONDS + 30)
    db_session.flush()
    listing = admin_client.get("/api/import/jobs").json()
    assert listing["worker_alive"] is False and listing["heartbeat_age_s"] >= WORKER_STALE_SECONDS
    detail = admin_client.get(f"/api/import/jobs/{job_id}").json()
    assert detail["worker_alive"] is False and detail["status"] == "queued"


# --- per-job Claude cost (report["cost"]) --------------------------------------------------


def test_record_usage_accumulates_cost_across_calls_and_logs_request_id(
    db_session, admin_user, caplog, monkeypatch
):
    import logging

    from app.ai import job_cost
    from app.log_context import log_context

    job = _job(db_session, admin_user, report={"filename_metadata": {"a": 1}})
    monkeypatch.setattr(job_cost, "session_factory", lambda: (lambda: _Borrowed(db_session)))
    usage = type("U", (), {"input_tokens": 1000, "output_tokens": 200, "cache_read_input_tokens": 50})()

    caplog.set_level(logging.INFO, logger="pillora")
    with log_context(job_id=str(job.id)):
        job_cost.record_usage("ingest_segment", "claude-haiku-4-5", usage, "req_a")
        job_cost.record_usage("extract_metadata", "claude-haiku-4-5-20251001", usage, "req_b")
    job_cost.record_usage("label_question", "claude-haiku-4-5", usage, "req_c")  # no job: not counted

    db_session.refresh(job)
    cost = job.report["cost"]
    assert cost["calls"] == 2
    assert cost["input_tokens"] == 2000 and cost["output_tokens"] == 400 and cost["cache_hit"] == 100
    assert cost["cost_usd"] == pytest.approx(2 * (1000 * 1.0 + 50 * 0.1 + 200 * 5.0) / 1e6)
    assert job.report["filename_metadata"] == {"a": 1}
    logged = {rid: r for r in caplog.records for rid in ("req_a", "req_b", "req_c") if rid in r.getMessage()}
    assert set(logged) == {"req_a", "req_b", "req_c"}
    assert logged["req_a"].job_id == str(job.id)


class _Borrowed:
    """Lets the cost writer use the test session without closing it."""

    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self.db

    def __exit__(self, *a):
        return False


def test_metadata_call_cost_survives_the_paper_metadata_write(db_session, admin_user, monkeypatch):
    from app.ai import job_cost
    from app.log_context import log_context

    job = _job(db_session, admin_user)
    monkeypatch.setattr(job_cost, "session_factory", lambda: (lambda: _Borrowed(db_session)))
    usage = type("U", (), {"input_tokens": 10, "output_tokens": 5})()

    def extractor(filename, db, cover=None):
        with log_context(job_id=str(job.id)):
            job_cost.record_usage("extract_metadata", "claude-haiku-4-5-20251001", usage, "req_m")
        return {"school_id": 1}

    metadata = extract_paper_metadata_safely(extractor, job.filename, db_session, b"%PDF")
    record_paper_metadata(job, db_session, {"q1": metadata})
    assert job.report["paper_metadata"] == {"q1": {"school_id": 1}}
    assert job.report["cost"]["calls"] == 1


def test_job_prefix_is_derived_from_the_stored_source_key():
    from app.services.ingest_jobs import job_prefix, source_key_for

    jid = uuid.uuid4()
    assert source_key_for(jid) == f"ingest/{jid}/source.pdf"
    assert job_prefix(source_key_for(jid)) == f"ingest/{jid}/"
    # A job created before the move keeps its legacy prefix.
    assert job_prefix(f"tmp/ingest/{jid}/source.pdf") == f"tmp/ingest/{jid}/"


def test_cancel_legacy_job_deletes_its_legacy_prefix(admin_client, db_session, admin_user, fake_object_store):
    jid = uuid.uuid4()
    key = f"tmp/ingest/{jid}/source.pdf"
    fake_object_store.put(key, b"%PDF", "application/pdf")
    db_session.add(IngestJob(
        id=jid, created_by=admin_user.id, filename="x.pdf", source_key=key,
        sha256="0" * 64, page_count=1, status="review_ready",
    ))
    db_session.commit()
    assert admin_client.delete(f"/api/import/jobs/{jid}").status_code == 204
    assert fake_object_store.deleted_prefixes == [f"tmp/ingest/{jid}/"]
    assert fake_object_store.objects == {}
