"""The daily sweep: stale review_ready/failed jobs expire; S3 prefix and scratch go; once a day."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.orm import IngestJob, WorkerHeartbeat
from app.services.ingest_jobs import job_prefix
from app.worker.main import Worker, WorkerSettings
from app.worker.store import SqlStore
from app.worker.sweep import EXPIRE_AFTER, SWEEP_EVERY, run_sweep
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


def test_only_stale_review_ready_and_failed_jobs_expire(env):
    factory, _user, scratch, objects, clock = env
    old = EXPIRE_AFTER + timedelta(hours=1)
    stale_review = aged_job(env, "review_ready", old)
    stale_failed = aged_job(env, "failed", old)
    fresh_review = aged_job(env, "review_ready", EXPIRE_AFTER - timedelta(hours=1))
    stale_running = aged_job(env, "running", old)
    stale_queued = aged_job(env, "queued", old)
    stale_confirmed = aged_job(env, "confirmed", old)
    stale_cancelled = aged_job(env, "cancelled", old, with_files=False)

    expired = run_sweep(factory, objects, scratch, clock)

    assert set(expired) == {stale_review, stale_failed}
    assert status_of(factory, stale_review) == "expired"
    assert status_of(factory, stale_failed) == "expired"
    for untouched, status in [
        (fresh_review, "review_ready"), (stale_running, "running"), (stale_queued, "queued"),
        (stale_confirmed, "confirmed"), (stale_cancelled, "cancelled"),
    ]:
        assert status_of(factory, untouched) == status
    assert sorted(objects.deleted_prefixes) == sorted(job_prefix(i) for i in (stale_review, stale_failed))
    assert not any(k.startswith(job_prefix(stale_review)) for k in objects.objects)
    assert any(k.startswith(job_prefix(fresh_review)) for k in objects.objects)
    assert not (scratch / str(stale_review)).exists()
    assert (scratch / str(fresh_review)).exists()


def test_expired_job_is_not_claimable(env):
    factory, user, scratch, objects, clock = env
    job_id = make_job(factory, user, status="review_ready", stages=("register",))
    with factory() as db:
        db.get(IngestJob, job_id).updated_at = NOW - EXPIRE_AFTER - timedelta(days=1)
        db.commit()
    run_sweep(factory, objects, scratch, clock)
    assert SqlStore(factory, scratch).claim_ready(60) is None


def test_failed_s3_delete_does_not_stop_the_sweep(env):
    factory, _user, scratch, objects, clock = env
    a = aged_job(env, "failed", EXPIRE_AFTER + timedelta(days=1))
    b = aged_job(env, "failed", EXPIRE_AFTER + timedelta(days=2))

    def boom(prefix):
        raise RuntimeError("s3 down")

    objects.delete_prefix = boom
    assert set(run_sweep(factory, objects, scratch, clock)) == {a, b}
    assert status_of(factory, a) == status_of(factory, b) == "expired"
    assert not (scratch / str(a)).exists()


def test_sweep_runs_at_most_once_a_day_across_restarts(env):
    factory, _user, scratch, objects, clock = env
    assert run_sweep(factory, objects, scratch, clock) == []
    late = aged_job(env, "failed", EXPIRE_AFTER + timedelta(days=1))

    clock.now = NOW + SWEEP_EVERY - timedelta(minutes=1)
    assert run_sweep(factory, objects, scratch, clock) is None  # same "day": not due, any process
    assert status_of(factory, late) == "failed"

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
    stale = aged_job(env, "review_ready", EXPIRE_AFTER + timedelta(days=1))
    worker = Worker(
        factory, objects, lambda *a: {}, lambda *a: type("R", (), {"run_one": lambda s: None})(),
        WorkerSettings(scratch_dir=scratch), clock=clock,
    )
    worker.run_once()
    assert status_of(factory, stale) == "expired"
    assert len(objects.deleted_prefixes) == 1
    worker.run_once()
    assert len(objects.deleted_prefixes) == 1
