"""The daily reconciler: every check, in dry-run and delete mode, against FakeObjectStore."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text

from app.models.orm import IngestEvent, IngestJob, IngestTask, QuestionPage
from app.worker.main import WorkerSettings, load_settings
from app.worker.reconcile import Reconciler
from app.worker.store import SqlStore
from app.worker.sweep import run_sweep
from tests.conftest import FakeObjectStore
from tests.worker_support import make_job, make_session_factory, make_user

NOW = datetime(2026, 6, 1, 12, tzinfo=UTC)
DAY = timedelta(days=1)


@pytest.fixture
def env(tmp_path):
    engine, factory = make_session_factory(tmp_path / "w.db")
    user = make_user(factory)
    SqlStore(factory, tmp_path / "scratch").touch_worker()
    scratch = tmp_path / "scratch"
    scratch.mkdir(exist_ok=True)
    yield engine, factory, user, scratch, FakeObjectStore()
    engine.dispose()


def reconcile(env, delete):
    _engine, factory, _user, scratch, objects = env
    return Reconciler(factory, objects, scratch, NOW, delete=delete).run()


def put(objects, key, age):
    objects.put(key, b"x")
    objects.modified[key] = NOW - age


def job(env, status, age, **kw):
    _engine, factory, user, *_ = env
    job_id = make_job(factory, user, status=status, **kw)
    with factory() as db:
        db.get(IngestJob, job_id).updated_at = NOW - age
        db.commit()
    return job_id


def events(env):
    with env[1]() as db:
        return db.scalars(select(IngestEvent).where(IngestEvent.kind == "reconcile").order_by(IngestEvent.id)).all()


def by_kind(findings, kind):
    return [f for f in findings if f.kind == kind]


# --- orphan job prefix ---------------------------------------------------------------
@pytest.mark.parametrize("delete", [False, True])
@pytest.mark.parametrize("root", ["ingest", "tmp/ingest"])
def test_orphan_prefix_of_settled_and_missing_jobs(env, delete, root):
    objects = env[4]
    old = job(env, "cancelled", 2 * DAY)
    fresh = job(env, "confirmed", timedelta(hours=2))
    pending = job(env, "review_ready", 30 * DAY)
    gone, gone_recent = uuid.uuid4(), uuid.uuid4()
    for j, age in [(old, 2 * DAY), (fresh, 2 * DAY), (pending, 30 * DAY), (gone, 3 * DAY), (gone_recent, timedelta(hours=1))]:
        put(objects, f"{root}/{j}/source.pdf", age)
        put(objects, f"{root}/{j}/pages/p01.webp", age)

    findings = by_kind(reconcile(env, delete), "orphan_job_prefix")

    assert {f.key_or_path for f in findings} == {f"{root}/{old}/", f"{root}/{gone}/"}
    assert {f.job_id for f in findings} == {old, None}
    for j in (fresh, pending, gone_recent):
        assert any(k.startswith(f"{root}/{j}/") for k in objects.objects)
    for j in (old, gone):
        assert any(k.startswith(f"{root}/{j}/") for k in objects.objects) is (not delete)
    assert {f.action for f in findings} == {"deleted" if delete else "would_delete"}


# --- stale temp ------------------------------------------------------------------------
@pytest.mark.parametrize("delete", [False, True])
def test_stale_temp_objects(env, delete):
    objects = env[4]
    put(objects, "tmp/up1/p0.webp", timedelta(hours=30))
    put(objects, "tmp/up2/p0.webp", timedelta(hours=3))
    pending = job(env, "review_ready", 30 * DAY)  # a pending legacy job's objects are not "stale temp"
    put(objects, f"tmp/ingest/{pending}/source.pdf", 30 * DAY)

    findings = by_kind(reconcile(env, delete), "stale_temp")

    assert [f.key_or_path for f in findings] == ["tmp/up1/p0.webp"]
    assert ("tmp/up1/p0.webp" in objects.objects) is (not delete)
    assert "tmp/up2/p0.webp" in objects.objects
    assert f"tmp/ingest/{pending}/source.pdf" in objects.objects


# --- orphan scratch ----------------------------------------------------------------------
@pytest.mark.parametrize("delete", [False, True])
def test_orphan_scratch(env, delete):
    scratch = env[3]
    review_old = job(env, "review_ready", 2 * DAY)
    review_new = job(env, "review_ready", timedelta(hours=1))
    failed = job(env, "failed", 30 * DAY)
    running = job(env, "running", 30 * DAY)
    missing = uuid.uuid4()
    import os
    for j in (review_old, review_new, failed, running, missing):
        (scratch / str(j)).mkdir()
        (scratch / str(j) / "f").write_text("x")
    old_ts = (NOW - 3 * DAY).timestamp()
    os.utime(scratch / str(missing), (old_ts, old_ts))
    (scratch / "notes").mkdir()  # not a job folder

    findings = by_kind(reconcile(env, delete), "orphan_scratch")

    assert {f.job_id for f in findings} == {review_old, None}
    for j in (review_new, failed, running):
        assert (scratch / str(j)).exists()
    assert (scratch / "notes").exists()
    for j in (review_old, missing):
        assert (scratch / str(j)).exists() is (not delete)


# --- orphan paper images ---------------------------------------------------------------------
@pytest.mark.parametrize("delete", [False, True])
def test_orphan_paper_images(env, delete):
    engine, _f, _u, _s, objects = env
    put(objects, "papers/1/q1/kept.webp", 30 * DAY)
    put(objects, "papers/1/q1/orphan.webp", 30 * DAY)
    put(objects, "papers/1/q1/recent.webp", 2 * DAY)
    with engine.begin() as conn:  # a page row without its question: foreign keys off on this connection
        conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        conn.execute(
            QuestionPage.__table__.insert().values(
                question_id=1, page_order=0, image_key="papers/1/q1/kept.webp", page_type="question",
                width_px=1, height_px=1,
            )
        )

    findings = by_kind(reconcile(env, delete), "orphan_paper_image")

    assert [f.key_or_path for f in findings] == ["papers/1/q1/orphan.webp"]
    assert ("papers/1/q1/orphan.webp" in objects.objects) is (not delete)
    assert "papers/1/q1/kept.webp" in objects.objects and "papers/1/q1/recent.webp" in objects.objects


# --- stuck jobs ------------------------------------------------------------------------------------
def _set_task(env, job_id, **values):
    with env[1]() as db:
        for t in db.scalars(select(IngestTask).where(IngestTask.job_id == job_id)):
            for k, v in values.items():
                setattr(t, k, v)
        db.commit()


def test_stuck_job_dry_run_only_reports_and_delete_marks_failed(env):
    stuck = job(env, "running", 7 * 3600 * timedelta(seconds=1))
    _set_task(env, stuck, status="running", lease_until=NOW - timedelta(hours=7), started_at=NOW - timedelta(hours=8))
    leased = job(env, "running", timedelta(hours=7))
    _set_task(env, leased, status="running", lease_until=NOW + timedelta(minutes=5))
    recent = job(env, "queued", timedelta(hours=1))
    with env[1]() as db:
        dry = Reconciler(env[1], env[4], env[3], NOW, delete=False).run()
        assert [f.job_id for f in dry if f.kind == "stuck_job"] == [stuck]
        assert db.get(IngestJob, stuck).status == "running"
        assert db.scalar(select(IngestTask.status).where(IngestTask.job_id == stuck)) == "running"
    assert [f.action for f in dry if f.kind == "stuck_job"] == ["would_mark_failed"]

    wet = Reconciler(env[1], env[4], env[3], NOW, delete=True).run()
    assert [(f.job_id, f.action) for f in wet if f.kind == "stuck_job"] == [(stuck, "marked_failed")]
    with env[1]() as db:
        row = db.get(IngestJob, stuck)
        assert row.status == "failed" and "stuck" in row.error
        task = db.scalars(select(IngestTask).where(IngestTask.job_id == stuck)).one()
        assert (task.status, task.reason) == ("failed", "stuck")
        assert db.get(IngestJob, leased).status == "running"
        assert db.get(IngestJob, recent).status == "queued"


def test_stuck_job_is_retryable(env):
    from pipeline.registry import default_registry
    from pipeline.runner import Runner

    stuck = job(env, "running", timedelta(hours=9))
    _set_task(env, stuck, status="running", lease_until=NOW - timedelta(hours=8))
    Reconciler(env[1], env[4], env[3], NOW, delete=True).run()
    store = SqlStore(env[1], env[3])
    reopened = Runner(store, default_registry(), lambda _j: env[3]).retry(str(stuck))
    assert [t.stage for t in reopened] == ["register"]


# --- abandoned uploads ------------------------------------------------------------------------------
def test_abandoned_upload_dry_run_reports_and_delete_cancels_and_removes_the_object(env):
    objects = env[4]
    old = job(env, "awaiting_upload", timedelta(hours=2), stages=(), created_at=NOW - timedelta(hours=2))
    fresh = job(env, "awaiting_upload", timedelta(minutes=10), stages=(), created_at=NOW - timedelta(minutes=10))
    queued = job(env, "queued", timedelta(hours=2), created_at=NOW - timedelta(hours=2))
    for j in (old, fresh):
        put(objects, f"tmp/ingest/{j}/source.pdf", timedelta(minutes=5))
    with env[1]() as db:
        for j in (old, fresh):
            db.get(IngestJob, j).source_key = f"ingest/{j}/source.pdf"
        db.commit()
    for j in (old, fresh):
        objects.objects[f"ingest/{j}/source.pdf"] = objects.objects.pop(f"tmp/ingest/{j}/source.pdf")

    dry = by_kind(Reconciler(env[1], objects, env[3], NOW, delete=False).run(), "abandoned_upload")
    assert [(f.job_id, f.action) for f in dry] == [(old, "would_cancel")]
    with env[1]() as db:
        assert db.get(IngestJob, old).status == "awaiting_upload"
    assert f"ingest/{old}/source.pdf" in objects.objects

    wet = by_kind(Reconciler(env[1], objects, env[3], NOW, delete=True).run(), "abandoned_upload")
    assert [(f.job_id, f.action) for f in wet] == [(old, "cancelled")]
    with env[1]() as db:
        assert db.get(IngestJob, old).status == "cancelled"
        assert db.get(IngestJob, fresh).status == "awaiting_upload"
        assert db.get(IngestJob, queued).status == "queued"
    assert f"ingest/{old}/source.pdf" not in objects.objects
    assert f"ingest/{fresh}/source.pdf" in objects.objects
    kinds = {e.data["check"]: e.data["action"] for e in events(env)}
    assert kinds["abandoned_upload"] in ("would_cancel", "cancelled")


# --- missing source ------------------------------------------------------------------------------------
@pytest.mark.parametrize("delete", [False, True])
def test_missing_source_is_report_only(env, delete):
    objects = env[4]
    missing = job(env, "review_ready", DAY)
    present = job(env, "review_ready", DAY)
    settled = job(env, "confirmed", DAY)
    put(objects, f"tmp/ingest/{present}/source.pdf", DAY)

    findings = by_kind(reconcile(env, delete), "missing_source")

    assert [(f.job_id, f.action) for f in findings] == [(missing, "report_only")]
    with env[1]() as db:  # the row is never touched
        assert db.get(IngestJob, missing).status == "review_ready"


# --- findings: events + logs ------------------------------------------------------------------------------
def test_dry_run_deletes_nothing_and_records_events_and_logs(env, caplog):
    objects = env[4]
    old = job(env, "cancelled", 2 * DAY)
    put(objects, f"tmp/ingest/{old}/source.pdf", 2 * DAY)
    put(objects, "tmp/up/p.webp", 2 * DAY)
    put(objects, "papers/9/orphan.webp", 30 * DAY)
    before = dict(objects.objects)

    with caplog.at_level("WARNING"):
        findings = reconcile(env, False)

    assert objects.objects == before and not objects.deleted_prefixes and not objects.deleted_keys
    rows = events(env)
    assert len(rows) == len(findings) >= 3
    assert {r.data["check"] for r in rows} >= {"orphan_job_prefix", "stale_temp", "orphan_paper_image"}
    assert all(r.data["dry_run"] is True and r.data["action"].startswith("would_") for r in rows)
    assert {r.job_id for r in rows} == {old, None}  # job-less findings carry no job id
    assert any("reconcile" in r.getMessage() or "reconcile" in str(getattr(r, "fields", "")) for r in caplog.records)


def test_delete_mode_records_deleted_events(env):
    objects = env[4]
    put(objects, "tmp/up/p.webp", 2 * DAY)
    reconcile(env, True)
    assert "tmp/up/p.webp" not in objects.objects
    (row,) = events(env)
    assert row.job_id is None and row.data["action"] == "deleted" and row.data["dry_run"] is False


def test_clean_store_has_no_findings(env):
    assert reconcile(env, True) == []
    assert events(env) == []


# --- wiring ---------------------------------------------------------------------------------------------------
def test_sweep_runs_the_reconciler_gated_by_the_flag(env):
    _e, factory, _u, scratch, objects = env
    put(objects, "tmp/up/p.webp", 2 * DAY)
    assert run_sweep(factory, objects, scratch, lambda: NOW) == []
    assert "tmp/up/p.webp" in objects.objects and len(events(env)) == 1
    assert run_sweep(factory, objects, scratch, lambda: NOW + 2 * DAY, True) == []
    assert "tmp/up/p.webp" not in objects.objects


def test_settings_read_the_delete_flag():
    assert load_settings({}).reconcile_delete is False
    assert load_settings({"INGEST_RECONCILE_DELETE": "true"}).reconcile_delete is True
    assert load_settings({"INGEST_RECONCILE_DELETE": "false"}).reconcile_delete is False
    assert WorkerSettings().reconcile_delete is False
