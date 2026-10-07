"""The ingest worker process: one job at a time, claimed from the ``ingest_task`` table.

``python -m app.worker`` (configuration in the environment, see :func:`load_settings`).
Each loop writes the worker heartbeat, then asks the pipeline runner to claim and run one ready
task; a liveness thread keeps the heartbeat and the running task's lease fresh while a long
stage (OCR, a Claude call) holds the main thread. SIGTERM/SIGINT finish the current task and
exit cleanly.
"""

from __future__ import annotations

import logging
import os
import shlex
import signal
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from dataclasses import dataclass, field, replace
from pathlib import Path

from ingester import IngestConfig
from ingester import request as segment_request
from pipeline.config import PipelineConfig
from question_extractor import ExtractConfig

from app.logger import log_tokens
from app.worker.edges import Edges
from app.worker.store import SqlStore
from app.worker.sweep import run_sweep

log = logging.getLogger("pillora.worker")

LEASE_SECONDS = 600.0  # a task's lease: now + 10 minutes, refreshed by the heartbeat
HEARTBEAT_SECONDS = 30.0  # the liveness thread's period; the lease is far longer than this
POLL_SECONDS = 2.0  # idle sleep between looks at the queue
# How often a pass asks whether the daily sweep is due (an in-memory throttle; the claim itself is
# the database's), so the poll loop does not hit the heartbeat row every 2 seconds.
SWEEP_CHECK_EVERY = timedelta(minutes=10)


@dataclass(frozen=True)
class WorkerSettings:
    scratch_dir: Path = Path("/tmp/ingest")
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)
    fixtures_dir: Path | None = None
    lease_seconds: float = LEASE_SECONDS
    heartbeat_seconds: float = HEARTBEAT_SECONDS
    poll_seconds: float = POLL_SECONDS


def load_settings(env=None) -> WorkerSettings:
    """Settings from the environment; anything unset keeps the ingestion package's default.

    ``INGEST_SCRATCH_DIR`` (default ``/tmp/ingest``), ``INGEST_OCR_COMMAND`` (the Tesseract
    command, e.g. ``tesseract`` in the container), ``INGEST_SEGMENT_MODEL`` and
    ``INGEST_RETRY_MODEL``. ``INGEST_FIXTURES_DIR`` is for development only: a folder of
    ``<paper>.segments.json`` plans used in place of the Messages API.
    """
    env = os.environ if env is None else env
    ingest, extract = IngestConfig(), ExtractConfig()
    if env.get("INGEST_SEGMENT_MODEL"):
        ingest = replace(ingest, model=env["INGEST_SEGMENT_MODEL"])
    if env.get("INGEST_RETRY_MODEL"):
        ingest = replace(ingest, retry_model=env["INGEST_RETRY_MODEL"])
    if env.get("INGEST_OCR_COMMAND"):
        extract = replace(extract, ocr_command=tuple(shlex.split(env["INGEST_OCR_COMMAND"])))
    return WorkerSettings(
        scratch_dir=Path(env.get("INGEST_SCRATCH_DIR") or "/tmp/ingest"),
        pipeline=PipelineConfig(lease_seconds=LEASE_SECONDS, ingest=ingest, extract=extract),
        fixtures_dir=Path(env["INGEST_FIXTURES_DIR"]) if env.get("INGEST_FIXTURES_DIR") else None,
    )


class Worker:
    def __init__(
        self,
        session_factory,
        object_store,
        extract_metadata: Callable,
        runner_factory: Callable,
        settings: WorkerSettings | None = None,
        sleep: Callable[[float], None] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings or WorkerSettings()
        self.store = SqlStore(
            session_factory,
            self.settings.scratch_dir,
            version=os.environ.get("WORKER_VERSION"),
        )
        self.edges = Edges(
            session_factory,
            object_store,
            self.store,
            self.settings.scratch_dir,
            extract_metadata,
            self.settings.fixtures_dir,
        )
        self.runner = runner_factory(
            self.store, self.edges.job_dir, self.settings.pipeline, self.edges.wrap_registry
        )
        self._stop = threading.Event()
        self._sleep = sleep
        self._clock = clock or (lambda: datetime.now(UTC))
        self._session_factory = session_factory
        self._objects = object_store
        self._sweep_checked: datetime | None = None

    # --- lifecycle ----------------------------------------------------------
    def request_stop(self, *_args) -> None:
        """Finish the task in hand, then leave the loop."""
        self._stop.set()

    @property
    def stopping(self) -> bool:
        return self._stop.is_set()

    def start(self) -> None:
        """On start: heartbeat, hand back tasks a dead worker left past their lease, and reopen
        the finished tasks of unfinished jobs whose artefacts are gone (a lost scratch folder)."""
        self.store.touch_worker()
        for task in self.store.reset_stale(self.settings.pipeline.retry_limit):
            log.warning("task %s %s of job %s: lease expired, %s",
                        task.stage, task.section or "-", task.job_id, task.status)
        for job in self.store.jobs():
            self.store.set_job_status(job.id, job.status)
            try:
                self.runner.revalidate(job.id)
            except Exception:
                log.exception("job %s: could not revalidate its tasks", job.id)

    def sweep(self) -> None:
        """The daily expiry sweep, when due (see :mod:`app.worker.sweep`); never raises."""
        now = self._clock()
        if self._sweep_checked is not None and now - self._sweep_checked < SWEEP_CHECK_EVERY:
            return
        self._sweep_checked = now
        try:
            run_sweep(self._session_factory, self._objects, self.settings.scratch_dir, self._clock)
        except Exception:
            log.exception("the expiry sweep failed")

    def run_once(self) -> bool:
        """One look at the queue: ``True`` when a task was run."""
        self.store.touch_worker()
        self.sweep()
        try:
            return self.runner.run_one() is not None
        except Exception:
            # The runner records a failing stage; this is the store or S3 being unreachable.
            # The claimed task, if any, comes back when its lease expires.
            log.exception("the worker could not run a task")
            return False

    def run_forever(self) -> None:
        self.start()
        liveness = threading.Thread(target=self._liveness, daemon=True, name="worker-liveness")
        liveness.start()
        try:
            while not self.stopping:
                if not self.run_once():
                    self._wait(self.settings.poll_seconds)
        finally:
            self._stop.set()
            liveness.join(timeout=5)
        log.info("worker stopped")

    def _wait(self, seconds: float) -> None:
        if self._sleep is not None:
            self._sleep(seconds)
        else:
            self._stop.wait(seconds)

    def _liveness(self) -> None:
        while not self._stop.wait(self.settings.heartbeat_seconds):
            try:
                self.store.touch_worker(self.settings.lease_seconds)
            except Exception:
                log.exception("worker heartbeat failed")


def main() -> int:
    from app.db import SessionLocal
    from app.deps import get_metadata_extractor, get_object_store, get_pipeline_runner

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    # The segment stage's Messages API usage goes to the app log with the others' (and prices).
    segment_request.usage_listener = lambda model, usage: log_tokens("ingest_segment", model, usage)

    settings = load_settings()
    settings.scratch_dir.mkdir(parents=True, exist_ok=True)
    worker = Worker(
        SessionLocal,
        get_object_store(),
        get_metadata_extractor(),
        get_pipeline_runner(),
        settings,
    )
    signal.signal(signal.SIGTERM, worker.request_stop)
    signal.signal(signal.SIGINT, worker.request_stop)
    log.info("ingest worker up; scratch %s", settings.scratch_dir)
    worker.run_forever()
    return 0
