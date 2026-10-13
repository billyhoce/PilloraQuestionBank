"""``segment``: label the booklet's page ranges into ``segments.json``.

Reuses the committed ``<paper>.segments.json`` fixture beside the PDF when there
is one, else asks the Messages API (``ingester.segmenter``). The file is written
either way; a booklet with no sections fails the task, with the ingester's
reasons as its error, because nothing downstream can run on it.
"""

from __future__ import annotations

from ingester.segmenter import fixture_path, segment_into
from ingester.segments import read_plan

from .. import artefacts
from ..fingerprint import ingest_settings, source_input
from ..outcome import Outcome, StageContext, done, failed
from ..registry import API, JOB, Stage


def _forget_failed_plan(ctx: StageContext) -> None:
    """A failed run leaves a plan with no sections in ``segments.json``, and ``segment_into``
    reuses whatever plan is on disk: a retry (after a fixture is added, say) would be handed
    the failure back. An empty plan is not worth reusing; a real one (or a person's edit) is."""
    path = ctx.path(artefacts.SEGMENTS_NAME)
    if ctx.force or not path.is_file():
        return
    try:
        empty = not read_plan(path, pdf=ctx.source).segmented
    except Exception:
        empty = True
    if empty:
        path.unlink()


def run(ctx: StageContext) -> Outcome:
    _forget_failed_plan(ctx)
    plan = segment_into(ctx.source, ctx.job_dir, ctx.config.ingest, force=ctx.force)
    warnings = tuple(plan.warnings)
    if not plan.segmented:
        # The last warning is the ingester's verdict; the rest are in `warnings`.
        reason = warnings[-1] if warnings else "no sections were found"
        return failed(f"not segmented: {reason}", warnings=warnings)
    return done(
        needs_review=any(segment.needs_review for segment in plan.segments),
        warnings=warnings,
    )


def _inputs(ctx: StageContext) -> list:
    # the committed fixture is read instead of the model when there is one
    return [source_input(ctx), fixture_path(ctx.source)]


STAGE = Stage(
    name="segment",
    scope=JOB,
    kind=API,
    run=run,
    needs=("register",),
    inputs=_inputs,
    settings=ingest_settings,
    outputs=lambda ctx: [ctx.path(artefacts.SEGMENTS_NAME)],
)
