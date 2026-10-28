"""The worker loop with a fake pipeline runner: stages that write a canned proposal."""

import json
import uuid

import fitz
import pytest
from pipeline.config import PipelineConfig
from pipeline.outcome import done, failed
from pipeline.registry import CPU, JOB, Registry, Stage
from pipeline.runner import Runner
from sqlalchemy import select

from app.models.orm import IngestJob, IngestPaper, IngestTask
from app.worker.main import Worker, WorkerSettings, load_settings
from tests.conftest import FakeObjectStore
from tests.worker_support import PDF_BYTES, LOCKED_PDF_BYTES, make_job, make_session_factory, make_user

def _segment(label, first, last, cover=()):
    kind = "question" if label[0] == "q" else "answer"
    return {
        "label": label, "kind": kind, "index": int(label[1:]), "first_page": first, "last_page": last,
        "cover_pages": list(cover),
    }


# q1 (cover = page 1) with its answer, and an answer-only a2
PLAN = {"pdf": "source.pdf", "paper": "x", "page_count": 2, "segments": [_segment("q1", 2, 2, cover=[1]), _segment("a1", 2, 2), _segment("a2", 1, 1)]}

PROPOSAL = {"papers": [{"label": "q1", "questions": []}], "unrouted": [], "warnings": []}


