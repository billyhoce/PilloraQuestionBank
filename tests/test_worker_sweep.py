"""The daily sweep: settled jobs' scratch goes, pending jobs never expire; once a day."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.orm import IngestJob, WorkerHeartbeat
from app.services.ingest_jobs import job_prefix
from app.worker.main import Worker, WorkerSettings
from app.worker.store import SqlStore
from app.worker.sweep import SWEEP_EVERY, run_sweep
from tests.conftest import FakeObjectStore
from tests.worker_support import make_job, make_session_factory, make_user

NOW = datetime(2026, 6, 1, 12, tzinfo=UTC)


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


@pytest.fixture
def env(tmp_path):
    engine, factory = make_session_factory(tmp_path / "w.db")
    user = make_user(factory)
    store = SqlStore(factory, tmp_path / "scratch")
    store.touch_worker()  # the heartbeat row the sweep claim lives on
    scratch = tmp_path / "scratch"
    scratch.mkdir(exist_ok=True)
    yield factory, user, scratch, FakeObjectStore(), Clock()
    engine.dispose()


def aged_job(env, status, age, with_files=True):
    factory, user, scratch, objects, _clock = env
    job_id = make_job(factory, user, status=status)
    with factory() as db:
        db.get(IngestJob, job_id).updated_at = NOW - age
        db.commit()
    if with_files:
        objects.put(f"tmp/ingest/{job_id}/source.pdf", b"x")
        objects.put(f"tmp/ingest/{job_id}/pages/p01.webp", b"x")
        (scratch / str(job_id)).mkdir()
        (scratch / str(job_id) / "source.pdf").write_bytes(b"x")
    return job_id


def status_of(factory, job_id):
    with factory() as db:
        return db.get(IngestJob, job_id).status


def test_pending_jobs_never_expire(env):
    factory, _user, scratch, objects, clock = env
    ancient = timedelta(days=400)
    review = aged_job(env, "review_ready", ancient)
    failed = aged_job(env, "failed", ancient)
    running = aged_job(env, "running", ancient)
    queued = aged_job(env, "queued", ancient)

    run_sweep(factory, objects, scratch, clock)

    for job_id, status in [(review, "review_ready"), (failed, "failed"), (running, "running"), (queued, "queued")]:
        assert status_of(factory, job_id) == status
        assert (scratch / str(job_id)).exists()
    assert objects.deleted_prefixes == []
    assert any(k.startswith(f"tmp/ingest/{review}/") for k in objects.objects)


def test_sweep_runs_at_most_once_a_day_across_restarts(env):
    factory, _user, scratch, objects, clock = env
    assert run_sweep(factory, objects, scratch, clock) == []
    late = aged_job(env, "cancelled", timedelta(days=9))

    clock.now = NOW + SWEEP_EVERY - timedelta(minutes=1)
    assert run_sweep(factory, objects, scratch, clock) is None  # same "day": not due, any process
    assert (scratch / str(late)).exists()

    clock.now = NOW + SWEEP_EVERY + timedelta(minutes=1)
    assert run_sweep(factory, objects, scratch, clock) == [late]
    with factory() as db:
        assert db.scalars(select(WorkerHeartbeat.last_sweep_at)).one() is not None


def test_cancelled_scratch_removed_after_grace(env):
    factory, _user, scratch, objects, clock = env
    old = aged_job(env, "cancelled", timedelta(days=2), with_files=True)
    recent = aged_job(env, "cancelled", timedelta(hours=1), with_files=True)
    run_sweep(factory, objects, scratch, clock)
    assert not (scratch / str(old)).exists()
    assert (scratch / str(recent)).exists()
    assert status_of(factory, old) == "cancelled"


def test_confirmed_scratch_removed_after_grace(env):
    factory, _user, scratch, objects, clock = env
    old = aged_job(env, "confirmed", timedelta(days=2), with_files=True)
    run_sweep(factory, objects, scratch, clock)
    assert not (scratch / str(old)).exists()
    assert status_of(factory, old) == "confirmed"


def test_worker_sweeps_from_its_loop_once(env):
    factory, _user, scratch, objects, clock = env
    stale = aged_job(env, "cancelled", timedelta(days=9))
    worker = Worker(
        factory, objects, lambda *a: {}, lambda *a: type("R", (), {"run_one": lambda s: None})(),
        WorkerSettings(scratch_dir=scratch), clock=clock,
    )
    worker.run_once()
    assert not (scratch / str(stale)).exists()
    fresh = aged_job(env, "cancelled", timedelta(days=9))
    worker.run_once()
    assert (scratch / str(fresh)).exists()  # not due again the same day
