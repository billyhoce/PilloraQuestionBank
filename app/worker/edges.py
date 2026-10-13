"""The worker's S3 and database edges, composed around the pipeline's stages.

``ingestion/`` knows nothing of S3 or the app, so the edges are added here by wrapping
stages of the registry (:func:`wrap_registry`) and by resolving each job's scratch folder
(:meth:`Edges.job_dir`):

* **scratch** -- ``<scratch>/<job_id>/`` is the job's folder. Resolving it fetches ``source.pdf``
  from S3 when it is not there: the first ``register`` finds its input, and after a restart
  that lost the folder the booklet is back before any stage (or the fingerprint check) reads it.
  Artefacts that were lost with the folder are not fetched: ``Runner.revalidate`` finds their
  outputs missing and the tasks run again (slower, never wrong);
* ``register`` -- before the stage, the PDF check (:func:`check_pdf`): a corrupt, password-protected
  or empty booklet fails the task with a readable reason (a failed task is not retried on its own,
  so it ends as a ``failed`` job whose ``error`` says why). After the stage, the job's ``page_count``
  and ``sha256`` (read from ``job.json``, which ``register`` wrote);
* ``segment`` -- after the stage, each paper's metadata is read from its own cover (one Claude call
  per segment pair, :func:`ingester.segments.pair_segments`; it needs the app's reference data) and
  stored in ``ingest_job.report["paper_metadata"][paper_key]``, the key the proposal uses for that
  paper. A failed call falls back to the filename alone, then to empty metadata: it never fails the task;
* ``report`` -- after the stage, the review images ``pages/pNN.webp`` are uploaded to
  ``tmp/ingest/{job_id}/pages/`` and the proposal and the run summary are stored on the job row.
  The images are uploaded here rather than at ``render`` because the job-level ``pages/`` folder
  (booklet page numbering, what the proposal's ``image`` paths name) is assembled by ``report``;
  ``render`` only writes each section's own ``review/`` folder. The job's ``segments.json`` and
  ``ingest.json`` are copied to ``ingest_job.debug``, and once the runner has recorded the task done
  the scratch folder is deleted (:meth:`Edges.release_scratch`, called by the worker loop).

A hook runs inside its stage's task (before ``complete``), so the task's lease covers it, a failure
fails the task, and a crash reruns it.
"""

from __future__ import annotations

import logging
import shutil
import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import fitz  # PyMuPDF
from ingester.segments import SEGMENTS_NAME, paper_key, pair_segments, read_plan
from pipeline import artefacts
from pipeline.outcome import DONE, FAILED, Outcome, StageContext, failed
from pipeline.registry import Registry, Stage
from pipeline.store import TaskSpec
from sqlalchemy.orm import Session

from app.logger import log_job_event
from app.models.orm import IngestJob
from app.services.ingest_jobs import (
    extract_paper_metadata_safely,
    job_prefix,
    record_paper_metadata,
    source_key_for,
)
from app.services.ingest_papers import sync_job_papers
from app.services.ingest_review import extract_pages
from app.storage.object_store import ObjectStore
from app.worker.store import API_OWNED, SOURCE_NAME, SqlStore

log = logging.getLogger(__name__)

FAILED_JOB_STATUSES = ("failed",)

PAGES_DIR = "pages"
FIXTURE_SUFFIX = ".segments.json"


def check_pdf(path: Path) -> str | None:
    """Why ``path`` is not a usable PDF (a readable reason), or ``None`` when it is."""
    try:
        with fitz.open(path) as doc:
            if doc.needs_pass:
                return "The PDF is password protected"
            if doc.page_count < 1:
                return "The PDF has no pages"
    except Exception:
        return "The file is not a readable PDF"
    return None