class Fake:
    """Canned stages; ``seen`` records the job's status as each stage runs."""

    def __init__(self, factory, fail_segment=False):
        self.factory = factory
        self.fail_segment = fail_segment
        self.raise_in_segment = False
        self.seen: list[tuple[str, str]] = []
        self.on_report = None
        self.report_reads_segments = False  # as the real report does: it cannot run without them
        self.plan = PLAN
        self.proposal = PROPOSAL

    def _status(self, ctx):
        with self.factory() as db:
            return db.get(IngestJob, uuid.UUID(ctx.job_id)).status

    def registry(self):
        def register(ctx):
            assert ctx.source.read_bytes() == PDF_BYTES  # fetched from S3 into scratch
            self.seen.append(("register", self._status(ctx)))
            # what the real register stage records in job.json
            (ctx.job_dir / "job.json").write_text(json.dumps({"page_count": 2, "sha256": "ab" * 32}))
            return done()

        def segment(ctx):
            self.seen.append(("segment", self._status(ctx)))
            if self.raise_in_segment:
                raise RuntimeError("kaboom")
            (ctx.job_dir / "segments.json").write_text(json.dumps(self.plan))
            return failed("not segmented: nothing found") if self.fail_segment else done(needs_review=True, warnings=("check q1",))

        def split(ctx):
            return done()

        def report(ctx):
            self.seen.append(("report", self._status(ctx)))
            if self.report_reads_segments and not (ctx.job_dir / "segments.json").is_file():
                return failed("segments.json is missing")
            (ctx.job_dir / "pages").mkdir(exist_ok=True)
            (ctx.job_dir / "pages" / "p01.webp").write_bytes(b"webp")
            (ctx.job_dir / "proposal.json").write_text(json.dumps(self.proposal))
            (ctx.job_dir / "segments.json").write_text(json.dumps({"sections": ["q1"]}))
            (ctx.job_dir / "ingest.json").write_text(json.dumps({"papers": 1}))
            if self.on_report:
                self.on_report()
            return done()

        return Registry(
            [
                Stage("register", JOB, CPU, register),
                Stage("segment", JOB, CPU, segment, needs=("register",), outputs=lambda ctx: [ctx.job_dir / "segments.json"]),
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

    def extract(filename, db, cover=None):
        pages = None
        if cover is not None:
            with fitz.open(stream=cover, filetype="pdf") as doc:
                pages = doc.page_count
        metadata_calls.append((filename, pages))
        return {"year": 2024}

    job = make_job(factory, user)  # as the API makes it: just the `register` task
    objects.put(f"tmp/ingest/{job}/source.pdf", PDF_BYTES)
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
    # the run summary is merged with the per-paper metadata, not written over it; register no
    # longer reads the filename on its own: each paper's call carries it as a hint
    assert "filename_metadata" not in row.report
    assert row.report["paper_metadata"] == {"q1": {"year": 2024}, "a2": {"year": 2024}}
    # q1 sends its cover page (1 page), the answer-only a2 its first page (1 page)
    assert metadata_calls == [("RI_2024_Math_P1.pdf", 1), ("RI_2024_Math_P1.pdf", 1)]
    assert set(row.report["timing_ms"]) == {"register", "segment", "split"}
    assert row.report["warnings"] == ["check q1"] and row.report["needs_review"] is True
    # the review images are in S3 next to the source
    assert objects.objects[f"tmp/ingest/{job}/pages/p01.webp"] == b"webp"
    with factory() as db:
        assert {t.status for t in db.scalars(select(IngestTask))} == {"done"}
        # one queryable ingest_paper row per proposed paper, with its role and cover metadata
        (paper,) = db.scalars(select(IngestPaper)).all()
        assert (paper.job_id, paper.paper_key, paper.role, paper.status) == (job, "q1", "question", "pending")
        assert (paper.year, paper.metadata_source, paper.school_id) == (2024, "cover", None)


def test_a_failing_metadata_call_never_fails_the_segment_task(setup):
    factory, job, objects, _, fake, _, tmp_path = setup
    calls = []

    def flaky(filename, db, cover=None):
        calls.append(cover is not None)
        raise RuntimeError("claude down")

    settings = WorkerSettings(scratch_dir=tmp_path / "scratch", poll_seconds=0.01)
    worker = Worker(factory, objects, flaky, fake.runner_factory(), settings)
    worker.start()
    drain(worker)
    row = job_row(factory, job)
    assert row.status == "review_ready"
    assert row.report["paper_metadata"] == {"q1": {}, "a2": {}}
    assert calls == [True, False, True, False]  # the cover, then the filename alone, per paper


def test_paper_metadata_keys_match_the_proposal_papers(tmp_path):
    from ingester.segments import Segment, pair_segments, paper_key
    from app.services.ingest_confirm import paper_key as proposal_key

    segs = [
        Segment("q1", "question", 1, 1, 2), Segment("a1", "answer", 1, 3, 3),
        Segment("a2", "answer", 2, 4, 4), Segment("q3", "question", 3, 5, 6),
    ]
    keys = [paper_key(q, a) for q, a in pair_segments(segs)]
    assert keys == ["q1", "q3", "a2"]
    papers = [{"label": q and q.label, "answer_label": a and a.label} for q, a in pair_segments(segs)]
    assert keys == [proposal_key(p, i) for i, p in enumerate(papers)]


def test_report_keeps_a_debug_bundle_and_releases_scratch(setup):
    factory, job, _, _, _, make_worker, tmp_path = setup
    worker = make_worker()
    worker.start()
    drain(worker)
    row = job_row(factory, job)
    assert row.debug == {"segments": {"sections": ["q1"]}, "ingest": {"papers": 1}}
    assert not (tmp_path / "scratch" / str(job)).exists()  # scratch is a cache
    # a restart does not reopen the review_ready job's tasks for want of the artefacts
    restarted = make_worker()
    restarted.start()
    assert not restarted.run_once()
    with factory() as db:
        assert {t.status for t in db.scalars(select(IngestTask))} == {"done"}
    assert job_row(factory, job).status == "review_ready"


def test_scratch_is_kept_for_a_failed_job(setup):
    factory, job, _, _, fake, make_worker, tmp_path = setup
    fake.fail_segment = True
    worker = make_worker()
    worker.start()
    drain(worker)
    assert job_row(factory, job).status == "failed"
    assert (tmp_path / "scratch" / str(job)).is_dir()  # Retry re-runs only the failed tasks


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
    assert not (tmp_path / "scratch" / str(job)).exists()  # released once the report was done


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


@pytest.mark.parametrize("regenerated, edit_kept", [(PROPOSAL, True), ({**PROPOSAL, "warnings": ["new"]}, False)])
def test_retry_drops_saved_edits_only_when_the_proposal_changes(setup, regenerated, edit_kept):
    from app.services.ingest_jobs import retry_job

    factory, job, _, _, fake, make_worker, _ = setup
    worker = make_worker()
    worker.start()
    drain(worker)
    edited = {**PROPOSAL, "papers": [{"label": "q1", "questions": [{"number": 1}]}]}
    with factory() as db:
        db.get(IngestJob, job).proposal_edited = edited
        report = db.scalars(select(IngestTask).where(IngestTask.job_id == job, IngestTask.stage == "report")).one()
        report.status, report.fingerprint = "failed", None  # None: its inputs changed, so it re-runs
        db.commit()

    fake.proposal = regenerated
    with factory() as db:
        assert retry_job(db.get(IngestJob, job), db) == 1
    drain(worker)
    row = job_row(factory, job)
    assert row.status == "review_ready" and row.proposal == regenerated
    assert row.proposal_edited == (edited if edit_kept else None)


@pytest.mark.parametrize("scratch", ["released", "lost_in_a_restart"])
def test_retry_rebuilds_a_scratch_folder_that_is_gone(setup, scratch):
    """A retried task runs after the tasks whose artefacts went with the job's scratch folder:
    released once `report` was done, or lost with the worker's container."""
    from app.services.ingest_jobs import retry_job

    factory, job, _, _, fake, make_worker, tmp_path = setup
    fake.report_reads_segments = True
    worker = make_worker()
    worker.start()
    drain(worker)
    assert not (tmp_path / "scratch" / str(job)).exists()  # released with the proposal stored
    with factory() as db:
        report = db.scalars(select(IngestTask).where(IngestTask.job_id == job, IngestTask.stage == "report")).one()
        report.status, report.fingerprint = "failed", None
        db.commit()
    if scratch == "lost_in_a_restart":
        worker = make_worker()
        worker.start()

    with factory() as db:
        assert retry_job(db.get(IngestJob, job), db) == 1
    fake.seen.clear()
    drain(worker)
    assert [s for s, _ in fake.seen] == ["segment", "report"]  # segment rebuilt what report reads
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


def test_segment_call_is_handed_out_with_its_reply_and_logged_with_prices(caplog):
    from ingester import request as segment_request

    from app.logger import _PRICES, log_claude_call

    assert "claude-haiku-4-5" in _PRICES
    seen = []
    segment_request.usage_listener = lambda *call: seen.append(call)
    try:
        usage = type("U", (), {"input_tokens": 10, "output_tokens": 5})()
        thinking = type("B", (), {"type": "thinking", "thinking": "hmm"})()
        text = type("B", (), {"type": "text", "text": '{"segments": []}'})()
        response = type("R", (), {"usage": usage, "_request_id": "req_1", "content": [thinking, text]})()
        segment_request._report_usage("claude-haiku-4-5", response, 2.5)
        assert seen == [("claude-haiku-4-5", usage, "req_1", '{"segments": []}', 2.5)]
        segment_request.usage_listener = lambda *call: 1 / 0  # a bad listener cannot fail a request
        segment_request._report_usage("claude-haiku-4-5", type("R", (), {"usage": usage})())
    finally:
        segment_request.usage_listener = None
    with caplog.at_level("INFO", logger="pillora"):
        log_claude_call("find the papers in the booklet", "claude-haiku-4-5", usage, "req_1", reply='{"segments": []}')
    assert "$0.0000" in caplog.text and 'Reply: {"segments": []}' in caplog.text


def test_register_fills_in_page_count_and_sha256(setup):
    factory, job, _, _, _, make_worker, _ = setup
    assert job_row(factory, job).page_count == 1  # make_job's placeholder
    worker = make_worker()
    worker.start()
    drain(worker)
    row = job_row(factory, job)
    assert row.page_count == 2 and row.sha256 == "ab" * 32


@pytest.mark.parametrize(
    "data, reason",
    [
        (b"definitely not a pdf", "The file is not a readable PDF"),
        (LOCKED_PDF_BYTES, "The PDF is password protected"),
    ],
)
def test_a_bad_pdf_fails_the_job_with_a_reason_and_is_not_retried(setup, data, reason):
    factory, job, objects, _, fake, make_worker, _ = setup
    objects.put(f"tmp/ingest/{job}/source.pdf", data)
    worker = make_worker()
    worker.start()
    drain(worker)
    row = job_row(factory, job)
    assert row.status == "failed"
    assert row.error == f"register failed: {reason}"
    assert fake.seen == []  # the register stage itself never ran
    with factory() as db:
        [task] = db.scalars(select(IngestTask)).all()
        assert task.status == "failed" and task.attempts == 1
