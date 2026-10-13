"""``ingest_event``: one audit row per ingest-job transition, kept after the task rows are overwritten."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.orm import IngestEvent, IngestJob, IngestTask
from app.worker.main import Worker, WorkerSettings
from app.worker.sweep import EXPIRE_AFTER, run_sweep
from tests.conftest import FakeObjectStore
from tests.test_ingest_confirm import env, paper, proposal  # noqa: F401  (the confirm fixtures)
from tests.test_ingest_jobs import _seed_failed_job, upload
from tests.test_ingest_review import edit_body, make_job, rect
from tests.test_worker import Fake, drain
from tests.worker_support import make_job as make_worker_job
from tests.worker_support import make_session_factory, make_user


def kinds(db, job_id):
    job_id = uuid.UUID(str(job_id))
    rows = db.scalars(select(IngestEvent).where(IngestEvent.job_id == job_id).order_by(IngestEvent.id)).all()
    return [r.kind for r in rows], rows


def test_created_retry_cancel(admin_client, db_session, admin_user, fake_object_store):
    job_id = upload(admin_client).json()["job_id"]
    names, [created] = kinds(db_session, job_id)
    assert names == ["created"] and created.actor_user_id == admin_user.id
    assert created.data["filename"] == "RI_2024_Math_P1.pdf" and created.data["page_count"] == 3

    _seed_failed_job(db_session, job_id)
    assert admin_client.post(f"/api/import/jobs/{job_id}/retry").status_code == 200
    assert admin_client.delete(f"/api/import/jobs/{job_id}").status_code == 204
    names, rows = kinds(db_session, job_id)
    assert names == ["created", "retry", "cancelled"]
    assert rows[1].data["reopened"] == 3 and rows[1].actor_user_id == admin_user.id
    assert rows[2].data["previous_status"] and rows[2].actor_user_id == admin_user.id


def test_proposal_edited(admin_client, db_session, admin_user, fake_object_store):
    job = make_job(db_session, admin_user)
    q = {"number": 7, "question_rects": [rect(2, 50, 90)], "answer_rects": [], "flags": []}
    assert admin_client.put(f"/api/import/jobs/{job.id}/proposal", json=edit_body({"questions": [q]})).status_code == 200
    names, [row] = kinds(db_session, job.id)
    assert names == ["proposal_edited"] and row.actor_user_id == admin_user.id


def test_paper_confirmed_and_skipped(admin_client, db_session, admin_user, env):  # noqa: F811
    setup, meta = env
    job = setup(prop=proposal(paper("q1"), paper("q2", "a2")))
    assert admin_client.post(f"/api/import/jobs/{job.id}/confirm", json={**meta, "paper_label": "q1"}).status_code == 201
    assert admin_client.post(f"/api/import/jobs/{job.id}/skip", json={"paper_label": "q2"}).status_code == 200
    names, rows = kinds(db_session, job.id)
    assert names == ["paper_confirmed", "paper_skipped"]
    assert rows[0].data["paper_id"] and rows[0].data["paper_label"] == "q1" and rows[0].data["job_settled"] is False
    assert rows[1].data["paper_label"] == "q2" and rows[1].data["job_settled"] is True
    assert all(r.actor_user_id == admin_user.id for r in rows)


def test_expired(tmp_path):
    engine, factory = make_session_factory(tmp_path / "w.db")
    user = make_user(factory)
    from app.worker.store import SqlStore

    SqlStore(factory, tmp_path).touch_worker()
    now = datetime(2026, 6, 1, 12, tzinfo=UTC)
    job_id = make_worker_job(factory, user, status="failed")
    with factory() as db:
        db.get(IngestJob, job_id).updated_at = now - EXPIRE_AFTER - timedelta(hours=1)
        db.commit()
    run_sweep(factory, FakeObjectStore(), tmp_path, lambda: now)
    with factory() as db:
        names, [row] = kinds(db, job_id)
    assert names == ["expired"] and row.data["reason"] == "stale"
    engine.dispose()


@pytest.fixture
def worker_env(tmp_path):
    engine, factory = make_session_factory(tmp_path / "w.db")
    user = make_user(factory)
    objects = FakeObjectStore()
    job = make_worker_job(factory, user)
    objects.put(f"tmp/ingest/{job}/source.pdf", b"%PDF source")
    fake = Fake(factory)

    def worker():
        settings = WorkerSettings(scratch_dir=tmp_path / "scratch", poll_seconds=0.01)
        return Worker(factory, objects, lambda f, db: {}, fake.runner_factory(), settings)

    yield factory, job, fake, worker
    engine.dispose()


def test_claim_and_finish_rows_and_retry_keeps_earlier_attempt(worker_env):
    factory, job, fake, make_worker = worker_env
    fake.raise_in_segment = True
    worker = make_worker()
    worker.start()
    drain(worker)
    with factory() as db:
        _, rows = kinds(db, job)
        seg_id = db.scalars(select(IngestTask.id).where(IngestTask.stage == "segment")).one()
        seg = [r for r in rows if r.task_id == seg_id]
        assert [r.kind for r in seg] == ["task_claimed", "task_finished"]
        assert seg[1].data["status"] == "failed" and seg[1].data["error"] == "RuntimeError: kaboom"
        assert seg[1].data["duration_ms"] is not None and "warnings" in seg[1].data
        # every task: exactly one claim and one finish row per attempt
        assert sum(r.kind == "task_claimed" for r in rows) == sum(r.kind == "task_finished" for r in rows)

        fake.raise_in_segment = False
        from app.services.ingest_jobs import retry_job

        retry_job(db.get(IngestJob, job), db)
    worker = make_worker()
    worker.start()
    drain(worker)
    with factory() as db:
        _, rows = kinds(db, job)
        seg = [r for r in rows if r.task_id == seg_id]
        assert [(r.kind, r.data.get("status"), r.data.get("attempt")) for r in seg] == [
            ("task_claimed", None, 1),
            ("task_finished", "failed", 1),
            ("task_claimed", None, 1),
            ("task_finished", "done", 1),
        ]
        assert [r.kind for r in rows].count("retry") == 1
        assert db.scalars(select(IngestTask).where(IngestTask.id == seg_id)).one().attempts == 1
