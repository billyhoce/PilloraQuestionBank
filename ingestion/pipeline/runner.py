"""The runner: one loop -- claim, run, record, expand fan-out.

It works with any :class:`~pipeline.store.Store` and any ``job_dir`` resolver
(job id -> folder), so the local CLI and the webapp's worker share it. A stage
that raises is recorded as ``failed``; the loop never dies of a stage.

Dependencies live in the registry, not the store. After each task the runner
:func:`settle`\\ s its job: a ``pending`` task whose needs are all ``done`` becomes
``ready``; one whose need ``failed`` or is ``blocked`` becomes ``blocked``; one
whose need was ``skipped`` is ``skipped`` itself (there is nothing to run on).
A stage with ``after_sections`` (``report``) is also held until every section task of the job
has settled, whichever way. A *soft* need (:attr:`~pipeline.registry.Stage.soft_needs`) only has to have settled:
however it ended, the dependent runs, and ``StageContext.unmet`` tells it how.
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

from . import fingerprint
from .artefacts import OPTIONS_NAME, read_options, write_json
from .config import PipelineConfig
from .outcome import FAILED, Outcome, StageContext, TaskSummary, Unmet, failed
from .registry import UNROUTED, Registry, Stage
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

# What a task that was found unchanged and not run again records as its reason.
UNCHANGED = "unchanged: its inputs match the last run and its artefacts are present"

# Statuses that stop a task's dependents from running.
_BROKEN = (TASK_FAILED, BLOCKED)
# Statuses after which a soft need no longer holds its dependent back.
_SETTLED = (DONE, SKIPPED, TASK_FAILED, BLOCKED)


def settle(store: Store, registry: Registry, job_id: str) -> None:
    """Promote, block or skip every ``pending`` task of a job whose needs are settled."""
    tasks = {task.key: task for task in store.tasks(job_id)}
    routes = _routes(registry, tasks.values())
    while True:
        moves: list[tuple[Task, str, str]] = []
        for task in tasks.values():
            if task.status != PENDING:
                continue
            route = routes.get(task.section)
            needs = [tasks.get(key) for key in registry.needs(task.stage, task.section, route)]
            soft = [tasks.get(key) for key in registry.soft_needs(task.stage, task.section, route)]
            if any(need is None for need in (*needs, *soft)):
                continue  # a dependency not yet created (a section stage before its fan-out)
            if registry.get(task.stage, route).after_sections and any(
                t.section is not None and t.status not in _SETTLED for t in tasks.values()
            ):
                continue  # a section task is still to run: the report waits for all of them
            broken = next((n for n in needs if n.status in _BROKEN), None)
            skipped = next((n for n in needs if n.status == SKIPPED), None)
            if broken is not None:
                moves.append((task, BLOCKED, f"{broken.stage} {broken.status}"))
            elif skipped is not None:
                moves.append((task, SKIPPED, f"{skipped.stage} was skipped"))
            elif all(n.status == DONE for n in needs) and all(n.status in _SETTLED for n in soft):
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
    def submit(
        self, job_id: str, source: Path, *, debug: bool = False, force: bool = False
    ) -> None:
        """Create the job and a task for every job-scope stage (``register`` runs first).

        ``debug`` asks for the debug renders as well as the review images; it is
        kept in the job folder as ``options.json`` so any runner sees it. ``force`` asks
        ``segment`` to ask the model again even when a plan or fixture is on disk.
        """
        options = {name: True for name, on in (("debug", debug), ("force", force)) if on}
        if options:
            write_json(self.job_dir(job_id) / OPTIONS_NAME, options)
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
        stage, ctx = self._prepare(task, {t.key: t for t in self.store.tasks(task.job_id)})
        expected = self._fingerprint(stage, ctx)
        unchanged = (
            expected is not None
            and task.fingerprint == expected
            and fingerprint.outputs_exist(stage, ctx)
        )
        if unchanged:
            # What the claim returns of the last run is what is still on disk: keep it.
            log.info("%s %s: unchanged, not run again", task.stage, task.section or "-")
            outcome = Outcome(
                DONE,
                reason=UNCHANGED,
                needs_review=task.needs_review,
                warnings=task.warnings,
            )
        else:
            outcome = self._execute(task, stage, ctx)
        if outcome.status == FAILED:
            self.store.fail(task.id, outcome)
        else:
            # A fan-out stage records its tasks in the same transaction as its own
            # completion (a crash between the two would let `report` run early). A fan-out
            # stage found unchanged has nothing new to create: its tasks are already there.
            self.store.complete(
                task.id,
                outcome,
                fingerprint=expected,
                spawn=() if unchanged else self._fan_out(task, stage, outcome),
            )
        self._refresh(task.job_id)
        return task

    def run(self, *, watch: bool = False) -> int:
        """Drain the queue; with ``watch`` keep polling for new work. Returns tasks run."""
        ran = 0
        for job in self.store.jobs():
            self.revalidate(job.id)
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
    def _prepare(self, task: Task, tasks: dict) -> tuple[Stage, StageContext]:
        """The stage a task runs and the context it runs with, from the job's tasks as given."""
        job = self.store.get_job(task.job_id)
        job_dir = self.job_dir(task.job_id)
        route = None
        if task.section is not None:
            siblings = [t.stage for t in tasks.values() if t.section == task.section]
            route = self.registry.route_of(siblings)
        stage = self.registry.get(task.stage, route)
        summaries = ()
        if stage.after_sections:
            summaries = self._summaries(tasks.values())
        unmet = {}
        for key in self.registry.soft_needs(task.stage, task.section, route):
            need = tasks.get(key)
            if need is not None and need.status != DONE:
                unmet[need.stage] = Unmet(need.status, need.error or need.reason)
        options = read_options(job_dir)
        ctx = StageContext(
            job_id=task.job_id,
            job_dir=job_dir,
            source=Path(job.source),
            config=self.config,
            section=task.section,
            debug=bool(options.get("debug")),
            force=bool(options.get("force")),
            unmet=unmet,
            tasks=summaries,
        )
        return stage, ctx

    @staticmethod
    def _fingerprint(stage: Stage, ctx: StageContext) -> str | None:
        """The fingerprint of the task's inputs now; ``None`` when they cannot be read
        (the task then runs, and its stage reports whatever is wrong)."""
        try:
            return fingerprint.compute(stage, ctx)
        except Exception:
            log.debug(traceback.format_exc())
            return None

    def _execute(self, task: Task, stage: Stage, ctx: StageContext) -> Outcome:
        ctx.job_dir.mkdir(parents=True, exist_ok=True)
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

    def _summaries(self, tasks) -> tuple[TaskSummary, ...]:
        """Every task of a job as the ``report`` stage reads it."""
        tasks = list(tasks)
        routes = _routes(self.registry, tasks)
        optional = {route: self.registry.optional(route) for route in self.registry.routes()}
        return tuple(
            TaskSummary(
                section=t.section,
                stage=t.stage,
                status=t.status,
                detail=t.error or t.reason,
                needs_review=t.needs_review,
                warnings=t.warnings,
                optional=t.stage in optional.get(routes.get(t.section), ()),
            )
            for t in tasks
        )

    def _heartbeats(self, task_id: int, stopped: threading.Event) -> None:
        while not stopped.wait(self.config.heartbeat_seconds):
            if not self.store.heartbeat(task_id, self.config.lease_seconds):
                return

    def _fan_out(self, task: Task, stage: Stage, outcome: Outcome) -> list[TaskSpec]:
        """A fan-out stage finished: one task per stage of each section's route."""
        if not stage.fan_out or outcome.status == FAILED:
            return []
        return [
            TaskSpec(task.job_id, chain_stage.name, section)
            for section in outcome.sections
            for chain_stage in self.registry.chain_for(outcome.routes.get(section, UNROUTED))
        ]

    # --- resuming and retrying ---------------------------------------------
    def _dependents(self, tasks: dict) -> dict:
        """For each task key, the keys of the tasks that wait on it: by ``needs``, by
        ``soft_needs``, and (the ``after_sections`` stage) every section task."""
        routes = _routes(self.registry, tasks.values())
        waiting: dict = {key: set() for key in tasks}
        for task in tasks.values():
            route = routes.get(task.section)
            stage = self.registry.get(task.stage, route)
            deps = [
                *self.registry.needs(task.stage, task.section, route),
                *self.registry.soft_needs(task.stage, task.section, route),
            ]
            if stage.after_sections:
                deps += [key for key, other in tasks.items() if other.section is not None]
            for key in deps:
                if key in waiting:
                    waiting[key].add(task.key)
        return waiting

    def revalidate(self, job_id: str) -> list[Task]:
        """Reopen the finished tasks of a job that are stale; returns them.

        A ``done`` task is stale when its recorded fingerprint is not the one its inputs
        give now (an input artefact, the configuration it reads or its code changed) or
        when an artefact it should have left is missing (a scratch folder that was
        rebuilt). Everything downstream of a stale task is stale with it. The reopened
        tasks go back to ``pending`` and then ``ready``; each, when claimed, is run again
        unless its fingerprint turns out unchanged (an upstream task that came out the
        same). Failed tasks are left for :meth:`retry`.
        """
        tasks = {t.key: t for t in self.store.tasks(job_id)}
        waiting = self._dependents(tasks)
        stale: set = set()
        for task in tasks.values():
            if task.status != DONE:
                continue
            stage, ctx = self._prepare(task, tasks)
            expected = self._fingerprint(stage, ctx)
            if expected is None or task.fingerprint != expected or not fingerprint.outputs_exist(stage, ctx):
                stale.add(task.key)
        # Everything downstream of a stale task that has finished, whichever way, is stale.
        stack = list(stale)
        while stack:
            for key in waiting[stack.pop()]:
                if key not in stale and tasks[key].status in (DONE, SKIPPED):
                    stale.add(key)
                    stack.append(key)
        return self._reopen(job_id, [tasks[key] for key in stale], "stale")

    def retry(self, job_id: str) -> list[Task]:
        """Return a job's failed and blocked tasks, and everything downstream of them that
        has finished, to ``ready`` (via ``pending``: a task whose needs are not ``done`` yet
        waits for them). Their attempts start again. Tasks that are running or still waiting
        are left alone, as is everything not downstream of a failure. Returns the tasks reopened."""
        tasks = {t.key: t for t in self.store.tasks(job_id)}
        waiting = self._dependents(tasks)
        chosen = {key for key, t in tasks.items() if t.status in _BROKEN}
        stack = list(chosen)
        while stack:
            for key in waiting[stack.pop()]:
                if key not in chosen and tasks[key].status in (DONE, SKIPPED):
                    chosen.add(key)
                    stack.append(key)
        return self._reopen(job_id, [tasks[key] for key in chosen], "retry")

    def _reopen(self, job_id: str, tasks: list[Task], why: str) -> list[Task]:
        tasks = sorted(tasks, key=lambda t: t.id)
        if tasks:
            for task in tasks:
                log.info("%s %s: %s, back to the queue", task.stage, task.section or "-", why)
            self.store.reopen([t.id for t in tasks])
            self._refresh(job_id)
        return tasks

    def _refresh(self, job_id: str) -> None:
        settle(self.store, self.registry, job_id)
        self.store.set_job_status(job_id, job_status(self.store.tasks(job_id)))
