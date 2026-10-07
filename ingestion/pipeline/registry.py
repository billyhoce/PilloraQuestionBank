"""The stage registry: what stages exist, where they run, what they wait on.

Each stage has a name (it is the ``stage`` column, so at most 16 characters), a
scope, a kind, its dependencies and whether it fans out.

- **scope**: ``job`` (one task per job) or ``section`` (one task per section
  label from ``segments.json``, e.g. ``q1``, ``a1``).
- **kind**: ``cpu`` (in-process), ``api`` (the Messages API) or ``subprocess``
  (the Tesseract container). It tells a scheduler what a task will use; the
  runner treats all three alike.
- **needs**: stage names that must be ``done`` first. A section stage's needs are
  the same section's tasks, or job-scope tasks.
- **soft_needs**: stage names that must have *settled* (``done``, ``skipped`` or
  ``failed``) before the stage runs, whichever way they ended. A stage for which the
  predecessor's output is an improvement and not a requirement (``questions`` without
  OCR reads) lists it here: it waits, then runs, and is told how the need ended
  (:attr:`StageContext.unmet`). A ``blocked`` soft need does not stop it either; if
  the stage also has a hard need that is broken it is ``blocked`` as usual.
- **fan_out**: a job-scope stage whose ``Outcome.sections`` become one task for
  every stage of that section's route.
- **route**: a section stage belongs to one route's chain (``question``: ``locate``
  -> ``render``; ``table``: ``grid`` -> ``ocr`` -> ``questions`` -> ``render``). The fan-out picks each
  section's chain once, from how ``ingester.router`` would route it, so a section
  only ever gets the tasks that apply to it. Two routes may each have a stage of
  the same name (``render``): a task is identified by ``(job_id, section, stage)``
  and a section has exactly one route, so the name is unique where it matters. A
  section's route is recovered from the stages it has (:meth:`Registry.route_of`).
- **inputs / settings / outputs / version**: what the task fingerprint is made of and
  what "its artefacts exist" checks (``pipeline.fingerprint``).
- **after_sections**: a job-scope stage that also waits for every *section* task of the job
  to settle (``done``, ``skipped``, ``failed`` or ``blocked``). Sections do not exist when
  the job is submitted (``split`` fans them out), so the stage cannot name them in ``needs``;
  it lists the job stages it follows in ``soft_needs`` (a failed ``split`` must not stop it,
  and with no sections there is nothing more to wait for) and the runner holds it back until
  no section task is unsettled. It is handed every task of the job (:attr:`StageContext.tasks`).
  ``report`` is the one such stage.

Where a stage boundary goes: where an external dependency lives (the API, the
Tesseract container), where a human may edit the artefact before the next stage
reads it, or where the work is costly and separately useful. Anything finer is a
function call inside a stage, not a stage.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from .outcome import Outcome, StageContext

JOB = "job"
SECTION = "section"
CPU = "cpu"
API = "api"
SUBPROCESS = "subprocess"

MAX_STAGE_NAME = 16  # the ingest_task.stage column

# Section routes (see ingester.router.choose_route). ``unrouted`` is the chain of a
# section no extractor can take: its one task is recorded ``skipped`` with the reason.
QUESTION = "question"
TABLE = "table"
UNROUTED = "unrouted"


def _nothing(ctx: StageContext) -> Sequence:
    return ()


@dataclass(frozen=True)
class Stage:
    name: str
    scope: str
    kind: str
    run: Callable[[StageContext], Outcome]
    needs: tuple[str, ...] = ()
    soft_needs: tuple[str, ...] = ()
    fan_out: bool = False
    after_sections: bool = False  # job-scope only: also wait for every section task to settle
    route: str | None = None  # section stages only: the chain this stage belongs to
    # What the stage's artefacts are a function of, for the task fingerprint
    # (pipeline.fingerprint): the files it reads (a path is hashed by content, a string
    # is taken as is), the configuration subset and options it reads, the files it must
    # leave behind, and a version to bump when its code changes what it writes.
    inputs: Callable[[StageContext], Sequence[Path | str]] = _nothing
    settings: Callable[[StageContext], object] = _nothing
    outputs: Callable[[StageContext], Sequence[Path]] = _nothing
    version: int = 1


class Registry:
    def __init__(self, stages: list[Stage]) -> None:
        self._stages = {(stage.route, stage.name): stage for stage in stages}
        if len(self._stages) != len(stages):
            raise ValueError("duplicate stage name")
        for stage in stages:
            self._check(stage)
        self.order = tuple(stage.name for stage in stages)

    def _lookup(self, stage: Stage, need: str) -> Stage | None:
        """The stage ``need`` names, from ``stage``: its own route's, else a job stage."""
        return self._stages.get((stage.route, need)) or self._stages.get((None, need))

    def _check(self, stage: Stage) -> None:
        if len(stage.name) > MAX_STAGE_NAME:
            raise ValueError(f"stage name {stage.name!r} is over {MAX_STAGE_NAME} characters")
        if stage.scope not in (JOB, SECTION) or stage.kind not in (CPU, API, SUBPROCESS):
            raise ValueError(f"stage {stage.name!r} has an unknown scope or kind")
        if stage.fan_out and stage.scope != JOB:
            raise ValueError(f"stage {stage.name!r} fans out but is not job-scope")
        if stage.after_sections and (stage.scope != JOB or stage.fan_out):
            raise ValueError(f"stage {stage.name!r}: only a job-scope, non-fan-out stage can follow the sections")
        if (stage.route is None) != (stage.scope == JOB):
            raise ValueError(f"stage {stage.name!r}: exactly the section stages have a route")
        if set(stage.needs) & set(stage.soft_needs):
            raise ValueError(f"stage {stage.name!r} lists a need as both hard and soft")
        for need in (*stage.needs, *stage.soft_needs):
            needed = self._lookup(stage, need)
            if needed is None:
                raise ValueError(f"stage {stage.name!r} needs unknown stage {need!r}")
            if stage.scope == JOB and needed.scope == SECTION:
                raise ValueError(f"job-scope stage {stage.name!r} cannot need a section stage")

    def stages(self) -> list[Stage]:
        """Every stage, in registration order (a host wrapping them builds a new Registry)."""
        return list(self._stages.values())

    def get(self, name: str, route: str | None = None) -> Stage:
        """The stage ``name`` of ``route`` (a job stage when ``route`` is ``None``)."""
        return self._stages[(route, name)]

    def job_stages(self) -> list[Stage]:
        return [s for s in self._stages.values() if s.scope == JOB]

    def routes(self) -> list[str]:
        return list(dict.fromkeys(s.route for s in self._stages.values() if s.route))

    def section_stages(self, route: str) -> list[Stage]:
        """One route's chain, in registration order (which is run order)."""
        return [s for s in self._stages.values() if s.route == route]

    def chain_for(self, route: str) -> list[Stage]:
        """``route``'s chain, or the ``unrouted`` one when no stage is registered for it
        yet (a route whose stages have not been written is recorded, not dropped)."""
        return self.section_stages(route) or self.section_stages(UNROUTED)

    def optional(self, route: str | None) -> set[str]:
        """The stages of ``route``'s chain that are only ever soft needs (``ocr``): a section
        is not failed by one of them failing."""
        chain = self.section_stages(route) if route else []
        soft = {need for stage in chain for need in stage.soft_needs}
        hard = {need for stage in chain for need in stage.needs}
        return soft - hard

    def route_of(self, stage_names: set[str] | list[str]) -> str | None:
        """The route a section is on, from the names of the stages it has tasks for:
        the route whose first stage is among them."""
        names = set(stage_names)
        for route in self.routes():
            if self.section_stages(route)[0].name in names:
                return route
        return None

    def needs(
        self, stage: str, section: str | None, route: str | None = None
    ) -> list[tuple[str | None, str]]:
        """The ``(section, stage)`` keys of the tasks that must be ``done`` before ``stage``."""
        return self._keys(stage, section, route, soft=False)

    def soft_needs(
        self, stage: str, section: str | None, route: str | None = None
    ) -> list[tuple[str | None, str]]:
        """The keys of the tasks that must only have settled before ``stage``."""
        return self._keys(stage, section, route, soft=True)

    def _keys(
        self, stage: str, section: str | None, route: str | None, soft: bool
    ) -> list[tuple[str | None, str]]:
        this = self._stages[(route, stage)]
        keys = []
        for need in this.soft_needs if soft else this.needs:
            needed = self._lookup(this, need)
            keys.append((section if needed.scope == SECTION else None, need))
        return keys


def default_registry() -> Registry:
    from .stages import (
        grid,
        locate,
        ocr,
        questions,
        register,
        render,
        segment,
        split,
        report,
        table_render,
        unrouted,
    )

    return Registry(
        [
            register.STAGE,
            segment.STAGE,
            split.STAGE,
            # the question route: question sections and annotated_booklet answer sections
            locate.STAGE,
            render.STAGE,
            # the table route: table answer sections, scanned ones included
            grid.STAGE,
            ocr.STAGE,
            questions.STAGE,
            table_render.STAGE,
            unrouted.STAGE,
            # after every section has settled: the paper-level report
            report.STAGE,
        ]
    )
