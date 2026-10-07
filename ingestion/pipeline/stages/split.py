"""``split``: one PDF per section, plus ``split.json``, then fan out.

Builds ``_split.partial/`` with ``ingester.splitter`` and swaps it in as
``_split/`` once complete. Reports the sections it wrote, which the runner turns
into one task per stage of that section's route
(:func:`pipeline.sections.section_route`, the same choice ``ingester ingest`` makes).
"""

from __future__ import annotations

import shutil

from ingester.splitter import split_into

from .. import artefacts
from ..outcome import Outcome, StageContext, done, failed
from ..registry import CPU, JOB, Stage
from ..sections import section_route


def run(ctx: StageContext) -> Outcome:
    partial = ctx.path(artefacts.SPLIT_DIR + ".partial")
    result = split_into(ctx.source, ctx.job_dir, partial)
    warnings = tuple(result.warnings)
    if not result.sections:
        shutil.rmtree(partial, ignore_errors=True)
        return failed(
            "no section could be written: " + ("; ".join(warnings) or "segments.json is empty"),
            warnings=warnings,
        )
    artefacts.replace_dir(partial, ctx.path(artefacts.SPLIT_DIR))
    return done(
        needs_review=bool(result.skipped),
        warnings=warnings,
        sections=tuple(section.segment.label for section in result.sections),
        routes={section.segment.label: section_route(section) for section in result.sections},
    )


STAGE = Stage(name="split", scope=JOB, kind=CPU, run=run, needs=("segment",), fan_out=True)
