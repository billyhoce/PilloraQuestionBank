"""Auto-import job routes (POST/GET/DELETE /api/import/jobs) over a fake object store."""

import hashlib
import uuid
from datetime import UTC, datetime

import fitz
import pytest
from unittest.mock import patch
from sqlalchemy.exc import IntegrityError

from app.models.orm import IngestJob, IngestTask, Paper
from app.services.ingest_jobs import record_filename_metadata


def make_pdf(pages: int = 3) -> bytes:
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page()
    data = doc.tobytes()
    doc.close()
    return data


def upload(client, data=None, name="RI_2024_Math_P1.pdf", content_type="application/pdf"):
    return client.post(
        "/api/import/jobs",
        files={"file": (name, make_pdf() if data is None else data, content_type)},
    )


def test_non_admin_forbidden(public_client, fake_object_store):
    assert upload(public_client).status_code == 403
    assert public_client.get("/api/import/jobs").status_code == 403
    assert public_client.get(f"/api/import/jobs/{uuid.uuid4()}").status_code == 403
    assert public_client.delete(f"/api/import/jobs/{uuid.uuid4()}").status_code == 403
    assert fake_object_store.objects == {}


def test_post_does_not_run_filename_extraction(admin_client, fake_object_store):
    with patch("app.ai.filename_extractor.extract_metadata") as extract:
        assert upload(admin_client).status_code == 201
    extract.assert_not_called()


def test_create_job(admin_client, db_session, admin_user, fake_object_store):
    pdf = make_pdf(3)
    resp = upload(admin_client, pdf)
    assert resp.status_code == 201
    job_id = resp.json()["job_id"]

    key = f"tmp/ingest/{job_id}/source.pdf"
    assert fake_object_store.objects[key] == pdf

    job = db_session.get(IngestJob, uuid.UUID(job_id))
    assert job.status == "queued"
    assert job.created_by == admin_user.id
    assert job.filename == "RI_2024_Math_P1.pdf"
    assert job.source_key == key
    assert job.sha256 == hashlib.sha256(pdf).hexdigest()
    assert job.page_count == 3
    assert job.report is None
    [task] = job.tasks
    assert (task.section, task.stage, task.status) == (None, "register", "ready")


def test_non_pdf_rejected(admin_client, db_session, fake_object_store):
    assert upload(admin_client, b"hello", "a.txt", "text/plain").status_code == 422
    assert db_session.query(IngestJob).count() == 0
    assert fake_object_store.objects == {}


def test_pdf_content_type_but_garbage_bytes_rejected(
    admin_client, db_session, fake_object_store
):
    assert upload(admin_client, b"definitely not a pdf").status_code == 422
    assert db_session.query(IngestJob).count() == 0
    assert fake_object_store.objects == {}


def test_list_is_own_jobs_newest_first_and_filters(
    admin_client, db_session, admin_user, fake_object_store
):
    first = upload(admin_client, name="a.pdf").json()["job_id"]
    second = upload(admin_client, name="b.pdf").json()["job_id"]
    # Another admin's job must not show up.
    from tests.conftest import _create_user
    other = _create_user(db_session, "admin2@test.com", "x", "admin")
    db_session.add(IngestJob(
        created_by=other.id, filename="theirs.pdf", source_key="k", sha256="0" * 64, page_count=1,
    ))
    db_session.flush()
    db_session.get(IngestJob, uuid.UUID(first)).status = "failed"
    # The server default is second-resolution on SQLite; make the order explicit.
    db_session.get(IngestJob, uuid.UUID(first)).created_at = datetime(2026, 1, 1, tzinfo=UTC)
    db_session.get(IngestJob, uuid.UUID(second)).created_at = datetime(2026, 1, 2, tzinfo=UTC)
    db_session.flush()

    rows = admin_client.get("/api/import/jobs").json()["data"]
    assert [r["filename"] for r in rows] == ["b.pdf", "a.pdf"]
    assert rows[0]["id"] == second and rows[0]["status"] == "queued" and rows[0]["created_at"]

    failed = admin_client.get("/api/import/jobs?status=failed").json()["data"]
    assert [r["id"] for r in failed] == [first]
    assert admin_client.get("/api/import/jobs?status=bogus").status_code == 422


def test_get_job_with_tasks(admin_client, fake_object_store):
    job_id = upload(admin_client).json()["job_id"]
    body = admin_client.get(f"/api/import/jobs/{job_id}").json()
    assert body["id"] == job_id and body["status"] == "queued" and body["page_count"] == 3
    assert [(t["stage"], t["section"], t["status"]) for t in body["tasks"]] == [("register", None, "ready")]
    assert admin_client.get(f"/api/import/jobs/{uuid.uuid4()}").status_code == 404


def test_other_admins_job_is_404(admin_client, db_session, fake_object_store):
    from tests.conftest import _create_user
    other = _create_user(db_session, "admin2@test.com", "x", "admin")
    job = IngestJob(created_by=other.id, filename="t.pdf", source_key="k", sha256="0" * 64, page_count=1)
    db_session.add(job)
    db_session.flush()
    assert admin_client.get(f"/api/import/jobs/{job.id}").status_code == 404
    assert admin_client.delete(f"/api/import/jobs/{job.id}").status_code == 404


def test_cancel_marks_cancelled_and_deletes_prefix(
    admin_client, db_session, fake_object_store
):
    job_id = upload(admin_client).json()["job_id"]
    assert admin_client.delete(f"/api/import/jobs/{job_id}").status_code == 204
    assert db_session.get(IngestJob, uuid.UUID(job_id)).status == "cancelled"
    assert fake_object_store.deleted_prefixes == [f"tmp/ingest/{job_id}/"]
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


def test_record_filename_metadata_stores_result(db_session, admin_user, fake_metadata_extractor):
    job = _job(db_session, admin_user)
    out = record_filename_metadata(job, db_session, fake_metadata_extractor)
    assert out == fake_metadata_extractor.result
    assert fake_metadata_extractor.calls == ["RI_2024_Math_P1.pdf"]
    assert db_session.get(IngestJob, job.id).report == {"filename_metadata": fake_metadata_extractor.result}


def test_record_filename_metadata_merges_into_existing_report(db_session, admin_user, fake_metadata_extractor):
    job = _job(db_session, admin_user, report={"warnings": ["x"]})
    record_filename_metadata(job, db_session, fake_metadata_extractor)
    assert job.report == {"warnings": ["x"], "filename_metadata": fake_metadata_extractor.result}


def test_record_filename_metadata_falls_back_to_empty_on_error(db_session, admin_user):
    job = _job(db_session, admin_user)

    def boom(filename, db):
        raise RuntimeError("claude down")

    assert record_filename_metadata(job, db_session, boom) == {}
    assert job.report == {"filename_metadata": {}}


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


def test_retry_unknown_or_other_admins_job_is_404(admin_client, db_session, fake_object_store):
    from tests.conftest import _create_user
    other = _create_user(db_session, "admin2@test.com", "x", "admin")
    job = IngestJob(created_by=other.id, filename="t.pdf", source_key="k", sha256="0" * 64, page_count=1)
    db_session.add(job)
    db_session.flush()
    assert admin_client.post(f"/api/import/jobs/{job.id}/retry").status_code == 404
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
    db_session.flush()
    row = admin_client.get("/api/import/jobs").json()["data"][0]
    assert row["stage"] == "segment"  # the running task
    assert (row["tasks_done"], row["tasks_total"], row["warnings_count"], row["needs_review"]) == (1, 3, 2, True)

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
