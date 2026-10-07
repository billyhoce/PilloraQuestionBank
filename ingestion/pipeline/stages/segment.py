"""``segment``: label the booklet's page ranges into ``segments.json``.

Reuses the committed ``<paper>.segments.json`` fixture beside the PDF when there
is one, else asks the Messages API (``ingester.segmenter``). The file is written
either way; a booklet with no sections fails the task, with the ingester's
reasons as its error, because nothing downstream can run on it.
"""

from __future__ import annotations

from ingester.segmenter import segment_into

from .. import artefacts
from ..outcome import Outcome, StageContext, done, failed
from ..registry import API, JOB, Stage


def run(ctx: StageContext) -> Outcome:
    plan = segment_into(ctx.source, ctx.job_dir, ctx.config.ingest)
    warnings = tuple(plan.warnings)
    if not plan.segmented:
        # The last warning is the ingester's verdict; the rest are in `warnings`.
        reason = warnings[-1] if warnings else "no sections were found"
        return failed(f"not segmented: {reason}", warnings=warnings)
    return done(
        needs_review=any(segment.needs_review for segment in plan.segments),
        warnings=warnings,
    )


STAGE = Stage(name="segment", scope=JOB, kind=API, run=run, needs=("register",))
