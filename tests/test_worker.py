"""The worker loop with a fake pipeline runner: stages that write a canned proposal."""

import json
import uuid

import pytest
from pipeline.config import PipelineConfig
from pipeline.outcome import done, failed
from pipeline.registry import CPU, JOB, Registry, Stage
from pipeline.runner import Runner
from sqlalchemy import select

from app.models.orm import IngestJob, IngestTask
from app.worker.main import Worker, WorkerSettings, load_settings
from tests.conftest import FakeObjectStore
from tests.worker_support import make_job, make_session_factory, make_user

PROPOSAL = {"papers": [{"label": "q1", "questions": []}], "unrouted": [], "warnings": []}


class Fake:
    """Canned stages; ``seen`` records the job's status as each stage runs."""

    def __init__(self, factory, fail_segment=False):
        self.factory = factory
        self.fail_segment = fail_segment
        self.seen: list[tuple[str, str]] = []
        self.on_report = None

    def _status(self, ctx):
        with self.factory() as db:
            return db.get(IngestJob, uuid.UUID(ctx.job_id)).status

    def registry(self):
        def register(ctx):
            assert ctx.source.read_bytes() == b"%PDF source"  # fetched from S3 into scratch
            self.seen.append(("register", self._status(ctx)))
            return done()

        def segment(ctx):
            self.seen.append(("segment", self._status(ctx)))
            return failed("not segmented: nothing found") if self.fail_segment else done(needs_review=True, warnings=("check q1",))

        def split(ctx):
            return done()

        def report(ctx):
            self.seen.append(("report", self._status(ctx)))
            (ctx.job_dir / "pages").mkdir(exist_ok=True)
            (ctx.job_dir / "pages" / "p01.webp").write_bytes(b"webp")
            (ctx.job_dir / "proposal.json").write_text(json.dumps(PROPOSAL))
            if self.on_report:
                self.on_report()
            return done()

        return Registry(
            [
                Stage("register", JOB, CPU, register),
                Stage("segment", JOB, CPU, segment, needs=("register",)),
                Stage("split", JOB, CPU, split, needs=("segment",), fan_out=True),
                Stage("report", JOB, CPU, report, soft_needs=("register", "segment", "split"), after_sections=True),
            ]
        )

    def runner_factory(self):
        def factory(store, job_dir, config, wrap):
            return Runner(store, wrap(self.registry()), job_dir, config, sleep=lambda s: None)

        return factory


@pytest.fixture
def setup(tmp_path):
    engine, factory = make_session_factory(tmp_path / "w.db")
    user = make_user(factory)
    objects = FakeObjectStore()
    metadata_calls = []

    def extract(filename, db):
        metadata_calls.append(filename)
        return {"year": 2024}

    job = make_job(factory, user)  # as the API makes it: just the `register` task
    objects.put(f"tmp/ingest/{job}/source.pdf", b"%PDF source")
    fake = Fake(factory)

    def worker(fake=fake):
        settings = WorkerSettings(scratch_dir=tmp_path / "scratch", poll_seconds=0.01)
        return Worker(factory, objects, extract, fake.runner_factory(), settings)

    yield factory, job, objects, metadata_calls, fake, worker, tmp_path
    engine.dispose()


def drain(worker, limit=20):
    for _ in range(limit):
        if not worker.run_once():
            return
    raise AssertionError("the worker never ran out of tasks")


def job_row(factory, job):
    with factory() as db:
        row = db.get(IngestJob, job)
        db.refresh(row)
        return row


def test_job_goes_queued_running_review_ready_with_the_proposal(setup):
    factory, job, objects, metadata_calls, fake, make_worker, _ = setup
    assert job_row(factory, job).status == "queued"
    worker = make_worker()
    worker.start()
    drain(worker)

    row = job_row(factory, job)
    assert row.status == "review_ready" and row.error is None
    assert row.proposal == PROPOSAL
    assert [s for _, s in fake.seen] == ["running", "running", "running"]
    # the run summary is merged with the filename metadata, not written over it
    assert row.report["filename_metadata"] == {"year": 2024}
    assert metadata_calls == ["RI_2024_Math_P1.pdf"]
    assert set(row.report["timing_ms"]) == {"register", "segment", "split"}
    assert row.report["warnings"] == ["check q1"] and row.report["needs_review"] is True
    # the review images are in S3 next to the source
    assert objects.objects[f"tmp/ingest/{job}/pages/p01.webp"] == b"webp"
    with factory() as db:
        assert {t.status for t in db.scalars(select(IngestTask))} == {"done"}


