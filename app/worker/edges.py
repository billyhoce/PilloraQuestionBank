"""The worker's S3 and database edges, composed around the pipeline's stages.

``ingestion/`` knows nothing of S3 or the app, so the edges are added here by wrapping
stages of the registry (:func:`wrap_registry`) and by resolving each job's scratch folder
(:meth:`Edges.job_dir`):

* **scratch** -- ``<scratch>/<job_id>/`` is the job's folder. Resolving it fetches ``source.pdf``
  from S3 when it is not there: the first ``register`` finds its input, and after a restart
  that lost the folder the booklet is back before any stage (or the fingerprint check) reads it.
  Artefacts that were lost with the folder are not fetched: ``Runner.revalidate`` finds their
  outputs missing and the tasks run again (slower, never wrong);
* ``register`` -- after the stage, the filename-metadata extraction (it needs the app's
  reference data), stored in ``ingest_job.report["filename_metadata"]``;
* ``report`` -- after the stage, the review images ``pages/pNN.webp`` are uploaded to
  ``tmp/ingest/{job_id}/pages/`` and the proposal and the run summary are stored on the job row.
  The images are uploaded here rather than at ``render`` because the job-level ``pages/`` folder
  (booklet page numbering, what the proposal's ``image`` paths name) is assembled by ``report``;
  ``render`` only writes each section's own ``review/`` folder.

A hook runs inside its stage's task (before ``complete``), so the task's lease covers it, a failure
fails the task, and a crash reruns it.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from pipeline import artefacts
from pipeline.outcome import FAILED, Outcome, StageContext, failed
from pipeline.registry import Registry, Stage
from pipeline.store import TaskSpec
from sqlalchemy.orm import Session

from app.models.orm import IngestJob
from app.services.ingest_jobs import job_prefix, record_filename_metadata, source_key_for
from app.storage.object_store import ObjectStore
from app.worker.store import API_OWNED, SOURCE_NAME, SqlStore

log = logging.getLogger(__name__)

PAGES_DIR = "pages"
FIXTURE_SUFFIX = ".segments.json"


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
            artefacts.write_bytes(source, self._objects.get(source_key_for(uuid.UUID(str(job_id)))))
        if self._fixtures is not None:
            self._place_fixture(job_id, folder)
        return folder

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
    def after_register(self, ctx: StageContext, outcome: Outcome) -> Outcome:
        # POST /api/import/jobs creates only the ``register`` task (the API does not know the
        # pipeline); the rest of the job-scope chain is created here, as ``Runner.submit`` does
        # locally. Idempotent, and inside register's own task: a crash reruns both.
        self._store.add_tasks([TaskSpec(ctx.job_id, name) for name in self._job_stages])
        with self._factory() as db:
            job = db.get(IngestJob, uuid.UUID(ctx.job_id))
            if job is not None:
                record_filename_metadata(job, db, self._extract_metadata)
                db.commit()
        return outcome

    def after_report(self, ctx: StageContext, outcome: Outcome) -> Outcome:
        job_uuid = uuid.UUID(ctx.job_id)
        proposal_path = ctx.path(artefacts.PROPOSAL_NAME)
        if not proposal_path.is_file():
            return failed("report wrote no proposal.json")
        proposal = artefacts.read_json(proposal_path)
        with self._factory() as db:
            job = db.get(IngestJob, job_uuid)
            if job is None or job.status in API_OWNED:
                return outcome  # cancelled while it ran: leave no objects behind
            pages = ctx.path(PAGES_DIR)
            prefix = job_prefix(job_uuid) + PAGES_DIR + "/"
            for image in sorted(pages.glob("*.webp")) if pages.is_dir() else ():
                self._objects.put(prefix + image.name, image.read_bytes(), "image/webp")
            job.proposal = proposal
            job.report = {
                **(job.report or {}),
                **self._summary(ctx.job_id, outcome),
            }
            db.commit()
        return outcome

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
        return {"register": self.after_register, "report": self.after_report}

    def wrap_registry(self, registry: Registry) -> Registry:
        self._job_stages = [stage.name for stage in registry.job_stages()]
        return wrap_registry(registry, self.hooks())


def _wrap(stage: Stage, hook: Callable[[StageContext, Outcome], Outcome]) -> Stage:
    inner = stage.run

    def run(ctx: StageContext) -> Outcome:
        outcome = inner(ctx)
        return outcome if outcome.status == FAILED else hook(ctx, outcome)

    return replace(stage, run=run)


def wrap_registry(registry: Registry, hooks: dict[str, Callable[[StageContext, Outcome], Outcome]]) -> Registry:
    """A registry whose job-scope stages named in ``hooks`` run the hook after they succeed."""
    return Registry(
        [
            _wrap(s, hooks[s.name]) if s.route is None and s.name in hooks else s
            for s in registry.stages()
        ]
    )
