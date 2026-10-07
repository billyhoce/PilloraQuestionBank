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
- **fan_out**: a job-scope stage whose ``Outcome.sections`` become one task for
  every section-scope stage in the registry.

Where a stage boundary goes: where an external dependency lives (the API, the
Tesseract container), where a human may edit the artefact before the next stage
reads it, or where the work is costly and separately useful. Anything finer is a
function call inside a stage, not a stage.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .outcome import Outcome, StageContext

JOB = "job"
SECTION = "section"
CPU = "cpu"
API = "api"
SUBPROCESS = "subprocess"

MAX_STAGE_NAME = 16  # the ingest_task.stage column


@dataclass(frozen=True)
class Stage:
    name: str
    scope: str
    kind: str
    run: Callable[[StageContext], Outcome]
    needs: tuple[str, ...] = ()
    fan_out: bool = False


class Registry:
    def __init__(self, stages: list[Stage]) -> None:
        self._stages = {stage.name: stage for stage in stages}
        if len(self._stages) != len(stages):
            raise ValueError("duplicate stage name")
        for stage in stages:
            self._check(stage)
        self.order = tuple(stage.name for stage in stages)

    def _check(self, stage: Stage) -> None:
        if len(stage.name) > MAX_STAGE_NAME:
            raise ValueError(f"stage name {stage.name!r} is over {MAX_STAGE_NAME} characters")
        if stage.scope not in (JOB, SECTION) or stage.kind not in (CPU, API, SUBPROCESS):
            raise ValueError(f"stage {stage.name!r} has an unknown scope or kind")
        if stage.fan_out and stage.scope != JOB:
            raise ValueError(f"stage {stage.name!r} fans out but is not job-scope")
        for need in stage.needs:
            if need not in self._stages:
                raise ValueError(f"stage {stage.name!r} needs unknown stage {need!r}")
            if stage.scope == JOB and self._stages[need].scope == SECTION:
                raise ValueError(f"job-scope stage {stage.name!r} cannot need a section stage")

    def get(self, name: str) -> Stage:
        return self._stages[name]

    def job_stages(self) -> list[Stage]:
        return [self._stages[name] for name in self.order if self._stages[name].scope == JOB]

    def section_stages(self) -> list[Stage]:
        return [self._stages[name] for name in self.order if self._stages[name].scope == SECTION]

    def needs(self, stage: str, section: str | None) -> list[tuple[str | None, str]]:
        """The ``(section, stage)`` keys of the tasks that ``stage`` waits on."""
        keys = []
        for need in self._stages[stage].needs:
            keys.append((section if self._stages[need].scope == SECTION else None, need))
        return keys


def default_registry() -> Registry:
    from .stages import register, segment, split

    return Registry([register.STAGE, segment.STAGE, split.STAGE])
