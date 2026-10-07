"""SqlStore: the claim, leases, idempotent task creation, atomic completion, job status."""

import threading
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pipeline.outcome import Outcome, done, failed
from pipeline.store import Task, TaskSpec
from sqlalchemy import select

from app.models.orm import IngestJob, IngestTask, WorkerHeartbeat
from app.worker.store import SqlStore, derive_job_status
from tests.worker_support import make_job, make_session_factory, make_user


class Clock:
    def __init__(self):
        self.now = datetime(2026, 1, 1, tzinfo=UTC)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def env(tmp_path):
    engine, factory = make_session_factory(tmp_path / "w.db")
    clock = Clock()
    user = make_user(factory)
    yield factory, user, clock, tmp_path
    engine.dispose()


def store_for(env, **kw):
    factory, _user, clock, tmp_path = env
    return SqlStore(factory, tmp_path / "scratch", clock=clock, **kw)


def test_two_claimers_never_get_the_same_task(env):
    factory, user, _clock, _ = env
    make_job(factory, user)
    a, b = store_for(env), store_for(env)
    first = a.claim_ready(600)
    assert first is not None and first.status == "running" and first.attempts == 1
    assert b.claim_ready(600) is None  # the only ready task is a's


def test_concurrent_claimers_take_distinct_tasks(env):
    factory, user, _clock, _ = env
    for _ in range(4):
        make_job(factory, user)
    claimed, errors = [], []

    def claim():
        try:
            task = store_for(env).claim_ready(600)
            if task:
                claimed.append(task.id)
        except Exception as exc:  # pragma: no cover - would fail the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=claim) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors
    assert len(claimed) == 4 and len(set(claimed)) == 4


def test_claims_oldest_job_first_and_skips_cancelled_jobs(env):
    factory, user, clock, _ = env
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    cancelled = make_job(factory, user, status="cancelled", created_at=t0)
    first = make_job(factory, user, created_at=t0 + timedelta(seconds=1))
    second = make_job(factory, user, created_at=t0 + timedelta(seconds=2))
    store = store_for(env)
    assert store.claim_ready(600).job_id == str(first)
    assert store.claim_ready(600).job_id == str(second)
    assert store.claim_ready(600) is None
    with factory() as db:
        task = db.scalars(select(IngestTask).where(IngestTask.job_id == cancelled)).one()
        assert task.status == "ready"


def test_claim_returns_previous_fingerprint_but_clears_the_row(env):
    factory, user, _clock, _ = env
    job = make_job(factory, user)
    with factory() as db:
        task = db.scalars(select(IngestTask)).one()
        task.fingerprint, task.warnings, task.needs_review = "abc", ["w"], True
        db.commit()
    claimed = store_for(env).claim_ready(600)
    assert (claimed.fingerprint, claimed.warnings, claimed.needs_review) == ("abc", ("w",), True)
    with factory() as db:
        row = db.scalars(select(IngestTask).where(IngestTask.job_id == job)).one()
        assert (row.fingerprint, row.warnings, row.needs_review) == (None, [], False)
        assert row.lease_until is not None


def test_expired_lease_is_reset_and_a_live_one_is_not(env):
    factory, user, clock, _ = env
    make_job(factory, user)
    store = store_for(env)
    task = store.claim_ready(600)
    clock.advance(300)
    assert store.reset_stale(3) == []  # still within the lease
    assert store.heartbeat(task.id, 600)  # refreshed to t+900
    clock.advance(400)
    assert store.reset_stale(3) == []
    clock.advance(600)
    [reset] = store.reset_stale(3)
    assert reset.id == task.id and reset.status == "ready" and reset.lease_until is None
    # the old claimant lost the task: neither completes nor heartbeats
    assert not store.complete(task.id, done())
    assert not store.heartbeat(task.id, 600)
    again = store.claim_ready(600)
    assert again.id == task.id and again.attempts == 2


def test_a_task_that_keeps_expiring_fails_at_the_retry_limit(env):
    factory, user, clock, _ = env
    make_job(factory, user)
    store = store_for(env)
    for _ in range(3):
        store.claim_ready(10)
        clock.advance(11)
        [t] = store.reset_stale(3)
    assert t.status == "failed" and "lease expired" in t.error and t.needs_review