def test_a_failed_job_level_stage_fails_the_job_with_the_reason(setup):
    factory, job, _, _, fake, make_worker, _ = setup
    fake.fail_segment = True
    worker = make_worker()
    worker.start()
    drain(worker)
    row = job_row(factory, job)
    assert row.status == "failed"
    assert row.error == "segment failed: not segmented: nothing found"


def test_scratch_is_rebuilt_from_s3_after_a_restart(setup):
    factory, job, objects, _, fake, make_worker, tmp_path = setup
    worker = make_worker()
    worker.start()
    worker.run_once()  # register only
    assert fake.seen == [("register", "running")]

    # a restart that lost the scratch folder: a new worker, the source back from S3
    import shutil

    shutil.rmtree(tmp_path / "scratch")
    restarted = make_worker()
    restarted.start()
    drain(restarted)
    assert job_row(factory, job).status == "review_ready"
    assert (tmp_path / "scratch" / str(job) / "source.pdf").read_bytes() == b"%PDF source"


def test_killed_mid_task_resumes_with_only_unfinished_tasks(setup):
    factory, job, _, _, fake, make_worker, tmp_path = setup
    worker = make_worker()
    worker.start()
    worker.run_once()  # register done
    claimed = worker.store.claim_ready(600)  # segment is claimed, then the process "dies"
    assert claimed.stage == "segment"
    from datetime import UTC, datetime, timedelta

    with factory() as db:  # its lease runs out
        db.execute(
            IngestTask.__table__.update()
            .where(IngestTask.id == claimed.id)
            .values(lease_until=datetime.now(UTC) - timedelta(seconds=5))
        )
        db.commit()

    fake.seen.clear()
    restarted = make_worker()
    restarted.start()
    drain(restarted)
    assert [s for s, _ in fake.seen] == ["segment", "report"]  # register was not run again
    assert job_row(factory, job).status == "review_ready"


def test_sigterm_finishes_the_current_task_then_exits(setup):
    factory, job, _, _, fake, make_worker, _ = setup
    worker = make_worker()
    fake.on_report = worker.request_stop  # the signal arrives while `report` runs
    worker.run_forever()  # returns instead of polling forever
    assert worker.stopping
    assert job_row(factory, job).status == "review_ready"  # the task in hand was finished


def test_a_cancelled_job_is_not_run(setup):
    factory, job, _, _, fake, make_worker, _ = setup
    with factory() as db:
        db.get(IngestJob, job).status = "cancelled"
        db.commit()
    worker = make_worker()
    worker.start()
    assert not worker.run_once()
    assert fake.seen == []


def test_settings_come_from_the_environment():
    defaults = load_settings({})
    assert str(defaults.scratch_dir) == "/tmp/ingest"
    assert defaults.pipeline.ingest.model == "claude-haiku-4-5"
    assert defaults.pipeline.lease_seconds == 600
    env = {
        "INGEST_SCRATCH_DIR": "/data/scratch",
        "INGEST_OCR_COMMAND": "tesseract",
        "INGEST_SEGMENT_MODEL": "m1",
        "INGEST_RETRY_MODEL": "m2",
    }
    s = load_settings(env)
    assert str(s.scratch_dir) == "/data/scratch"
    assert s.pipeline.extract.ocr_command == ("tesseract",)
    assert (s.pipeline.ingest.model, s.pipeline.ingest.retry_model) == ("m1", "m2")


def test_segment_usage_is_logged_with_prices(caplog):
    from ingester import request as segment_request

    from app.logger import _PRICES, log, log_tokens

    assert "claude-haiku-4-5" in _PRICES
    seen = []
    segment_request.usage_listener = lambda model, usage: seen.append((model, usage))
    try:
        usage = type("U", (), {"input_tokens": 10, "output_tokens": 5})()
        segment_request._report_usage("claude-haiku-4-5", type("R", (), {"usage": usage})())
        assert seen == [("claude-haiku-4-5", usage)]
        segment_request.usage_listener = lambda model, usage: 1 / 0  # a bad listener cannot fail a request
        segment_request._report_usage("claude-haiku-4-5", type("R", (), {"usage": usage})())
    finally:
        segment_request.usage_listener = None
    log_tokens("ingest_segment", "claude-haiku-4-5", usage)  # does not raise
