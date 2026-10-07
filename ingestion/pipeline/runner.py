"""The runner: one loop -- claim, run, record, expand fan-out.

It works with any :class:`~pipeline.store.Store` and any ``job_dir`` resolver
(job id -> folder), so the local CLI and the webapp's worker share it. A stage
that raises is recorded as ``failed``; the loop never dies of a stage.

Dependencies live in the registry, not the store. After each task the runner
:func:`settle`\\ s its job: a ``pending`` task whose needs are all ``done`` becomes
``ready``; one whose need ``failed`` or is ``blocked`` becomes ``blocked``; one
whose need was ``skipped`` is ``skipped`` itself (there is nothing to run on).
Settling is one reader-then-writer pass, which is exact for one runner; with
several runners finishing sibling tasks at once it can miss a promotion until the
next settle, so the loop settles every unfinished job when it finds nothing to
claim.
"""

from __future__ import annotations

import logging
import threading
import time
import traceback
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from question_extractor.warnscope import collect_warnings

from .artefacts import OPTIONS_NAME, read_options, write_json
from .config import PipelineConfig
from .outcome import FAILED, Outcome, StageContext, failed
from .registry import UNROUTED, Registry
from .store import (
    BLOCKED,
    DONE,
    JOB_DONE,
    JOB_FAILED,
    JOB_QUEUED,
    JOB_RUNNING,
    PENDING,
    READY,
    RUNNING,
    SKIPPED,
    Store,
    Task,
    TaskSpec,
)
from .store import FAILED as TASK_FAILED

log = logging.getLogger(__name__)

# Statuses that stop a task's dependents from running.
_BROKEN = (TASK_FAILED, BLOCKED)


def settle(store: Store, registry: Registry, job_id: str) -> None:
    """Promote, block or skip every ``pending`` task of a job whose needs are settled."""
    tasks = {task.key: task for task in store.tasks(job_id)}
    routes = _routes(registry, tasks.values())
    while True:
        moves: list[tuple[Task, str, str]] = []
        for task in tasks.values():
            if task.status != PENDING:
                continue
            needs = [tasks.get(key) for key in registry.needs(task.stage, task.section, routes.get(task.section))]
            if any(need is None for need in needs):
                continue  # a dependency not yet created (a section stage before its fan-out)
            broken = next((n for n in needs if n.status in _BROKEN), None)
            skipped = next((n for n in needs if n.status == SKIPPED), None)
            if broken is not None:
                moves.append((task, BLOCKED, f"{broken.stage} {broken.status}"))
            elif skipped is not None:
                moves.append((task, SKIPPED, f"{skipped.stage} was skipped"))
            elif all(n.status == DONE for n in needs):
                moves.append((task, READY, ""))
        if not moves:
            return
        grouped: dict[tuple[str, str], list[int]] = {}
        for task, status, reason in moves:
            grouped.setdefault((status, reason), []).append(task.id)
        for (status, reason), ids in grouped.items():
            store.set_status(ids, status, reason)
        for task, status, reason in moves:
            tasks[task.key] = replace(task, status=status, reason=reason)


def _routes(registry: Registry, tasks) -> dict[str | None, str | None]:
    """Each section's route, from the stages it has tasks for (job stages: ``None``)."""
    stages: dict[str, set[str]] = {}
    for task in tasks:
        if task.section is not None:
            stages.setdefault(task.section, set()).add(task.stage)
    return {section: registry.route_of(names) for section, names in stages.items()}


def job_status(tasks: list[Task]) -> str:
    """queued until something starts; failed once any task failed or is blocked and
    nothing is still going; done once every task has finished."""
    if any(t.status == RUNNING for t in tasks):
        return JOB_RUNNING
    if any(t.status in _BROKEN for t in tasks) and not any(
        t.status in (READY, PENDING) for t in tasks
    ):
        return JOB_FAILED
    if all(t.status in (DONE, SKIPPED) for t in tasks):
        return JOB_DONE
    if any(t.status in (DONE, SKIPPED) or t.attempts for t in tasks):
        return JOB_RUNNING
    return JOB_QUEUED