class Edges:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        object_store: ObjectStore,
        store: SqlStore,
        scratch_root: Path | str,
        extract_metadata: Callable,
        fixtures_dir: Path | str | None = None,
    ) -> None:
        self._factory = session_factory
        self._objects = object_store
        self._store = store
        self._scratch = Path(scratch_root)
        self._extract_metadata = extract_metadata
        # Dev only (INGEST_FIXTURES_DIR): a folder of ``<paper>.segments.json`` plans, used in
        # place of the Messages API where there is no key. Never set in production.
        self._fixtures = Path(fixtures_dir) if fixtures_dir else None
        self._job_stages: list[str] = []

    # --- scratch ------------------------------------------------------------
    def job_dir(self, job_id: str) -> Path:
        """The job's scratch folder, with ``source.pdf`` fetched from S3 when missing."""
        folder = self._scratch / str(job_id)
        folder.mkdir(parents=True, exist_ok=True)
        source = folder / SOURCE_NAME
        if not source.is_file():
            log.info("job %s: fetching the source PDF into %s", job_id, folder)
            artefacts.write_bytes(source, self._objects.get(self._source_key(job_id)))
        if self._fixtures is not None:
            self._place_fixture(job_id, folder)
        return folder

    def _source_key(self, job_id: str) -> str:
        """The job's stored source key (legacy jobs sit under ``tmp/ingest/``)."""
        with self._factory() as db:
            job = db.get(IngestJob, uuid.UUID(str(job_id)))
            return job.source_key if job is not None else source_key_for(uuid.UUID(str(job_id)))

    def _place_fixture(self, job_id: str, folder: Path) -> None:
        target = folder / (Path(SOURCE_NAME).stem + FIXTURE_SUFFIX)
        if target.is_file():
            return
        with self._factory() as db:
            job = db.get(IngestJob, uuid.UUID(str(job_id)))
            filename = job.filename if job else None
        if filename is None:
            return
        fixture = self._fixtures / (Path(filename).stem + FIXTURE_SUFFIX)
        if fixture.is_file():
            artefacts.write_bytes(target, fixture.read_bytes())

    # --- the stages' hooks --------------------------------------------------
    def before_register(self, ctx: StageContext) -> Outcome | None:
        reason = check_pdf(ctx.source)
        if reason is None:
            return None
        log.warning("job %s: rejected source PDF: %s", ctx.job_id, reason)
        return failed(reason, needs_review=False)

    def after_register(self, ctx: StageContext, outcome: Outcome) -> Outcome:
        # POST /api/import/jobs creates only the ``register`` task (the API does not know the
        # pipeline); the rest of the job-scope chain is created here, as ``Runner.submit`` does
        # locally. Idempotent, and inside register's own task: a crash reruns both.
        self._store.add_tasks([TaskSpec(ctx.job_id, name) for name in self._job_stages])
        with self._factory() as db:
            job = db.get(IngestJob, uuid.UUID(ctx.job_id))
            if job is not None:
                self._record_identity(ctx, db, job)
                db.commit()
        return outcome

    def _record_identity(self, ctx: StageContext, db: Session, job: IngestJob) -> None:
        """Fill the job's ``page_count`` and ``sha256`` from the ``job.json`` ``register`` wrote."""
        path = ctx.path(artefacts.JOB_NAME)
        if not path.is_file():
            return
        info = artefacts.read_json(path)
        job.page_count = info.get("page_count")
        job.sha256 = info.get("sha256")
        log_job_event(job.id, "registered", sha256=job.sha256, page_count=job.page_count)

    def after_segment(self, ctx: StageContext, outcome: Outcome) -> Outcome:
        """Read each paper's metadata from its own cover and store it by paper key."""
        path = ctx.path(SEGMENTS_NAME)
        if not path.is_file():
            return outcome
        try:
            plan = read_plan(path, pdf=ctx.source)
        except (OSError, ValueError, KeyError):
            log.warning("job %s: unreadable segments.json; no paper metadata", ctx.job_id)
            return outcome
        job_uuid = uuid.UUID(ctx.job_id)
        with self._factory() as db:
            job = db.get(IngestJob, job_uuid)
            if job is None or job.status in API_OWNED:
                return outcome
            source = ctx.source.read_bytes()
            papers: dict[str, dict] = {}
            for question, answer in pair_segments(plan.segments):
                key = paper_key(question, answer)
                cover = self._cover_pdf(source, question or answer, job_uuid)
                papers[key] = extract_paper_metadata_safely(self._extract_metadata, job.filename, db, cover)
                log_job_event(
                    job_uuid, "paper_metadata", paper=key, cover=cover is not None,
                    fields=sorted(k for k, v in papers[key].items() if v is not None),
                )
            if papers:
                record_paper_metadata(job, db, papers)
        return outcome

    @staticmethod
    def _cover_pdf(source: bytes, section, job_uuid: uuid.UUID) -> bytes | None:
        """The section's cover pages as a PDF, else its first page; ``None`` if they cannot be cut."""
        pages = list(section.cover_pages) or [section.first_page]
        try:
            return extract_pages(source, pages)
        except Exception:
            log.warning("job %s: could not cut the cover of %s", job_uuid, section.label)
            return None

    def after_report(self, ctx: StageContext, outcome: Outcome) -> Outcome:
        job_uuid = uuid.UUID(ctx.job_id)
        proposal_path = ctx.path(artefacts.PROPOSAL_NAME)
        if not proposal_path.is_file():
            return failed("report wrote no proposal.json")
        proposal = artefacts.read_json(proposal_path)
        with self._factory() as db:
            job = db.get(IngestJob, job_uuid, with_for_update=True)  # cost writes lock the row too
            if job is None or job.status in API_OWNED:
                return outcome  # cancelled while it ran: leave no objects behind
            pages = ctx.path(PAGES_DIR)
            prefix = job_prefix(job.source_key) + PAGES_DIR + "/"
            for image in sorted(pages.glob("*.webp")) if pages.is_dir() else ():
                self._objects.put(prefix + image.name, image.read_bytes(), "image/webp")
            job.proposal = proposal
            job.debug = self._debug_bundle(ctx)
            job.report = {
                **(job.report or {}),
                **self._summary(ctx.job_id, outcome),
            }
            sync_job_papers(db, job)  # same transaction as the proposal
            db.commit()
        log_job_event(job_uuid, "proposal_stored", papers=len(proposal.get("papers", [])))
        return outcome

    @staticmethod
    def _debug_bundle(ctx: StageContext) -> dict:
        """``segments.json`` and ``ingest.json`` as read from scratch (a few KB): once the scratch
        folder is released they are all that remains of the pipeline's own record of the run."""
        bundle: dict = {}
        for name, filename in (("segments", artefacts.SEGMENTS_NAME), ("ingest", artefacts.REPORT_NAME)):
            path = ctx.path(filename)
            if path.is_file():
                try:
                    bundle[name] = artefacts.read_json(path)
                except (OSError, ValueError):
                    log.warning("job %s: could not read %s for the debug bundle", ctx.job_id, filename)
        return bundle

    def release_scratch(self, job_id: str) -> bool:
        """Delete the job's scratch folder once its ``report`` task is durably ``done`` and the
        proposal is on the job row; returns whether it did.

        This runs after the runner has recorded the task done, not inside ``after_report``: a hook
        runs before ``complete``, so a crash after deleting there would leave ``report`` unfinished
        with its inputs gone and rerun the whole job. After ``complete`` a crash merely leaves the
        folder behind (the sweep/reconciler removes it). A ``review_ready`` job is never revalidated
        (the worker revalidates only ``queued`` / ``running`` jobs), and Review, confirm and
        manual-pages read only S3 and the database, so the missing artefacts are never looked for.
        A failed job keeps its folder, so Retry re-runs only the failed tasks."""
        job_uuid = uuid.UUID(str(job_id))
        report_done = any(
            t.section is None and t.stage == "report" and t.status == DONE
            for t in self._store.tasks(str(job_id))
        )
        if not report_done:
            return False
        with self._factory() as db:
            job = db.get(IngestJob, job_uuid)
            if job is None or job.proposal is None or job.status in FAILED_JOB_STATUSES:
                return False
        shutil.rmtree(self._scratch / str(job_id), ignore_errors=True)
        log_job_event(job_uuid, "scratch_released")
        return True

    def _summary(self, job_id: str, outcome: Outcome) -> dict:
        """Per-stage timing and the warnings of every task (the report task itself excluded:
        it has no duration yet)."""
        tasks = [t for t in self._store.tasks(job_id) if not (t.section is None and t.stage == "report")]
        timing: dict[str, int] = {}
        for task in tasks:
            timing[task.stage] = timing.get(task.stage, 0) + (task.duration_ms or 0)
        warnings = list(dict.fromkeys(w for t in tasks for w in t.warnings))
        warnings.extend(w for w in outcome.warnings if w not in warnings)
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "timing_ms": timing,
            "warnings": warnings,
            "needs_review": any(t.needs_review for t in tasks) or outcome.needs_review,
            "tasks": [
                {
                    "section": t.section,
                    "stage": t.stage,
                    "status": t.status,
                    "duration_ms": t.duration_ms,
                    "needs_review": t.needs_review,
                    "warnings": list(t.warnings),
                    "reason": t.reason,
                    "error": t.error,
                }
                for t in tasks
            ],
        }

    def hooks(self) -> dict[str, Callable[[StageContext, Outcome], Outcome]]:
        return {"register": self.after_register, "segment": self.after_segment, "report": self.after_report}

    def before_hooks(self) -> dict[str, Callable[[StageContext], Outcome | None]]:
        return {"register": self.before_register}

    def wrap_registry(self, registry: Registry) -> Registry:
        self._job_stages = [stage.name for stage in registry.job_stages()]
        return wrap_registry(registry, self.hooks(), self.before_hooks())


def _wrap(
    stage: Stage,
    hook: Callable[[StageContext, Outcome], Outcome] | None,
    before: Callable[[StageContext], Outcome | None] | None = None,
) -> Stage:
    inner = stage.run

    def run(ctx: StageContext) -> Outcome:
        if before is not None:
            refusal = before(ctx)
            if refusal is not None:
                return refusal
        outcome = inner(ctx)
        return outcome if hook is None or outcome.status == FAILED else hook(ctx, outcome)

    return replace(stage, run=run)


def wrap_registry(
    registry: Registry,
    hooks: dict[str, Callable[[StageContext, Outcome], Outcome]],
    before: dict[str, Callable[[StageContext], Outcome | None]] | None = None,
) -> Registry:
    """A registry whose job-scope stages named in ``hooks`` run the hook after they succeed, and
    those named in ``before`` run that check first (an outcome it returns replaces the stage's run)."""
    before = before or {}
    return Registry(
        [
            _wrap(s, hooks.get(s.name), before.get(s.name))
            if s.route is None and (s.name in hooks or s.name in before)
            else s
            for s in registry.stages()
        ]
    )