def test_adding_the_same_task_twice_is_a_no_op(env):
    factory, user, _clock, _ = env
    job = make_job(factory, user, stages=())
    store = store_for(env)
    specs = [TaskSpec(str(job), "register"), TaskSpec(str(job), "locate", "q1")]
    assert len(store.add_tasks(specs)) == 2
    assert store.add_tasks(specs) == []
    assert store.add_tasks([TaskSpec(str(job), "register")]) == []
    assert len(store.tasks(str(job))) == 2
    assert all(t.status == "pending" for t in store.tasks(str(job)))


def test_complete_creates_the_fan_out_in_the_same_transaction(env):
    factory, user, _clock, _ = env
    job = make_job(factory, user)
    store = store_for(env)
    task = store.claim_ready(600)
    spawn = [TaskSpec(str(job), "locate", "q1"), TaskSpec(str(job), "render", "q1")]
    assert store.complete(task.id, done(), fingerprint="fp", spawn=spawn)
    tasks = {(t.section, t.stage): t for t in store.tasks(str(job))}
    assert tasks[(None, "register")].status == "done" and tasks[(None, "register")].fingerprint == "fp"
    assert tasks[(None, "register")].duration_ms is not None
    assert tasks[("q1", "locate")].status == "pending"
    # a lost lease creates nothing
    assert not store.complete(task.id, done(), spawn=[TaskSpec(str(job), "locate", "q2")])
    assert ("q2", "locate") not in {(t.section, t.stage) for t in store.tasks(str(job))}


def test_fail_records_the_error_and_no_fingerprint(env):
    factory, user, _clock, _ = env
    job = make_job(factory, user)
    store = store_for(env)
    task = store.claim_ready(600)
    assert store.fail(task.id, failed("boom", warnings=("w",)))
    [t] = store.tasks(str(job))
    assert (t.status, t.error, t.warnings, t.fingerprint) == ("failed", "boom", ("w",), None)
    store.reopen([t.id])
    assert store.tasks(str(job))[0].status == "pending"


def test_heartbeat_row_is_upserted(env):
    factory, user, clock, _ = env
    job = make_job(factory, user)
    store = store_for(env, version="v1")
    store.touch_worker()
    clock.advance(5)
    store.claim_ready(600)
    store.touch_worker(600)
    with factory() as db:
        beat = db.scalars(select(WorkerHeartbeat)).one()
        assert beat.id == 1 and beat.version == "v1" and beat.current_job_id == job


def test_set_job_status_derives_and_leaves_api_owned_states(env):
    factory, user, _clock, _ = env
    job = make_job(factory, user)
    store = store_for(env)
    store.set_job_status(str(job), "done")  # the runner's word is ignored
    with factory() as db:
        assert db.get(IngestJob, job).status == "queued"
    task = store.claim_ready(600)
    store.set_job_status(str(job), "queued")
    with factory() as db:
        assert db.get(IngestJob, job).status == "running"
        db.get(IngestJob, job).status = "cancelled"
        db.commit()
    store.fail(task.id, failed("x"))
    store.set_job_status(str(job), "failed")
    with factory() as db:
        assert db.get(IngestJob, job).status == "cancelled"


def _t(stage, status, section=None, attempts=0, error=""):
    return Task(id=1, job_id="j", section=section, stage=stage, status=status, attempts=attempts, error=error)


@pytest.mark.parametrize(
    "tasks, proposal, expected",
    [
        ([_t("register", "ready")], False, "queued"),
        ([_t("register", "running")], False, "running"),
        ([_t("register", "done", attempts=1), _t("segment", "pending")], False, "running"),
        ([_t("register", "done"), _t("segment", "done"), _t("report", "done")], True, "review_ready"),
        # a failed section still gives a proposal to review
        ([_t("register", "done"), _t("locate", "failed", "q1"), _t("report", "done")], True, "review_ready"),
        # a failed job-level stage: nothing was extracted
        ([_t("register", "done"), _t("segment", "failed", error="not segmented"), _t("report", "done")], True, "failed"),
        ([_t("register", "done"), _t("report", "done")], False, "failed"),
        ([_t("register", "done"), _t("report", "failed", error="x")], False, "failed"),
    ],
)
def test_derive_job_status(tasks, proposal, expected):
    assert derive_job_status(tasks, proposal)[0] == expected


def test_derive_job_status_names_the_failing_stage():
    status, error = derive_job_status(
        [_t("register", "done"), _t("segment", "failed", error="not segmented: no sections"), _t("report", "done")],
        True,
    )
    assert status == "failed" and error == "segment failed: not segmented: no sections"