class Runner:
    def __init__(
        self,
        store: Store,
        registry: Registry,
        job_dir: Callable[[str], Path],
        config: PipelineConfig | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.store = store
        self.registry = registry
        self.job_dir = job_dir
        self.config = config or PipelineConfig()
        self._clock = clock
        self._sleep = sleep

    # --- submitting -------------------------------------------------------
    def submit(self, job_id: str, source: Path, *, debug: bool = False) -> None:
        """Create the job and a task for every job-scope stage (``register`` runs first).

        ``debug`` asks for the debug renders as well as the review images; it is
        kept in the job folder as ``options.json`` so any runner sees it.
        """
        if debug:
            write_json(self.job_dir(job_id) / OPTIONS_NAME, {"debug": True})
        self.store.add_job(job_id, str(source))
        self.store.add_tasks(
            [TaskSpec(job_id, stage.name) for stage in self.registry.job_stages()]
        )
        self._refresh(job_id)

    # --- the loop ---------------------------------------------------------
    def run_one(self) -> Task | None:
        """Claim one ready task, run it, record it. ``None`` when nothing is ready."""
        for stale in self.store.reset_stale(self.config.retry_limit):
            log.warning("task %s %s: lease expired (%s)", stale.stage, stale.section, stale.status)
            self._refresh(stale.job_id)
        task = self.store.claim_ready(self.config.lease_seconds)
        if task is None:
            return None
        self._refresh(task.job_id)
        outcome = self._execute(task)
        if outcome.status == FAILED:
            self.store.fail(task.id, outcome)
        else:
            self.store.complete(task.id, outcome)
        if (
            outcome.status != FAILED
            and task.section is None
            and self.registry.get(task.stage).fan_out
        ):
            self._expand(task, outcome)
        self._refresh(task.job_id)
        return task

    def run(self, *, watch: bool = False) -> int:
        """Drain the queue; with ``watch`` keep polling for new work. Returns tasks run."""
        ran = 0
        while True:
            if self.run_one() is not None:
                ran += 1
                continue
            for job in self.store.jobs():
                if job.status in (JOB_QUEUED, JOB_RUNNING):
                    self._refresh(job.id)
            busy = any(t.status in (READY, RUNNING) for t in self.store.tasks())
            if not watch and not busy:
                return ran
            self._sleep(self.config.poll_interval_seconds)

    # --- internals --------------------------------------------------------
    def _execute(self, task: Task) -> Outcome:
        job = self.store.get_job(task.job_id)
        job_dir = self.job_dir(task.job_id)
        job_dir.mkdir(parents=True, exist_ok=True)
        route = None
        if task.section is not None:
            siblings = [t.stage for t in self.store.tasks(task.job_id) if t.section == task.section]
            route = self.registry.route_of(siblings)
        stage = self.registry.get(task.stage, route)
        ctx = StageContext(
            job_id=task.job_id,
            job_dir=job_dir,
            source=Path(job.source),
            config=self.config,
            section=task.section,
            debug=bool(read_options(job_dir).get("debug")),
        )
        stopped = threading.Event()
        beat = threading.Thread(target=self._heartbeats, args=(task.id, stopped), daemon=True)
        beat.start()
        started = self._clock()
        try:
            with collect_warnings() as collected:
                try:
                    outcome = stage.run(ctx)
                except Exception as exc:
                    log.debug(traceback.format_exc())
                    outcome = failed(f"{type(exc).__name__}: {exc}")
        finally:
            stopped.set()
            beat.join()
        if outcome.status == FAILED:
            log.error("%s %s failed: %s", task.stage, task.section or "-", outcome.error)
        log.info("%s %s: %s in %.1fs", task.stage, task.section or "-", outcome.status,
                 self._clock() - started)
        warnings = tuple(dict.fromkeys((*outcome.warnings, *collected)))
        return Outcome(
            status=outcome.status,
            reason=outcome.reason,
            error=outcome.error,
            needs_review=outcome.needs_review,
            warnings=warnings,
            sections=outcome.sections,
            routes=outcome.routes,
        )

    def _heartbeats(self, task_id: int, stopped: threading.Event) -> None:
        while not stopped.wait(self.config.heartbeat_seconds):
            if not self.store.heartbeat(task_id, self.config.lease_seconds):
                return

    def _expand(self, task: Task, outcome: Outcome) -> None:
        """A fan-out stage finished: one task per stage of each section's route."""
        specs = [
            TaskSpec(task.job_id, stage.name, section)
            for section in outcome.sections
            for stage in self.registry.chain_for(outcome.routes.get(section, UNROUTED))
        ]
        if specs:
            self.store.add_tasks(specs)

    def _refresh(self, job_id: str) -> None:
        settle(self.store, self.registry, job_id)
        self.store.set_job_status(job_id, job_status(self.store.tasks(job_id)))
