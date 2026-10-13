"""Each ingest-job lifecycle event is one INFO record carrying the job id."""

import logging
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.log_context import ContextFilter
from app.models.orm import IngestJob, IngestTask
from app.worker.main import Worker, WorkerSettings
from app.worker.sweep import EXPIRE_AFTER, run_sweep
from tests.conftest import FakeObjectStore
from tests.test_ingest_confirm import env, paper, proposal  # noqa: F401  (the confirm fixtures)
from tests.test_ingest_jobs import _seed_failed_job, upload
from tests.test_ingest_review import PROPOSAL, edit_body, make_job, rect
from tests.test_worker import Fake, drain
from tests.worker_support import make_job as make_worker_job
from tests.worker_support import make_session_factory, make_user


class _Collect(logging.Handler):
    def __init__(self):
        super().__init__(logging.INFO)
        self.records = []
        self.addFilter(ContextFilter())  # what the JSON handler does in production

    def emit(self, record):
        self.records.append(record)


@pytest.fixture
def records():
    handler, root = _Collect(), logging.getLogger()
    previous = root.level
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    yield handler.records
    root.removeHandler(handler)
    root.setLevel(previous)


def events(records, job_id, func="ingest_job"):
    """{step: record} of the lifecycle records stamped with ``job_id``."""
    found = {}
    for r in records:
        fields = getattr(r, "fields", None) or {}
        if fields.get("func") == func and r.job_id == str(job_id):
            assert r.levelno == logging.INFO
            found.setdefault(fields["step"], []).append(r)
    return found


def test_created_cancelled_retried(admin_client, db_session, admin_user, fake_object_store, records):
    job_id = upload(admin_client).json()["job_id"]
    [created] = events(records, job_id)["created"]
    assert created.fields["filename"] == "RI_2024_Math_P1.pdf"
    assert created.fields["page_count"] == 3 and created.fields["size"] > 0
    assert len(created.fields["sha256"]) == 64 and created.fields["user_id"] == admin_user.id

    _seed_failed_job(db_session, job_id)
    assert admin_client.post(f"/api/import/jobs/{job_id}/retry").status_code == 200
    [retry] = events(records, job_id)["retry"]
    assert retry.fields["reopened"] == 3

    assert admin_client.delete(f"/api/import/jobs/{job_id}").status_code == 204
    assert len(events(records, job_id)["cancelled"]) == 1


def test_confirmed_and_skipped(admin_client, db_session, env, records):  # noqa: F811
    setup, meta = env
    job = setup(prop=proposal(paper("q1"), paper("q2", "a2")))
    assert admin_client.post(f"/api/import/jobs/{job.id}/confirm", json={**meta, "paper_label": "q1"}).status_code == 201
    [confirmed] = events(records, job.id)["paper_confirmed"]
    assert confirmed.fields["paper_id"] and confirmed.fields["paper_label"] == "q1"
    assert admin_client.post(f"/api/import/jobs/{job.id}/skip", json={"paper_label": "q2"}).status_code == 200
    assert len(events(records, job.id)["paper_skipped"]) == 1


def test_proposal_saved_event(admin_client, db_session, admin_user, fake_object_store, records):
    job = make_job(db_session, admin_user)
    q = {"number": 7, "question_rects": [rect(2, 50, 90)], "answer_rects": [], "flags": []}
    assert admin_client.put(f"/api/import/jobs/{job.id}/proposal", json=edit_body({"questions": [q]})).status_code == 200
    assert len(events(records, job.id)["proposal_saved"]) == 1


def test_expired_event(tmp_path, records):
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
    assert len(events(records, job_id)["expired"]) == 1
    engine.dispose()


# --- the worker: runner events, proposal stored, traceback ---------------------------------

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


def test_worker_logs_claim_finish_and_proposal(worker_env, records):
    factory, job, _fake, make_worker = worker_env
    worker = make_worker()
    worker.start()
    drain(worker)
    tasks = events(records, job, func="ingest_task")
    assert len(tasks["claimed"]) == 4 and len(tasks["finished"]) == 4
    finished = tasks["finished"][0].fields
    assert finished["status"] == "done" and finished["duration_s"] >= 0
    assert len(events(records, job)["proposal_stored"]) == 1


def test_failing_stage_stores_truncated_traceback_and_logs_error(worker_env, records):
    factory, job, fake, make_worker = worker_env
    fake.raise_in_segment = True
    worker = make_worker()
    worker.start()
    drain(worker)
    with factory() as db:
        seg = db.scalars(select(IngestTask).where(IngestTask.stage == "segment")).one()
        assert seg.status == "failed" and seg.error == "RuntimeError: kaboom"
        assert "RuntimeError: kaboom" in seg.traceback and len(seg.traceback) <= 4096
        register = db.scalars(select(IngestTask).where(IngestTask.stage == "register")).one()
        assert register.traceback is None
    errors = [r for r in records if r.levelno == logging.ERROR and r.exc_info and r.job_id == str(job)]
    assert errors and errors[0].exc_info[0] is RuntimeError
    # a retry clears the stored traceback
    fake.raise_in_segment = False
    with factory() as db:
        from app.services.ingest_jobs import retry_job

        retry_job(db.get(IngestJob, job), db)
        db.commit()
        seg = db.scalars(select(IngestTask).where(IngestTask.stage == "segment")).one()
        assert seg.traceback is None


def test_runner_truncates_the_traceback_to_the_configured_tail(tmp_path):
    from dataclasses import replace

    from pipeline.config import PipelineConfig
    from pipeline.registry import JOB, CPU, Registry, Stage
    from pipeline.runner import Runner
    from pipeline.sqlite_store import SQLiteStore

    def boom(ctx):
        raise ValueError("the end of it")

    store = SQLiteStore(tmp_path / "p.db")
    runner = Runner(
        store, Registry([Stage("register", JOB, CPU, boom)]), lambda j: tmp_path / j,
        replace(PipelineConfig(), traceback_chars=40), sleep=lambda s: None,
    )
    runner.submit("j1", tmp_path / "x.pdf")
    runner.run()
    [task] = store.tasks("j1")
    assert task.status == "failed" and task.error == "ValueError: the end of it"
    assert len(task.traceback) == 40 and task.traceback.endswith("ValueError: the end of it\n")
    runner.retry("j1")
    assert store.tasks("j1")[0].traceback == ""
