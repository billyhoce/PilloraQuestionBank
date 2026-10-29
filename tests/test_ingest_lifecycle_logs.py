"""Each ingest-job lifecycle event is one INFO sentence logged under the job's context."""

import logging
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.log_context import ContextFilter
from app.models.orm import IngestJob, IngestTask
from app.worker.main import Worker, WorkerSettings
from tests.conftest import FakeObjectStore
from tests.test_ingest_confirm import env, paper, proposal  # noqa: F401  (the confirm fixtures)
from tests.test_ingest_jobs import _seed_failed_job, upload
from tests.test_ingest_review import PROPOSAL, edit_body, make_job, rect
from tests.test_worker import Fake, drain
from tests.worker_support import PDF_BYTES, make_job as make_worker_job
from tests.worker_support import make_session_factory, make_user


class _Collect(logging.Handler):
    def __init__(self):
        super().__init__(logging.INFO)
        self.records = []
        self.addFilter(ContextFilter())  # what the stdout handler does in production

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


def events(records, job_id, starting):
    """The INFO records of ``job_id`` whose message starts with ``starting``; none repeats the id."""
    found = [r for r in records if r.job_id == str(job_id) and r.getMessage().startswith(starting)]
    for r in found:
        assert r.levelno == logging.INFO and str(job_id) not in r.getMessage()
    return found


def test_created_cancelled_retried(admin_client, db_session, admin_user, fake_object_store, records):
    job_id = upload(admin_client).json()["job_id"]
    [created] = events(records, job_id, "job created")
    assert created.getMessage().startswith("job created for 'RI_2024_Math_P1.pdf' (")
    assert created.user_id == str(admin_user.id)  # from the request context, not the message

    _seed_failed_job(db_session, job_id)
    assert admin_client.post(f"/api/import/jobs/{job_id}/retry").status_code == 200
    [retry] = events(records, job_id, "retry")
    assert retry.getMessage() == "retry: 3 task(s) reopened"

    assert admin_client.delete(f"/api/import/jobs/{job_id}").status_code == 204
    assert [r.getMessage() for r in events(records, job_id, "job cancelled")] == ["job cancelled (was running)"]


def test_confirmed_and_skipped(admin_client, db_session, env, records):  # noqa: F811
    setup, meta = env
    job = setup(prop=proposal(paper("q1"), paper("q2", "a2")))
    assert admin_client.post(f"/api/import/jobs/{job.id}/confirm", json={**meta, "paper_label": "q1"}).status_code == 201
    [confirmed] = events(records, job.id, "paper q1 confirmed as paper ")
    assert "job settled" not in confirmed.getMessage()
    assert admin_client.post(f"/api/import/jobs/{job.id}/skip", json={"paper_label": "q2"}).status_code == 200
    assert [r.getMessage() for r in events(records, job.id, "paper q2")] == ["paper q2 skipped; job settled"]


def test_proposal_saved_event(admin_client, db_session, admin_user, fake_object_store, records):
    job = make_job(db_session, admin_user)
    q = {"number": 7, "question_rects": [rect(2, 50, 90)], "answer_rects": [], "flags": []}
    assert admin_client.put(f"/api/import/jobs/{job.id}/proposal", json=edit_body({"questions": [q]})).status_code == 200
    assert len(events(records, job.id, "review edits saved")) == 1


# --- the worker: runner events, proposal stored, traceback ---------------------------------

@pytest.fixture
def worker_env(tmp_path):
    engine, factory = make_session_factory(tmp_path / "w.db")
    user = make_user(factory)
    objects = FakeObjectStore()
    job = make_worker_job(factory, user)
    objects.put(f"tmp/ingest/{job}/source.pdf", PDF_BYTES)
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
    started = events(records, job, "task started")
    finished = events(records, job, "task done in ")
    assert len(started) == 4 and len(finished) == 4
    assert {r.stage for r in finished} == {r.stage for r in started}  # the stage rides in the context
    assert len(events(records, job, "proposal stored: ")) == 1


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
