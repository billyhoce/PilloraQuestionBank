"""What a stage is given and what it hands back."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .config import PipelineConfig

DONE = "done"
SKIPPED = "skipped"
FAILED = "failed"


@dataclass(frozen=True)
class StageContext:
    """Everything a stage may read: where its job lives, which section, the config.

    ``source`` is the booklet PDF on local disk (the webapp's worker downloads it
    into its scratch dir first). A stage reads and writes only under ``job_dir``.
    """

    job_id: str
    job_dir: Path
    source: Path
    config: PipelineConfig
    section: str | None = None  # None for a job-scope stage
    debug: bool = False  # the job's option: also write the debug renders

    def path(self, *parts: str) -> Path:
        """An artefact path under the job dir."""
        return self.job_dir.joinpath(*parts)


@dataclass(frozen=True)
class Outcome:
    """``done | skipped(reason) | failed(error)``, plus what a human should know.

    ``sections`` is only read from a fan-out stage: the labels it found, which
    the runner turns into one task per stage of the section's route; ``routes``
    names each label's route (a label missing from it is ``unrouted``).
    """

    status: str
    reason: str = ""
    error: str = ""
    needs_review: bool = False
    warnings: tuple[str, ...] = ()
    sections: tuple[str, ...] = field(default=())
    routes: dict[str, str] = field(default_factory=dict)


def done(
    *,
    needs_review: bool = False,
    warnings: tuple[str, ...] = (),
    sections: tuple[str, ...] = (),
    routes: dict[str, str] | None = None,
) -> Outcome:
    return Outcome(
        DONE,
        needs_review=needs_review,
        warnings=tuple(warnings),
        sections=tuple(sections),
        routes=dict(routes or {}),
    )


def skipped(
    reason: str, *, needs_review: bool = False, warnings: tuple[str, ...] = ()
) -> Outcome:
    return Outcome(SKIPPED, reason=reason, needs_review=needs_review, warnings=tuple(warnings))


def failed(
    error: str, *, needs_review: bool = True, warnings: tuple[str, ...] = ()
) -> Outcome:
    return Outcome(FAILED, error=error, needs_review=needs_review, warnings=tuple(warnings))
